"""
聊天引擎。

负责编排整个聊天流程：消息发送、上下文注入、记忆提取触发。
记忆系统（SessionInitAgent + ExtractionAgent）已完整接入。
"""

import asyncio
import logging
from typing import AsyncGenerator

from app.chat.providers.base import LLMProvider
from app.chat.session import SessionManager
from app.config import settings

logger = logging.getLogger(__name__)


class ChatEngine:
    """聊天引擎：编排聊天流程，接入记忆系统。"""

    def __init__(
        self,
        provider: LLMProvider,
        session_mgr: SessionManager,
        memory_engine=None,
        extraction_agent_cls=None,
    ):
        self.provider = provider
        self.session_mgr = session_mgr
        self.memory_engine = memory_engine  # MemoryEngine
        self.extraction_agent_cls = extraction_agent_cls  # ExtractionAgent class（延迟初始化）

        # 提取状态跟踪
        self._extraction_in_progress = False
        self._pending_extraction_session: str | None = None

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    async def create_session(self, title: str | None = None) -> str:
        """创建新会话。

        记忆通过 MEMORY.md 直接注入 system prompt，无需额外 LLM 调用。
        """
        meta = await self.session_mgr.create(title)
        logger.info(f"ChatEngine: 创建会话 {meta.session_id}")
        return meta.session_id

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    async def send_message(
        self, session_id: str, content: str
    ) -> AsyncGenerator[dict, None]:
        """处理用户消息并流式返回 AI 响应。"""
        # 1. 保存用户消息
        await self.session_mgr.add_message(session_id, "user", content)

        # 自动命名：首条消息截取前 30 字作为标题
        meta = await self.session_mgr.get_metadata(session_id)
        if meta and meta.message_count == 1 and meta.title == "新对话":
            title = content.replace("\n", " ").strip()[:30]
            if len(content) > 30:
                title += "…"
            await self.session_mgr.update_metadata(session_id, title=title)

        # 2. 构建 LLM 消息 + 记忆工具
        messages = await self.session_mgr.get_messages_for_llm(session_id)
        tools = self._build_chat_tools()

        # 3. tool-use 循环（coding-agent-main 模式：agent 自己决定是否查记忆）
        full_response = ""
        max_tool_rounds = 3
        recall_act_id: str | None = None
        recall_items: list[str] = []
        try:
            for _ in range(max_tool_rounds):
                resp = await self.provider.chat_with_tools(messages, tools)
                tool_calls = resp.get("tool_calls") or []

                if tool_calls:
                    # 记录工具调用
                    if recall_act_id is None:
                        from app.agent.activity_log import get_activity_log
                        recall_act_id = get_activity_log().start(
                            "recall", "记忆召回", session_id=session_id,
                        )
                    messages.append(self._msg_assistant_tool_calls(tool_calls))
                    for tc in tool_calls:
                        result = await self._execute_chat_tool(tc, session_id)
                        recall_items.append(f"{tc.name}: {tc.arguments.get('query') or tc.arguments.get('name', '?')}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
                    continue

                # 无工具调用 → 最终文本响应
                content = resp.get("content") or ""
                full_response = content
                yield {"type": "token", "content": content}
                break

            if not full_response:
                full_response = "抱歉，回复生成失败。"
                yield {"type": "token", "content": full_response}

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            full_response = f"抱歉，回复生成失败：{e}"
            yield {"type": "token", "content": full_response}

        # 4. 保存 AI 响应
        assistant_msg = await self.session_mgr.add_message(
            session_id, "assistant", full_response
        )
        yield {"type": "done", "msg_id": assistant_msg.msg_id}

        # 如果本轮有记忆召回，记录到活动面板
        if recall_act_id and recall_items:
            from app.agent.activity_log import get_activity_log
            get_activity_log().finish(recall_act_id, summary=f"查询 {len(recall_items)} 次", items=recall_items)

        # 5. 检查是否需要记忆提取（后台不阻塞）
        if await self.session_mgr.should_extract(
            session_id, settings.extraction_interval
        ):
            yield {
                "type": "extraction",
                "status": "started",
                "message": "正在后台提取记忆...",
            }
            asyncio.create_task(self._trigger_extraction(session_id))

        # 6. 检查是否需要更新会话笔记（后台不阻塞）
        if await self.session_mgr.should_update_session_memory(session_id):
            asyncio.create_task(self._update_session_memory(session_id))

    # ------------------------------------------------------------------
    # 记忆提取
    # ------------------------------------------------------------------

    async def _trigger_extraction(self, session_id: str) -> None:
        """触发后台记忆提取，带 coalescing 逻辑。

        参考 coding-agent-main extractMemories.ts:
        - 如果提取正在运行 → 暂存上下文（coalescing）
        - 提取完成后 → 追跑一次（如果有暂存上下文）
        """
        if self._extraction_in_progress:
            logger.debug(f"[extraction] 提取进行中，暂存会话 {session_id}")
            self._pending_extraction_session = session_id
            return

        self._extraction_in_progress = True
        try:
            await self._do_extraction(session_id)
        finally:
            self._extraction_in_progress = False

            # 处理追跑请求（coalescing trailing run）
            pending = self._pending_extraction_session
            self._pending_extraction_session = None
            if pending and pending != session_id:
                logger.info(f"[extraction] 执行追跑提取: {pending}")
                asyncio.create_task(self._trigger_extraction(pending))

    async def _do_extraction(self, session_id: str) -> None:
        """实际执行记忆提取。"""
        if not self.memory_engine:
            return

        try:
            # 获取自上次提取后的新消息
            messages, new_offset = await self.session_mgr.get_messages_since_offset(
                session_id
            )
            if not messages:
                return

            logger.info(
                f"[extraction] 开始提取会话 {session_id}（{len(messages)} 条新消息）"
            )

            # 快照：提取前已有的记忆（失败不影响提取本身）
            from app.agent.extraction import ExtractionAgent
            from app.agent.activity_log import get_activity_log

            old_names: set[str] = set()
            try:
                old_headers = await self.memory_engine.store.list_memories()
                old_names = {h.filename for h in old_headers}
            except Exception as e:
                logger.warning(f"[extraction] 快照失败: {e}")

            act_id = get_activity_log().start(
                "extraction", "记忆提取", session_id=session_id,
                detail=f"处理 {len(messages)} 条新消息",
            )

            # 获取完整聊天上下文作为前缀（复用 API 缓存）
            chat_context = await self.session_mgr.get_messages_for_llm(session_id)

            agent = ExtractionAgent(self.provider, self.memory_engine)
            result = await agent.extract_with_prefix(chat_context, session_id)

            # 更新提取偏移量
            await self.session_mgr.update_extraction_offset(session_id, new_offset)

            # 对比找出新增/更新的记忆
            changed: set[str] = set()
            try:
                new_headers = await self.memory_engine.store.list_memories()
                new_names = {h.filename for h in new_headers}
                changed = new_names - old_names
            except Exception as e:
                logger.warning(f"[extraction] 对比失败: {e}")

            if changed:
                items = []
                for h in new_headers:
                    if h.filename in changed:
                        items.append(f"[{h.type}] {h.description}")
                get_activity_log().finish(act_id, summary=f"保存 {len(changed)} 条记忆", items=items)
                logger.info(f"[extraction] 完成：保存了 {len(changed)} 条记忆")
            else:
                get_activity_log().finish(act_id, summary="无新记忆")
                logger.info(f"[extraction] 完成：本轮无新记忆")

        except Exception as e:
            logger.error(f"[extraction] 提取失败: {e}", exc_info=True)

    async def _update_session_memory(self, session_id: str) -> None:
        """后台更新会话笔记。"""
        from app.agent.activity_log import get_activity_log

        act_id = get_activity_log().start(
            "session_memory", "会话笔记更新", session_id=session_id,
        )
        try:
            all_messages = await self.session_mgr.get_messages(session_id)
            last_update = getattr(
                await self.session_mgr.get_metadata(session_id),
                "session_memory_message_count", 0
            ) or 0
            new_messages = all_messages[last_update:]

            if not new_messages:
                get_activity_log().finish(act_id, summary="无新消息")
                return

            recent_text = "\n".join(
                f"**{m.role}**: {m.content[:300]}" for m in new_messages[-16:]
            )
            current_notes = await self.session_mgr.read_session_memory(session_id)
            notes_path = await self.session_mgr.get_session_memory_path(session_id)

            from app.agent.session_memory import SessionMemoryAgent

            agent = SessionMemoryAgent(self.provider)
            result = await agent.update(current_notes, notes_path, recent_text)

            if result.get("status") != "error":
                await self.session_mgr.mark_session_memory_updated(session_id)
                sections = result.get("sections_changed", [])
                get_activity_log().finish(
                    act_id,
                    summary=f"更新了 {len(sections)} 个章节" if sections else "已更新",
                )
            else:
                get_activity_log().finish(act_id, status="failed", summary=result.get("error", "")[:80])

        except Exception as e:
            get_activity_log().finish(act_id, status="failed", summary=str(e)[:80])
            logger.error(f"[session_memory] 更新异常: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # 聊天工具（记忆搜索 / 读取）
    # ------------------------------------------------------------------

    @staticmethod
    def get_unified_tools() -> list[dict]:
        """统一工具集——聊天和提取使用完全相同的 tools，保证 API 前缀缓存命中。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_memories",
                    "description": "在记忆文件中搜索关键词，返回匹配行。",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_memory",
                    "description": "读取指定记忆文件完整内容。",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_all_memories",
                    "description": "列出所有已有记忆的索引。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_memory",
                    "description": "创建或更新一条记忆。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["user","feedback","reference","event","state"]},
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["type", "name", "description", "content"],
                    },
                },
            },
        ]

    def _build_chat_tools(self) -> list[dict]:
        return self.get_unified_tools()

    async def _execute_chat_tool(self, tool_call, session_id: str) -> str:
        """执行聊天工具调用。"""
        import json
        name = tool_call.name
        args = tool_call.arguments

        if name == "search_memories":
            query = args.get("query", "")
            return await self._search_memories(query)
        elif name == "read_memory":
            mem_name = args.get("name", "")
            return await self._read_memory_content(mem_name)
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    async def _search_memories(self, query: str) -> str:
        """搜索记忆文件。"""
        import json
        from pathlib import Path
        from app.storage.paths import get_memories_dir

        mem_dir = get_memories_dir()
        results = []
        for f in mem_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            try:
                content = f.read_text(encoding="utf-8")
                matches = []
                for i, line in enumerate(content.split("\n"), 1):
                    if query.lower() in line.lower():
                        matches.append(f"  L{i}: {line.strip()[:120]}")
                if matches:
                    results.append(f"### {f.stem}\n{chr(10).join(matches[:5])}")
            except Exception:
                pass

        if not results:
            return f"未找到与 '{query}' 相关的记忆。"
        return "\n\n".join(results[:5])

    async def _read_memory_content(self, name: str) -> str:
        """读取单条记忆的完整内容。"""
        import json
        from app.storage.paths import get_memories_dir

        filepath = get_memories_dir() / f"{name}.md"
        try:
            content = filepath.read_text(encoding="utf-8")
            return content
        except FileNotFoundError:
            return json.dumps({"error": f"记忆文件不存在: {name}.md"}, ensure_ascii=False)

    @staticmethod
    def _msg_assistant_tool_calls(tool_calls) -> dict:
        """构建含工具调用的 assistant 消息。"""
        import json
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
