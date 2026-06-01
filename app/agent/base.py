"""
子 Agent 基类。

实现 tool-use 循环的子 Agent 模式（参考 coding-agent-main forkedAgent.ts）。
子 Agent 通过 LLM 工具调用与系统交互，在受限的权限沙箱中运行。

设计原则：
- 统一 tool-use 循环：LLM 调用 → 工具执行 → 结果回传 → 继续循环
- max_turns 上限：防止无限制的 LLM 调用（默认 5 轮）
- 权限沙箱：仅允许指定的工具
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.chat.providers.base import LLMProvider, ToolCall

logger = logging.getLogger(__name__)


# =============================================================================
# Tool 定义
# =============================================================================


@dataclass
class Tool:
    """子 Agent 可用的工具。

    类似 OpenAI function calling 的 tool 定义。
    """
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[..., Awaitable[dict]]  # 工具执行函数

    def to_openai_format(self) -> dict:
        """转换为 OpenAI/DeepSeek 兼容的工具定义格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class SubAgentResult:
    """子 Agent 执行结果。"""
    success: bool
    output: dict | None = None  # 结构化输出
    text: str = ""  # 最终文本响应
    turns_used: int = 0
    error: str | None = None


# =============================================================================
# SubAgent 基类
# =============================================================================


class SubAgent:
    """子 Agent 基类 — 实现 tool-use 循环。

    子类通过提供 system_prompt 和 tools 来定义 agent 的行为。

    使用方式：
        agent = MyAgent(provider, system_prompt="...", tools=[...])
        result = await agent.run("任务描述")
    """

    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str,
        tools: list[Tool] | None = None,
        max_turns: int = 5,
    ):
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools = {t.name: t for t in (tools or [])}
        self.tool_defs = [t.to_openai_format() for t in (tools or [])]
        self.max_turns = max_turns

    async def run_with_prefix(
        self, prefix_messages: list[dict], input_text: str
    ) -> SubAgentResult:
        """在已有消息前缀上追加输入后执行 tool-use 循环。

        prefix_messages 的 system prompt 会被复用（不替换），
        从而实现 API 前缀缓存命中。仅在末尾追加一条 user 消息。
        """
        messages = list(prefix_messages)  # 浅拷贝
        messages.append({"role": "user", "content": input_text})
        return await self._run_loop(messages)

    async def run(self, input_text: str) -> SubAgentResult:
        """执行 tool-use 循环（使用 agent 自己的 system prompt）。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": input_text},
        ]
        return await self._run_loop(messages)

    async def _run_loop(self, messages: list[dict]) -> SubAgentResult:
        """执行 tool-use 循环（使用给定的 messages，不复用 self.system_prompt）。"""
        for turn in range(self.max_turns):
            logger.debug(f"SubAgent turn {turn + 1}/{self.max_turns}")

            try:
                if self.tool_defs:
                    response = await self.provider.chat_with_tools(
                        messages, self.tool_defs
                    )
                else:
                    # 无工具时使用普通 chat
                    content = await self.provider.chat(messages)
                    response = {
                        "content": content,
                        "tool_calls": None,
                        "finish_reason": "stop",
                    }

            except Exception as e:
                logger.error(f"SubAgent LLM 调用失败 (turn {turn + 1}): {e}")
                return SubAgentResult(
                    success=False,
                    error=str(e),
                    turns_used=turn + 1,
                )

            # 处理工具调用
            tool_calls: list[ToolCall] = response.get("tool_calls") or []
            if tool_calls:
                # 添加 assistant 消息（含工具调用）
                messages.append(self._assistant_msg_with_tools(tool_calls))

                # 执行工具并添加结果
                for tc in tool_calls:
                    tool_result = await self._execute_tool(tc)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
                continue

            # 无工具调用 → 最终输出
            content = response.get("content") or ""
            text = content.strip()

            # 尝试解析为 JSON（LLM 常用 markdown 代码块包裹 JSON）
            try:
                output = json.loads(text) if text else None
            except json.JSONDecodeError:
                output = self._extract_json(text)

            return SubAgentResult(
                success=True,
                output=output,
                text=text,
                turns_used=turn + 1,
            )

        # 达到最大轮次
        logger.warning(f"SubAgent 达到最大轮次 {self.max_turns}，强制结束")
        return SubAgentResult(
            success=False,
            error=f"达到最大轮次 ({self.max_turns})",
            turns_used=self.max_turns,
        )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """从文本中提取 JSON，处理 markdown 代码块包裹。"""
        if not text:
            return None
        # 去掉 ```json ... ``` 包裹
        m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        # 尝试找第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    async def _execute_tool(self, tool_call: ToolCall) -> dict:
        """执行工具调用。"""
        tool = self.tools.get(tool_call.name)
        if tool is None:
            return {"error": f"未知工具: {tool_call.name}"}

        try:
            logger.debug(f"执行工具: {tool_call.name}({tool_call.arguments})")
            result = await tool.handler(**tool_call.arguments)
            return result
        except Exception as e:
            logger.error(f"工具执行失败 {tool_call.name}: {e}")
            return {"error": str(e)}

    def _assistant_msg_with_tools(self, tool_calls: list[ToolCall]) -> dict:
        """构建含工具调用的 assistant 消息。"""
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ],
        }
