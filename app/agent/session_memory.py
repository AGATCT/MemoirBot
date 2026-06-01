"""
会话记忆 Agent（Session Memory）。

参考 coding-agent-main sessionMemory.ts。
定期用 forked agent 更新一份结构化的会话笔记。
笔记用于后续的上下文压缩——旧消息可被笔记替换，保持连贯的同时减少 token 消耗。
"""

import logging
from app.agent.base import SubAgent, Tool
from app.chat.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# 会话笔记模板
SESSION_MEMORY_TEMPLATE = """# 会话笔记

> 这是 AI 自动维护的会话笔记。定期更新，记录对话中的关键信息。

# 当前话题

<!-- 用户当前在聊什么 -->

# 重要信息

<!-- 对话中披露的用户信息、偏好、决策等 -->

# 进展

<!-- 完成了什么、得出了什么结论 -->

# 待办

<!-- 用户提到的待办事项 -->
"""


class SessionMemoryAgent(SubAgent):
    """会话笔记更新 Agent。

    接收当前笔记 + 最近的消息，用 tool-use 更新笔记文件。
    只允许 Edit/Write 笔记文件，不能动其他文件。
    """

    SYSTEM_PROMPT = """你是会话笔记维护助手。你的任务是更新一份结构化的会话笔记。

## 更新规则

1. **保留章节标题**（# 开头）——不要删除或重命名章节
2. **更新对应章节的内容**——把新消息中的关键信息写入合适的章节
3. **不要记录细节**——只记录值得在未来回顾的信息。临时讨论、一次性的代码细节不记录
4. **合并相同信息**——如果新信息和已有笔记讲的是同一件事，更新而不是追加
5. **使用简洁的列表**——用 `-` 列表，不要写大段文字
6. **总是更新「当前话题」**——这是最重要的章节

## 工具

使用 Write 工具覆写笔记文件。读取当前内容，规划修改，一次性写入。

## 输出

完成后输出 JSON: {"status": "updated", "sections_changed": ["当前话题", "重要信息"]}
"""

    def __init__(self, provider: LLMProvider):
        super().__init__(provider, self.SYSTEM_PROMPT, max_turns=3)

    async def update(
        self, current_notes: str, notes_path: str, recent_messages: str
    ) -> dict:
        """更新会话笔记。

        Args:
            current_notes: 当前笔记内容
            notes_path: 笔记文件路径（供 agent 写入）
            recent_messages: 最近的对话消息（格式化文本）

        Returns:
            更新结果
        """
        input_text = f"""## 当前笔记

{current_notes}

## 笔记文件路径

{notes_path}

## 最近消息

{recent_messages}

请更新笔记文件。先分析最近消息中有哪些值得记录的信息，然后用 Write 工具写入更新后的完整笔记。"""

        result = await self.run(input_text)

        if result.success:
            return result.output or {"status": "updated"}
        return {"status": "error", "error": result.error}
