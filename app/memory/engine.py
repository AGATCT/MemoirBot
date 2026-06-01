"""
记忆引擎。

协调记忆的存储、检索、上下文构建。
"""

import logging
from datetime import datetime

from app.memory.schemas import Memory
from app.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryEngine:
    """记忆引擎。"""

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()
        self._profile = None

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def has_memories(self) -> bool:
        return await self.store.memory_count() > 0

    async def get_relevant_context(self, limit: int = 15) -> str:
        """获取所有活跃记忆的格式化文本。"""
        memories = await self.store.read_all_memories()
        if not memories:
            return ""

        type_priority = {"user": 0, "state": 1, "event": 2, "feedback": 3, "reference": 4}
        memories.sort(key=lambda m: type_priority.get(m.type, 4))

        if limit and len(memories) > limit:
            memories = memories[:limit]

        lines = []
        type_labels = {
            "user": "用户信息", "feedback": "反馈指引",
            "reference": "外部参考", "event": "事件", "state": "当前状态",
        }
        for m in memories:
            label = type_labels.get(m.type, m.type)
            lines.append(f"[{label}] {m.content}")

        return "\n".join(lines) if lines else ""

    async def get_memory_manifest(self) -> str:
        headers = await self.store.list_memories()
        if not headers:
            return "（暂无已有记忆）"
        return "\n".join(
            f"- [{h.type}] {h.filename}: {h.description}" for h in headers
        )

    # ------------------------------------------------------------------
    # 存储
    # ------------------------------------------------------------------

    async def store_memories(self, memories: list[Memory], session_id: str = "") -> list[Memory]:
        stored = []
        for mem in memories:
            mem.source = mem.source or session_id
            await self.store.write_memory(mem)
            stored.append(mem)
            logger.info(f"记忆已保存: [{mem.type}] {mem.name} — {mem.description}")
        return stored

    # ------------------------------------------------------------------
    # 类型定义（供 prompt 使用）
    # ------------------------------------------------------------------

    def get_type_definitions_text(self) -> str:
        from app.memory.types import MEMORY_TYPE_DEFINITIONS
        lines = ["# 记忆类型\n"]
        for key, info in MEMORY_TYPE_DEFINITIONS.items():
            lines.append(f"## {info['name']} ({key})")
            lines.append(f"**描述**: {info['description']}")
            lines.append(f"**何时保存**: {info['when_to_save']}")
            lines.append(f"**如何使用**: {info['how_to_use']}")
            for ex in info.get("examples", []):
                lines.append(f"  - {ex}")
            lines.append("")
        return "\n".join(lines)
