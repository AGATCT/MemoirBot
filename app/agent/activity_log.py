"""
Agent 活动日志。

内存中记录所有子 Agent 的运行状态、结果和耗时，
供前端面板实时展示。支持逐条追加详情。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_ENTRIES = 50


@dataclass
class AgentActivity:
    """单次 Agent 运行记录。"""
    id: str
    agent_type: str
    label: str
    status: str
    started_at: str
    finished_at: str = ""
    duration_ms: int = 0
    summary: str = ""
    detail: str = ""
    session_id: str = ""
    items: list[str] = field(default_factory=list)  # 逐条详情


class AgentActivityLog:
    """全局 Agent 活动日志（内存）。"""

    def __init__(self):
        self._entries: list[AgentActivity] = []
        self._counter = 0

    def start(self, agent_type: str, label: str,
              session_id: str = "", detail: str = "") -> str:
        self._counter += 1
        activity = AgentActivity(
            id=f"act_{self._counter}",
            agent_type=agent_type,
            label=label,
            status="running",
            started_at=datetime.now().isoformat(),
            session_id=session_id,
            detail=detail,
        )
        self._entries.append(activity)
        self._trim()
        return activity.id

    def add_item(self, activity_id: str, item: str):
        """追加一条详情（在 agent 运行中调用）。"""
        for entry in self._entries:
            if entry.id == activity_id:
                entry.items.append(item)
                return

    def finish(self, activity_id: str, status: str = "completed",
               summary: str = "", items: list[str] | None = None):
        """标记完成，可传入完整 items 列表覆盖。"""
        for entry in self._entries:
            if entry.id == activity_id:
                entry.status = status
                entry.finished_at = datetime.now().isoformat()
                if entry.started_at:
                    try:
                        started = datetime.fromisoformat(entry.started_at)
                        entry.duration_ms = int(
                            (datetime.now() - started).total_seconds() * 1000
                        )
                    except Exception:
                        pass
                entry.summary = summary
                if items:
                    entry.items = items
                return

    def get_recent(self, limit: int = 20) -> list[dict]:
        recent = self._entries[-limit:]
        return [
            {
                "id": e.id,
                "agent_type": e.agent_type,
                "label": e.label,
                "status": e.status,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
                "duration_ms": e.duration_ms,
                "summary": e.summary,
                "detail": e.detail,
                "items": e.items,
            }
            for e in recent
        ]

    def running_count(self) -> int:
        return sum(1 for e in self._entries if e.status == "running")

    def _trim(self):
        if len(self._entries) > MAX_ENTRIES:
            self._entries = self._entries[-MAX_ENTRIES:]


_log: AgentActivityLog | None = None


def get_activity_log() -> AgentActivityLog:
    global _log
    if _log is None:
        _log = AgentActivityLog()
    return _log
