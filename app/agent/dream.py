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

    SYSTEM_PROMPT = """你是 PersonalAgent 记忆整理系统（Dream Process）。

你定期运行，负责检查和维护用户的记忆库。

## 你的职责

### 1. 合并明显的重复
两条记忆讲的是同一件事 → 保留更完整的那条，删除另一条。
如果只是主题相近但内容不同（如"用户喜欢Python"和"用户常用FastAPI"），不要合并。

### 2. 修正事实错误
- 日期明显错误且能确定正确日期 → 更新
- 内容与另一条更高可信度的记忆矛盾 → 删掉错误的那条
- 不确定对错的，**不要动**，标注在输出中

### 3. 清理明确过期的状态
- state 类型中已经不再有效的（如"正在做X"但显然已完成）
- 其他类型不要以"可能过期"为由删除

## 操作约束

- **默认保留**：拿不准的一律不动。只处理你确定应该处理的。
- **宁缺毋滥**：一次 dream 删 0-2 条是正常的。删 5 条以上说明你做过头了。
- **不要写综合报告**：不要创建新文件来"总结"已有记忆。
- **不要改表述**：除非有明显错误，否则保留用户原始表述。

## 输出

返回 JSON：
{
  "status": "completed",
  "deleted": 0,
  "merged": 0,
  "updated": 0,
  "summary": "做了什么，没做什么"
}
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
                description="列出所有记忆的索引。先看有哪些记忆，再决定读哪些的详情。",
                parameters={
                    "type": "object",
                    "properties": {
                        "mem_type": {"type": "string", "description": "可选，按类型筛选"},
                    },
                },
                handler=lambda **kw: tool_handlers["read_all_memories"](**kw),
            ),
            Tool(
                name="read_memory_detail",
                description="读取单条记忆的完整内容（含 frontmatter 元数据）",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "记忆文件名（不含 .md）"},
                    },
                    "required": ["name"],
                },
                handler=lambda **kw: tool_handlers["read_memory_detail"](**kw),
            ),
            Tool(
                name="write_memory",
                description="创建新记忆或更新已有记忆。name 相同即为更新。",
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

        input_text = f"""## Dream 任务

当前日期: {today_str}（所有日期判断以此为基准）
共 {total} 条记忆。自上次 dream 以来有 {session_count} 个会话活动。

## 当前记忆清单

{chr(10).join(memory_summary)}

## 执行步骤

### 第一步：读取（1轮）
用 read_all_memories 获取概览。只对明显重复或可能有矛盾的记忆用 read_memory_detail 读详情。

### 第二步：处理（1轮）
只处理你确定需要处理的：
- **合并**：两条记忆讲同一件事 → 保留更完整的那条，删除另一条
- **修正**：日期明显错误且能确定正确值 → 更新
- **清理**：state 类型中明确过期的 → 删除

## 重要约束

1. **默认不动**：拿不准的一律跳过。一次 dream 删 0-2 条是正常的。
2. **不要创建新记忆**来"总结"已有记忆。
3. **不要改表述**，除非有明显事实错误。

完成后输出 JSON：{{"status": "completed", "deleted": N, "merged": N, "updated": N, "summary": "做了什么"}}"""

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
