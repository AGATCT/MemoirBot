"""
记忆提取 Agent。

从聊天对话中提取结构化记忆（Event / Fact / State）。
参考 coding-agent-main extractMemories.ts + prompts.ts。

核心设计：
- 每 N 轮对话触发一次（由 ChatEngine 控制）
- 在后台运行，不阻塞用户
- 接收会话中自上次提取后的新消息
- 调用 LLM 提取记忆 → 存储 → 更新 MEMORY.md 索引
- 具有 coalescing 逻辑（提取进行中时合并后续请求）
"""

import logging
from datetime import datetime

from app.agent.base import SubAgent, Tool
from app.chat.providers.base import LLMProvider
from app.memory.engine import MemoryEngine
from app.memory.schemas import Memory
from app.memory.types import (
    MEMORY_TYPE_DEFINITIONS,
    WHAT_NOT_TO_SAVE,
    INDEX_UPDATE_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)


class ExtractionAgent(SubAgent):
    """从对话中提取记忆的子 Agent。

    使用 tool-use 模式：
    - 读取现有记忆（避免重复）
    - 提取新记忆并写入
    - 更新 MEMORY.md 索引
    """

    SYSTEM_PROMPT = """你是 PersonalAgent 记忆提取器。

你的任务是从最近的对话中提取值得持久保存的结构化记忆。

## 关注范围

只关注以下类型的信息（不是代码、不是临时讨论）：

### 用户信息 (user)
用户角色、背景、偏好、知识水平。了解用户是谁，以便未来更好地协助。

### 反馈指引 (feedback)
用户给出的行为指引。修正（"不要这样做"）和确认（"对就这样做"）都要记录。
如果只保存修正会越来越保守——确认也是重要信号。
格式：先写规则，然后 **为什么:** 和 **如何应用:**。

### 项目上下文 (project)
项目中正在进行的任务、目标、约束。始终将相对日期转换为绝对日期。

### 事件 (event)
过去发生的具体事情。包含日期、参与者、结果。

### 状态 (state)
用户当前的状况、进行中的事项、短期目标。状态会随时间过期。

## 什么不要提取
- 代码模式、架构、文件路径
- Git 历史、debug 方法
- 临时讨论、一次性的工作细节
- 已在 MEMORY.md 中记录的内容

## 提取原则
- 每条记忆一句话，清晰具体
- 置信度低于 0.5 的不保存
- 重要度评估：这条记忆在 1 个月后还有价值吗？（0-1）
- 优先更新已有记忆而不是创建重复

## 输出格式

每轮操作：
1. 先 read_all_memories 看看已有记忆（避免创建重复）
2. 对有价值的信息，用 write_memory 保存
3. 如果没有值得保存的内容，直接返回：{"status": "nothing_to_save"}

最终返回 JSON：
{
  "status": "completed",
  "extractions_count": 2,
  "summary": "从对话中提取了什么"
}
"""

    def __init__(self, provider: LLMProvider, memory_engine: MemoryEngine):
        from app.agent.tools import create_memory_tools

        self.memory_engine = memory_engine

        # 使用统一工具集 — 与聊天 agent 完全相同的 tools，保证 API 缓存命中
        from app.chat.engine import ChatEngine
        unified = ChatEngine.get_unified_tools()
        tool_handlers = create_memory_tools(memory_engine.store)

        # handler 映射：工具名 → 处理器
        handler_map = {
            "search_memories": lambda **kw: {"result": "提取模式下请用 read_all_memories"},
            "read_memory": lambda **kw: tool_handlers["read_memory_detail"](**kw),
            "read_all_memories": lambda **kw: tool_handlers["read_all_memories"](**kw),
            "write_memory": lambda **kw: tool_handlers["write_memory"](**kw),
        }

        tools = []
        for td in unified:
            name = td["function"]["name"]
            tools.append(Tool(
                name=name,
                description=td["function"]["description"],
                parameters=td["function"]["parameters"],
                handler=handler_map[name],
            ))
        super().__init__(provider, self.SYSTEM_PROMPT, tools, max_turns=5)

    async def extract_with_prefix(
        self, chat_messages: list[dict], session_id: str
    ) -> dict:
        """从对话中提取记忆，复用聊天前缀以命中 API 缓存。

        chat_messages 是聊天的完整消息列表（含 system prompt + 历史消息）。
        提取指令追加在末尾，不改变前缀。
        """
        if not chat_messages:
            return {"status": "skipped", "reason": "no messages"}

        manifest = await self.memory_engine.get_memory_manifest()
        today = datetime.now().strftime("%Y-%m-%d")

        type_defs = []
        for key, info in MEMORY_TYPE_DEFINITIONS.items():
            type_defs.append(f"- **{key}** ({info['name']}): {info['description']}")

        # 提取指令追加在聊天前缀后面（coding-agent-main 模式：一条 user message）
        input_text = f"""你是记忆提取子 Agent。分析以上对话中**用户的消息**，提取值得持久保存的新信息。

**注意**：

- 只提取用户本轮直接陈述的新事实。assistant 回复中引用的已有记忆不是新信息。
- 忠实于用户原意，不要替用户推理或添加评价。
- 一条记忆一件事。

当前日期: {today}。所有事件记忆必须以当前日期为基准计算。不确定的时间不要推测，直接标注"时间未明确"。

{chr(10).join(type_defs)}

{WHAT_NOT_TO_SAVE}

{INDEX_UPDATE_INSTRUCTIONS}

## 已有记忆
{manifest}

## 操作
- 先 read_all_memories 检查已有记忆，避免创建重复
- 只提取用户直接陈述的新信息，忽略 assistant 回复中的推测和已有记忆引用
- 对有价值的信息用 write_memory 保存（同名文件会更新）
- 如果没有值得保存的内容，直接返回: {{"status": "nothing_to_save"}}"""

        result = await self.run_with_prefix(chat_messages, input_text)

        if result.success:
            if result.output:
                return result.output
            return {"status": "completed", "text": result.text}

        logger.error(f"提取 Agent 失败: {result.error}")
        return {"status": "error", "error": result.error}

    async def extract(
        self, messages: list[dict], session_id: str
    ) -> dict:
        """从消息列表提取记忆。

        Args:
            messages: 自上次提取后的新消息列表
            session_id: 当前会话 ID

        Returns:
            提取结果摘要
        """
        if not messages:
            return {"status": "skipped", "reason": "no new messages"}

        # 构建输入：包含记忆类型定义 + 新消息
        conversation_text = self._format_messages(messages)
        manifest = await self.memory_engine.get_memory_manifest()
        today = datetime.now().strftime("%Y-%m-%d")

        type_defs = []
        for key, info in MEMORY_TYPE_DEFINITIONS.items():
            type_defs.append(f"- **{key}** ({info['name']}): {info['description']}")

        input_text = f"""## 重要：当前日期

今天是 {today}。所有事件记忆必须以此为基准计算日期。
永远不要推测时间 — 如果用户没有明确说明事件发生的日期，请标记置信度为 0.5 或在 content 中标注"日期未明确"。

## 记忆类型参考

{chr(10).join(type_defs)}

{WHAT_NOT_TO_SAVE}

## 已有记忆
{manifest}

## 最近对话（{len(messages)} 条消息）

{conversation_text}

请从上述对话中提取值得保存的记忆。先查已有记忆避免重复，再用 write_memory 保存。"""

        result = await self.run(input_text)

        if result.success:
            if result.output:
                return result.output
            return {"status": "completed", "text": result.text}

        logger.error(f"提取 Agent 失败: {result.error}")
        return {"status": "error", "error": result.error}

    def _format_messages(self, messages: list[dict]) -> str:
        """格式化消息列表为纯文本。"""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:500]  # 截断长消息
            lines.append(f"**{role}**: {content}")
            lines.append("")
        return "\n".join(lines)
