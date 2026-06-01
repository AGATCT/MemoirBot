"""
日记域数据模型。
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class DiaryEntry(BaseModel):
    """日记条目。"""
    id: str  # 格式: diary_YYYYMMDD
    date: str  # 格式: YYYY-MM-DD
    content: str = ""
    mood: str | None = None  # happy, sad, neutral, productive, tired, excited
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class DiaryEntryCreate(BaseModel):
    """创建/更新日记请求。"""
    date: str  # YYYY-MM-DD
    content: str = ""
    mood: str | None = None
    tags: list[str] = Field(default_factory=list)


class DiaryEntrySummary(BaseModel):
    """日记摘要（列表用）。"""
    id: str
    date: str
    mood: str | None = None
    tags: list[str] = Field(default_factory=list)
    preview: str = ""  # 内容前 100 字


class DiaryMonthView(BaseModel):
    """月份日记视图。"""
    year: int
    month: int
    entries: dict[int, DiaryEntrySummary] = Field(default_factory=dict)
