"""
Dream Agent — 记忆维护的"梦境"过程。

参考 coding-agent-main autoDream.ts + consolidationPrompt.ts。

Dream Agent 在 24h 间隔 + 足够会话积累后运行：
1. Orient: 通读所有记忆
2. Assess: 评估每条记忆的质量
3. Clean: 删除低质量/重复/过时的记忆
4. Merge: 合并相似记忆
5. Update: 更新用户画像（精炼摘要，不重复记忆内容）
"""

import logging
from datetime import datetime, date

from app.agent.base import SubAgent, Tool
from app.chat.providers.base import LLMProvider
from app.memory.engine import MemoryEngine

logger = logging.getLogger(__name__)


class DreamAgent(SubAgent):
    """Dream Agent: 定期的记忆清理和合并。

    关键原则：Dream 应该让记忆库更精炼，而不是更臃肿。
    """

    SYSTEM_PROMPT = """你是记忆整理 Agent。定期对记忆库做一次回顾，让未来的会话能快速了解用户。

## 工作流程

### 1. 了解现状
用 read_all_memories 查看索引。对看起来可能重复、过时或有矛盾的文件用 read_memory_detail 读完整内容。目的是在修改前充分理解已有信息，避免重复或误删。

### 2. 合并和修正
- 两条记忆实质上讲同一件事 → 更新更完整的那条，删除另一条。主题相近但内容不同的不要合并。
- 明显的事实错误（如日期不合理的）且能确定正确值 → 更新。不确定的不要动。
- 明显过期的 state（如已完成的短期状态）→ 删除。
- 内容高度重复且一条已覆盖另一条的全部信息 → 删除重复的那条。

### 3. 整理索引
检查 MEMORY.md，确保：
- 指向的文件确实存在
- 已删除的文件从索引中移除
- 每个条目一行，描述简洁

## 原则

- 拿不准的不动。一次 dream 处理 0-3 条是正常的。
- 不要新建记忆来"总结"已有内容。在已有文件上改进。
- 保留用户的原始表述，不要自行改写。

## 输出

返回 JSON：{"status": "completed", "deleted": N, "merged": N, "updated": N, "summary": "简述"}
"""

    def __init__(
        self,
        provider: LLMProvider,
        memory_engine: MemoryEngine,
        profile_manager=None,
    ):
        from app.agent.tools import create_memory_tools

        self.memory_engine = memory_engine
        self.profile_manager = profile_manager

        tool_handlers = create_memory_tools(memory_engine.store, profile_manager)

        tools = [
            Tool(
                name="read_all_memories",
                description="列出所有记忆的索引",
                parameters={"type": "object", "properties": {}},
                handler=lambda **kw: tool_handlers["read_all_memories"](**kw),
            ),
            Tool(
                name="read_memory_detail",
                description="读取单条记忆的完整内容",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                handler=lambda **kw: tool_handlers["read_memory_detail"](**kw),
            ),
            Tool(
                name="write_memory",
                description="创建或更新记忆，name 相同即为更新。",
                parameters={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["user","feedback","reference","event","state"]},
                        "name": {"type": "string", "description": "文件名 slug，如 user-lives-in-shenzhen"},
                        "description": {"type": "string", "description": "一行摘要"},
                        "content": {"type": "string", "description": "记忆正文。feedback 类型必须含 **为什么:** 和 **如何应用:**。"},
                    },
                    "required": ["type", "name", "description", "content"],
                },
                handler=lambda **kw: tool_handlers["write_memory"](**kw),
            ),
            Tool(
                name="delete_memory",
                description="删除一条记忆。对应文件会被移除，MEMORY.md 索引同步更新。",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "记忆文件名（不含 .md）"},
                    },
                    "required": ["name"],
                },
                handler=lambda **kw: tool_handlers["delete_memory"](**kw),
            ),
            Tool(
                name="read_profile",
                description="读取用户画像（当前版本）",
                parameters={"type": "object", "properties": {}},
                handler=lambda **kw: tool_handlers["read_profile"](**kw),
            ),
        ]
        super().__init__(provider, self.SYSTEM_PROMPT, tools, max_turns=10)

    async def dream(self, session_count: int = 0) -> dict:
        """执行 Dream 流程。"""
        manifest = await self.memory_engine.get_memory_manifest()
        memories = await self.memory_engine.store.read_all_memories()
        total = len(memories)
        today_str = date.today().isoformat()

        # 构建每条记忆的简要评估清单
        memory_summary = []
        for m in memories:
            age = ""
            if m.created_at:
                try:
                    created = datetime.fromisoformat(m.created_at)
                    days = (datetime.now() - created).days
                    age = f"（{days}天前）"
                except Exception:
                    pass
            memory_summary.append(
                f"- [{m.type}] **{m.name}** — {m.description}{age}"
            )

        input_text = f"""当前日期: {today_str}
共 {total} 条记忆，上次整理以来有 {session_count} 个会话活跃。

## 当前记忆

{chr(10).join(memory_summary)}

## 步骤

1. 用 read_all_memories 获取索引，对需要细看的条目用 read_memory_detail
2. 合并重复、修正错误、清理过期状态
3. 完成后直接输出结果

一次 dream 通常处理 0-3 条。拿不准的不动。"""

        result = await self.run(input_text)

        if result.success:
            output = result.output or {}
            output["status"] = output.get("status", "completed")

            # 刷新用户画像（只做精炼摘要，不重复记忆）
            try:
                if self.profile_manager:
                    remaining = await self.memory_engine.store.read_all_memories()
                    await self.profile_manager.rebuild_from_memories(remaining)
                    output["profile_updated"] = True
            except Exception as e:
                logger.error(f"Dream: 画像更新失败: {e}")

            logger.info(
                f"Dream 完成: 删除={output.get('deleted', 0)}, "
                f"合并={output.get('merged', 0)}, "
                f"更新={output.get('updated', 0)}"
            )
            return output

        logger.error(f"Dream Agent 失败: {result.error}")
        return {"status": "error", "error": result.error}
