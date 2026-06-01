"""
记忆系统数据模型。

极简设计，对齐 coding-agent-main：
- 记忆文件 = Markdown + YAML frontmatter（name, description, type）
- MEMORY.md = 索引文件，每行一个指针
- 内容即记忆本身，不需要额外的元数据评分
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# 五种记忆类型
MEMORY_TYPES = ["user", "feedback", "reference", "event", "state"]
MemoryType = Literal["user", "feedback", "reference", "event", "state"]


class Memory(BaseModel):
    """单条记忆。

    frontmatter 字段：name, description, type
    正文：content（feedback 类型含 **Why:** / **How to apply:** 结构）
    """
    id: str
    type: MemoryType
    name: str              # kebab-case，文件名 slug
    description: str       # 一行摘要，用于 MEMORY.md 索引
    content: str           # 记忆正文
    source: str = ""       # 来源 session_id 或 diary_id
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class MemoryHeader(BaseModel):
    """MEMORY.md 中一行的解析结果。"""
    id: str
    filename: str
    type: MemoryType
    description: str


# =============================================================================
# 剩余模型不变
# =============================================================================


class Contradiction(BaseModel):
    """两条记忆之间的矛盾。"""
    id: str
    memory_a_id: str
    memory_b_id: str
    memory_a_content: str
    memory_b_content: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"
    detected_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: Literal["unresolved", "resolved", "dismissed"] = "unresolved"
    resolution: str | None = None
    surviving_id: str | None = None
    flagged_for_user: bool = False


class DreamRecord(BaseModel):
    """一次 Dream 运行的记录。"""
    run_at: str
    duration_seconds: float = 0
    memories_merged: int = 0
    memories_archived: int = 0
    contradictions_found: int = 0
    contradictions_resolved: int = 0
    contradictions_flagged: int = 0
    profile_updated: bool = False


class UserProfile(BaseModel):
    """用户画像。"""
    version: int = 1
    name: str = "用户"
    summary: str = ""
    preferences: dict[str, str] = Field(default_factory=dict)
    traits: list[str] = Field(default_factory=list)
    life_context: dict[str, str] = Field(default_factory=dict)
    recent_events: list[dict] = Field(default_factory=list)
    current_focus: str = ""
    goals: list[str] = Field(default_factory=list)
    facts_summary: dict[str, list[str]] = Field(default_factory=dict)
    last_updated: str = Field(default_factory=lambda: datetime.now().isoformat())


class DreamState(BaseModel):
    """Dream 调度状态。"""
    last_dream_run: str = ""
    last_dream_result: str = ""
    conversations_since_dream: int = 0
    min_conversations_for_dream: int = 5
    dream_interval_hours: int = 24
    next_dream_time: str = ""
    is_dream_running: bool = False
    extraction_interval_messages: int = 5
