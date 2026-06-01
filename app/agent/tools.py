"""
子 Agent 共享工具。

提供记忆系统子 Agent 共同使用的工具实现。
"""

import logging
from app.memory.schemas import Memory

logger = logging.getLogger(__name__)


def create_memory_tools(store, profile_manager=None):
    tools = {}

    async def read_all_memories(mem_type: str | None = None) -> dict:
        headers = await store.list_memories(mem_type)
        return {
            "count": len(headers),
            "memories": [
                {"id": h.id, "filename": h.filename, "type": h.type, "description": h.description}
                for h in headers
            ],
        }

    async def read_memory_detail(name: str) -> dict:
        mem = await store.read_memory(name)
        if mem is None:
            return {"error": f"记忆不存在: {name}"}
        return {
            "id": mem.id, "type": mem.type, "name": mem.name,
            "description": mem.description, "content": mem.content,
            "source": mem.source,
        }

    async def write_memory(
        type: str, name: str, description: str, content: str,
        source: str = "",
    ) -> dict:
        existing = await store.read_memory(name)
        memory = Memory(
            id=existing.id if existing else f"mem_{name}",
            type=type, name=name, description=description, content=content,
            source=source,
        )
        await store.write_memory(memory)
        return {"status": "saved", "name": memory.name, "description": memory.description}

    async def delete_memory(name: str) -> dict:
        deleted = await store.delete_memory(name)
        return {"status": "deleted" if deleted else "not_found"}

    async def read_profile() -> dict:
        if profile_manager:
            profile = await profile_manager.get_profile()
            return profile.model_dump()
        return {"error": "profile_manager 未初始化"}

    tools["read_all_memories"] = read_all_memories
    tools["read_memory_detail"] = read_memory_detail
    tools["write_memory"] = write_memory
    tools["delete_memory"] = delete_memory
    tools["read_profile"] = read_profile
    return tools
