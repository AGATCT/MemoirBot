"""
矛盾检测器。

比较两条记忆，判断是否矛盾。
简易实现使用关键词匹配，后续可接入 LLM 深度判断。
"""

import logging
import uuid

from app.memory.schemas import Memory, Contradiction

logger = logging.getLogger(__name__)


class ContradictionDetector:
    """矛盾检测器。"""

    NEGATION_PATTERNS = [
        ("喜欢", "不喜欢"), ("是", "不是"), ("使用", "不使用"),
    ]

    async def detect(self, new_memory: Memory, candidates: list[Memory]) -> list[Contradiction]:
        contradictions = []
        for old in candidates:
            if old.id == new_memory.id:
                continue
            score = self._score_conflict(new_memory, old)
            if score > 0.5:
                severity = "high" if score > 0.8 else "medium"
                contra = Contradiction(
                    id=f"contra_{uuid.uuid4().hex[:8]}",
                    memory_a_id=new_memory.id,
                    memory_b_id=old.id,
                    memory_a_content=new_memory.content[:200],
                    memory_b_content=old.content[:200],
                    description=f"可能矛盾: '{new_memory.description}' vs '{old.description}'",
                    severity=severity,
                )
                contradictions.append(contra)
        return contradictions

    def _score_conflict(self, a: Memory, b: Memory) -> float:
        if a.type != b.type:
            return 0.0
        score = 0.0
        for pos, neg in self.NEGATION_PATTERNS:
            if (pos in a.content and neg in b.content) or (neg in a.content and pos in b.content):
                score += 0.6
                break
        if a.type in ("user", "state"):
            score += 0.2
        return min(score, 1.0)
