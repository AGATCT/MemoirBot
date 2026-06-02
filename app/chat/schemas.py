"""
聊天域数据模型。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """单条聊天消息。"""
    msg_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    reasoning_content: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SessionMetadata(BaseModel):
    """会话元数据。"""
    session_id: str
    title: str = "新对话"
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    message_count: int = 0
    extraction_offset: int = 0
    is_active: bool = True
    session_memory_message_count: int = 0  # 会话笔记已覆盖的消息数
    compacted_at: int = 0  # 上次压缩点（消息索引）


class CreateSessionRequest(BaseModel):
    """创建会话请求。"""
    title: str | None = None


class CreateSessionResponse(BaseModel):
    """创建会话响应。"""
    session_id: str
    title: str
    created_at: str


class SendMessageRequest(BaseModel):
    """发送消息请求。"""
    content: str
    thinking: bool = False
    reasoning_effort: str = "high"  # high | max


class RenameSessionRequest(BaseModel):
    """重命名会话请求。"""
    title: str


class SessionListItem(BaseModel):
    """会话列表项。"""
    session_id: str
    title: str
    updated_at: str
    message_count: int
    is_active: bool
