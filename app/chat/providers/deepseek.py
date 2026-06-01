"""
DeepSeek API 提供商实现。

支持 chat、chat_stream、chat_with_tools 三种调用模式。
使用 httpx 进行异步 HTTP 请求，兼容 OpenAI API 格式。
"""

import json
import logging
from typing import AsyncGenerator

import httpx

from app.chat.providers.base import LLMConfig, LLMProvider, ToolCall

logger = logging.getLogger(__name__)


class DeepSeekProvider(LLMProvider):
    """DeepSeek API 提供商。

    通过 OpenAI 兼容的 API 端点调用 DeepSeek 模型。
    支持 deepseek-chat 等模型。
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # chat — 非流式
    # ------------------------------------------------------------------

    async def chat(self, messages: list[dict], **kwargs) -> str:
        payload = self._build_payload(messages, stream=False, **kwargs)
        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # chat_stream — 流式
    # ------------------------------------------------------------------

    async def chat_stream(
        self, messages: list[dict], **kwargs
    ) -> AsyncGenerator[str, None]:
        payload = self._build_payload(messages, stream=True, **kwargs)

        async with self.client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    # ------------------------------------------------------------------
    # chat_with_tools — 工具调用
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        **kwargs,
    ) -> dict:
        payload = self._build_payload(messages, stream=False, **kwargs)
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        result: dict = {
            "content": message.get("content"),
            "tool_calls": None,
            "finish_reason": finish_reason,
        }

        raw_tool_calls = message.get("tool_calls", [])
        if raw_tool_calls:
            result["tool_calls"] = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                )
                for tc in raw_tool_calls
            ]

        return result

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _build_payload(
        self, messages: list[dict], stream: bool = False, **kwargs
    ) -> dict:
        """构建 API 请求体。"""
        payload = {
            "model": kwargs.get("model", self.config.model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": stream,
        }
        # 合并额外参数
        payload.update(self.config.extra)
        payload.update(
            {k: v for k, v in kwargs.items() if k not in ("model", "max_tokens", "temperature")}
        )
        return payload
