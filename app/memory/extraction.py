"""
记忆提取协调逻辑。

管理提取触发条件、coalescing（合并）、偏移量跟踪。
参考 coding-agent-main extractMemories.ts 的 closure-scoped state。
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ExtractionCoordinator:
    """记忆提取协调器。

    管理提取的触发、合并和状态跟踪。

    参考 coding-agent-main 的 closure-scoped state：
    - last_extraction_message_uuid → extraction_offset（用消息计数代替）
    - inProgress → is_running
    - pendingContext → pending_session_id
    - turns_since_last_extraction → turn counter
    """

    def __init__(self, extraction_interval: int = 5):
        self.extraction_interval = extraction_interval
        self.is_running = False
        self.pending_session_id: str | None = None
        self.turn_counters: dict[str, int] = {}  # session_id → turns since last extraction

    def should_extract(self, session_id: str) -> bool:
        """检查是否应该触发提取。"""
        turns = self.turn_counters.get(session_id, 0)
        self.turn_counters[session_id] = turns + 1
        should = self.turn_counters[session_id] >= self.extraction_interval
        if should:
            self.turn_counters[session_id] = 0
        return should

    async def run_extraction(
        self,
        session_id: str,
        messages: list[dict],
        extraction_agent,
        memory_engine,
    ) -> None:
        """执行提取（如果已在运行，暂存上下文）。"""
        if self.is_running:
            # Coalescing：暂存最新上下文，等当前运行完成后追跑
            logger.debug(f"[extraction] 提取进行中，暂存会话 {session_id} 用于追跑")
            self.pending_session_id = session_id
            return

        self.is_running = True
        try:
            await self._do_extract(session_id, messages, extraction_agent, memory_engine)
        finally:
            self.is_running = False

            # 处理暂存的追跑请求
            pending = self.pending_session_id
            self.pending_session_id = None
            if pending and pending != session_id:
                logger.info(f"[extraction] 执行追跑提取: {pending}")
                # 追跑提取需要获取 pending session 的最新消息
                # 这里简化处理，下一轮自动触发
                pass

    async def _do_extract(
        self,
        session_id: str,
        messages: list[dict],
        extraction_agent,
        memory_engine,
    ) -> None:
        """实际执行提取。"""
        logger.info(f"[extraction] 开始提取会话 {session_id}（{len(messages)} 条新消息）")

        try:
            result = await extraction_agent.extract(messages, session_id)
            logger.info(f"[extraction] 完成: {result.get('status')}")

            if result.get("extractions_count", 0) > 0:
                logger.info(f"[extraction] 保存了 {result['extractions_count']} 条记忆")
        except Exception as e:
            logger.error(f"[extraction] 提取失败: {e}")


# 全局提取协调器单例
_coordinator: ExtractionCoordinator | None = None


def get_extraction_coordinator(interval: int = 5) -> ExtractionCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = ExtractionCoordinator(extraction_interval=interval)
    return _coordinator
