"""
LLM Provider 抽象基类。

所有 LLM 提供商必须实现此接口。
支持三种调用模式：chat（非流式）、chat_stream（流式）、chat_with_tools（工具调用）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncGenerator


@dataclass
class LLMConfig:
    """LLM 提供商配置。"""
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.7

    # 额外参数，传递给 API
    extra: dict = field(default_factory=dict)


@dataclass
class ToolCall:
    """LLM 返回的工具调用。"""
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    """工具调用结果。"""
    tool_call_id: str
    content: str


class LLMProvider(ABC):
    """LLM 提供商抽象基类。"""

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def chat(self, messages: list[dict], **kwargs) -> str:
        """非流式聊天，返回完整响应文本。"""
        ...

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式聊天，逐块返回响应文本。"""
        ...

    @abstractmethod
    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        **kwargs,
    ) -> dict:
        """带工具调用的聊天。

        Returns:
            dict with keys:
                - "content": str | None  (文本响应)
                - "tool_calls": list[ToolCall] | None  (工具调用列表)
                - "finish_reason": str
        """
        ...

    async def chat_with_retry(
        self, messages: list[dict], max_retries: int = 3, **kwargs
    ) -> str:
        """带重试的非流式聊天（指数退避）。"""
        import asyncio
        import logging

        logger = logging.getLogger(__name__)
        last_error = None

        for attempt in range(max_retries):
            try:
                return await self.chat(messages, **kwargs)
            except Exception as e:
                last_error = e
                wait = 2**attempt * 2
                logger.warning(
                    f"LLM 调用失败 (尝试 {attempt + 1}/{max_retries}): {e}，"
                    f"{wait}秒后重试..."
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)

        raise last_error  # type: ignore[misc]
