"""
记忆合并/去重引擎。

供 DreamAgent 使用。
"""

import logging
from datetime import datetime

from app.memory.schemas import Memory

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """记忆合并引擎。"""

    async def find_duplicates(self, memories: list[Memory]) -> list[list[Memory]]:
        by_type: dict[str, list[Memory]] = {}
        for m in memories:
            by_type.setdefault(m.type, []).append(m)

        groups = []
        for mems in by_type.values():
            if len(mems) < 2:
                continue
            used = set()
            for i, a in enumerate(mems):
                if a.id in used:
                    continue
                group = [a]
                for j, b in enumerate(mems):
                    if j <= i or b.id in used:
                        continue
                    if self._is_duplicate(a, b):
                        group.append(b)
                        used.add(b.id)
                if len(group) > 1:
                    groups.append(group)
        return groups

    def _is_duplicate(self, a: Memory, b: Memory) -> bool:
        if a.description.strip() == b.description.strip():
            return True
        if a.description[:30].strip() == b.description[:30].strip():
            return True
        if a.type == b.type and a.content[:50].strip() == b.content[:50].strip():
            return True
        return False

    async def merge(self, primary: Memory, secondaries: list[Memory]) -> Memory:
        primary.updated_at = datetime.now().isoformat()
        logger.info(f"合并记忆: {primary.id} ← {[s.id for s in secondaries]}")
        return primary
