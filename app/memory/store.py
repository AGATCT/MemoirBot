"""
记忆文件存储。

负责记忆文件的 CRUD、MEMORY.md 索引管理。
参考 coding-agent-main memoryScan.ts + memdir.ts。
"""

import logging
from datetime import datetime
from pathlib import Path

from app.memory.schemas import Memory, MemoryHeader
from app.storage import file_store
from app.storage.paths import get_memories_dir

logger = logging.getLogger(__name__)

MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000


class MemoryStore:
    """记忆持久化存储。"""

    def __init__(self, memory_dir: Path | None = None):
        self.memory_dir = memory_dir or get_memories_dir()
        self.index_path = self.memory_dir / "MEMORY.md"

    def _filename(self, name: str) -> str:
        return f"{name}.md"

    def _filepath(self, name: str) -> Path:
        return self.memory_dir / self._filename(name)

    # ------------------------------------------------------------------
    # 记忆文件 CRUD
    # ------------------------------------------------------------------

    async def read_memory(self, name: str) -> Memory | None:
        filepath = self._filepath(name)
        post = await file_store.read_markdown(filepath)
        if post is None:
            return None
        meta = dict(post.metadata) if post.metadata else {}
        return Memory(
            id=meta.get("id", f"mem_{name}"),
            type=meta.get("type", "user"),
            name=meta.get("name", name),
            description=meta.get("description", ""),
            content=post.content or "",
            source=meta.get("source", ""),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
        )

    async def write_memory(self, memory: Memory) -> None:
        filepath = self._filepath(memory.name)
        memory.updated_at = datetime.now().isoformat()
        metadata = {
            "name": memory.name,
            "description": memory.description,
            "type": memory.type,
            "source": memory.source,
            "updated_at": memory.updated_at,
        }
        if not memory.created_at:
            memory.created_at = memory.updated_at
        metadata["created_at"] = memory.created_at
        metadata = {k: v for k, v in metadata.items() if v}

        await file_store.write_markdown(filepath, memory.content, metadata)
        await self._update_index(memory)

    async def delete_memory(self, name: str) -> bool:
        filepath = self._filepath(name)
        deleted = await file_store.delete_file(filepath)
        if deleted:
            await self._remove_from_index(name)
        return deleted

    # ------------------------------------------------------------------
    # 索引读取
    # ------------------------------------------------------------------

    async def list_memories(self, mem_type: str | None = None) -> list[MemoryHeader]:
        headers = await self._read_index()
        if not headers:
            return []

        import asyncio

        async def resolve_type(h: MemoryHeader) -> MemoryHeader | None:
            try:
                real = await self._read_memory_type(h.filename)
                h.type = real
                if mem_type and real != mem_type:
                    return None
                return h
            except Exception:
                return h

        resolved = await asyncio.gather(*(resolve_type(h) for h in headers), return_exceptions=True)
        return [r for r in resolved if isinstance(r, MemoryHeader)]

    async def read_all_memories(self) -> list[Memory]:
        headers = await self.list_memories()
        memories = []
        for h in headers:
            mem = await self.read_memory(h.id)
            if mem:
                memories.append(mem)
        return memories

    async def memory_count(self) -> int:
        return len(await self.list_memories())

    # ------------------------------------------------------------------
    # 内部索引方法
    # ------------------------------------------------------------------

    async def _read_index(self) -> list[MemoryHeader]:
        if not self.index_path.exists():
            return []
        content = await file_store.read_text(self.index_path)
        if not content:
            return []

        headers = []
        for raw in content.split("\n"):
            line = raw.strip()
            if line.startswith("- [") and "](" in line:
                try:
                    filename = line.split("](")[1].split(")")[0]
                    desc_part = line.split(" — ", 1)
                    description = desc_part[1] if len(desc_part) > 1 else ""
                    name = filename.replace(".md", "")
                    headers.append(MemoryHeader(
                        id=name, filename=filename, type="user", description=description,
                    ))
                except (ValueError, IndexError):
                    continue
        return headers

    async def _read_memory_type(self, filename: str) -> str:
        name = filename.replace(".md", "")
        metadata = await file_store.read_frontmatter_only(self._filepath(name))
        return metadata.get("type", "user")

    async def _update_index(self, memory: Memory) -> None:
        filename = self._filename(memory.name)
        new_line = f"- [{memory.name}]({filename}) — {memory.description}"

        new_lines = []
        for line in (await self._read_index_raw()).split("\n") if self.index_path.exists() else []:
            if f"]({filename})" in line:
                new_lines.append(new_line)
                line = None  # mark as updated
            elif line.strip():
                new_lines.append(line.rstrip())

        if not any(f"]({filename})" in l for l in new_lines):
            new_lines.append(new_line)

        content = "\n".join(line for line in new_lines if line)
        if len(content.encode("utf-8")) > MAX_ENTRYPOINT_BYTES:
            logger.warning(f"MEMORY.md 超过 {MAX_ENTRYPOINT_BYTES} 字节限制")
        await file_store.write_text_atomic(self.index_path, content)

    async def _read_index_raw(self) -> str:
        if not self.index_path.exists():
            return ""
        try:
            return await file_store.read_text(self.index_path)
        except Exception:
            return ""

    async def _remove_from_index(self, name: str) -> None:
        filename = self._filename(name)
        if not self.index_path.exists():
            return
        content = await self._read_index_raw()
        new_lines = [
            line.rstrip() for line in content.split("\n")
            if f"]({filename})" not in line and line.strip()
        ]
        await file_store.write_text_atomic(self.index_path, "\n".join(new_lines))

    # ------------------------------------------------------------------
    # 相似记忆查找
    # ------------------------------------------------------------------

    async def find_similar(self, memory: Memory, limit: int = 5) -> list[Memory]:
        headers = await self.list_memories(mem_type=memory.type)
        if not headers:
            return []
        results = []
        for h in headers:
            if h.id == memory.name:
                continue
            mem = await self.read_memory(h.id)
            if mem:
                results.append(mem)
        return results[:limit]
