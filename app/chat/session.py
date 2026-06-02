"""
会话管理器。

负责聊天会话的创建、读取、更新、删除，消息持久化，
以及会话笔记的维护和上下文压缩。

会话数据存储在 data/chats/{session_id}/ 目录中：
  - metadata.json:       会话元数据
  - messages.jsonl:      消息日志（追加写入）
  - session_memory.md:   会话笔记（定期更新，用于上下文压缩）
"""

import logging
import uuid
from datetime import datetime, date
from pathlib import Path

from app.chat.schemas import ChatMessage, SessionMetadata
from app.storage import file_store
from app.storage.paths import get_chat_session_dir
from app.agent.session_memory import SESSION_MEMORY_TEMPLATE

logger = logging.getLogger(__name__)

# 压缩阈值：超过此估算 token 数后触发压缩
COMPACTION_TOKEN_THRESHOLD = 16_000
# 压缩后保留的最近消息数
KEEP_RECENT_MESSAGES = 10
# 会话笔记更新触发间隔（轮数，每轮 = user + assistant 各一条）
SESSION_MEMORY_UPDATE_INTERVAL = 4


class SessionManager:
    """会话管理器。"""

    # ------------------------------------------------------------------
    # 会话 CRUD
    # ------------------------------------------------------------------

    async def create(self, title: str | None = None) -> SessionMetadata:
        """创建新会话。"""
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        metadata = SessionMetadata(
            session_id=session_id,
            title=title or "新对话",
            created_at=now,
            updated_at=now,
        )

        session_dir = get_chat_session_dir(session_id)
        await file_store.write_json(
            session_dir / "metadata.json", metadata.model_dump()
        )
        await file_store.write_text(session_dir / "messages.jsonl", "")
        # 创建空的会话笔记
        await file_store.write_text(session_dir / "session_memory.md", SESSION_MEMORY_TEMPLATE)

        logger.info(f"创建会话: {session_id}")
        return metadata

    async def get_metadata(self, session_id: str) -> SessionMetadata | None:
        data = await file_store.read_json(
            get_chat_session_dir(session_id) / "metadata.json"
        )
        if data is None:
            return None
        return SessionMetadata(**data)

    async def update_metadata(
        self, session_id: str, **kwargs
    ) -> SessionMetadata | None:
        meta = await self.get_metadata(session_id)
        if meta is None:
            return None

        for key, value in kwargs.items():
            if hasattr(meta, key):
                setattr(meta, key, value)

        meta.updated_at = datetime.now().isoformat()
        await file_store.write_json(
            get_chat_session_dir(session_id) / "metadata.json", meta.model_dump()
        )
        return meta

    async def list_sessions(self) -> list[SessionMetadata]:
        from app.storage.paths import get_chats_dir

        sessions = []
        chat_dirs = await file_store.list_files(get_chats_dir(), pattern="sess_*")
        for d in chat_dirs:
            if not d.is_dir():
                continue
            meta = await file_store.read_json(d / "metadata.json")
            if meta:
                try:
                    sessions.append(SessionMetadata(**meta))
                except Exception:
                    continue

        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    async def delete(self, session_id: str) -> bool:
        import shutil

        session_dir = get_chat_session_dir(session_id)

        def _delete():
            if session_dir.exists():
                shutil.rmtree(session_dir)
                return True
            return False

        import asyncio
        return await asyncio.to_thread(_delete)

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    async def add_message(
        self, session_id: str, role: str, content: str, reasoning_content: str | None = None
    ) -> ChatMessage:
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        msg = ChatMessage(
            msg_id=msg_id,
            role=role,
            content=content,
            reasoning_content=reasoning_content,
            timestamp=datetime.now().isoformat(),
        )

        session_dir = get_chat_session_dir(session_id)
        await file_store.append_jsonl(session_dir / "messages.jsonl", msg.model_dump())

        meta = await self.get_metadata(session_id)
        if meta:
            await self.update_metadata(
                session_id,
                message_count=meta.message_count + 1,
            )

        return msg

    async def get_messages(
        self, session_id: str, limit: int = 0, offset: int = 0
    ) -> list[ChatMessage]:
        session_dir = get_chat_session_dir(session_id)
        records = await file_store.read_jsonl_range(
            session_dir / "messages.jsonl", start=offset, limit=limit
        )
        return [ChatMessage(**r) for r in records]

    async def get_messages_since_offset(
        self, session_id: str
    ) -> tuple[list[ChatMessage], int]:
        meta = await self.get_metadata(session_id)
        if meta is None:
            return [], 0

        records = await file_store.read_jsonl_range(
            get_chat_session_dir(session_id) / "messages.jsonl",
            start=meta.extraction_offset,
        )
        messages = [ChatMessage(**r) for r in records]
        new_offset = meta.message_count
        return messages, new_offset

    # ------------------------------------------------------------------
    # 构建 LLM 消息（含会话笔记压缩）
    # ------------------------------------------------------------------

    async def get_messages_for_llm(
        self, session_id: str, max_messages: int = 50
    ) -> list[dict]:
        """构建发给 LLM 的消息列表。

        如果消息过多（token 估算超过阈值），用会话笔记替换旧消息。
        保持前缀稳定以利用 API 前缀缓存。
        """
        meta = await self.get_metadata(session_id)
        messages: list[dict] = []

        # 系统提示词（前缀缓存的核心：这段话永远不变）
        system_prompt = await self._build_system_prompt(meta)
        messages.append({"role": "system", "content": system_prompt})

        # 获取全部消息
        raw_messages = await self.get_messages(session_id)
        total_tokens = self._estimate_total_tokens(system_prompt, raw_messages)

        if total_tokens < COMPACTION_TOKEN_THRESHOLD or len(raw_messages) <= KEEP_RECENT_MESSAGES + 5:
            # 未超阈值：全部发送（前缀稳定，缓存友好）
            for msg in raw_messages:
                messages.append({"role": msg.role, "content": msg.content})
        else:
            # 超阈值：用会话笔记替换旧消息，仅保留最近 N 条
            memory_content = await self._read_session_memory(session_id)
            split_idx = len(raw_messages) - KEEP_RECENT_MESSAGES

            if memory_content and memory_content.strip() != SESSION_MEMORY_TEMPLATE.strip():
                # 注入压缩摘要
                summary = (
                    "## 之前的对话摘要\n\n"
                    f"以下是之前 {split_idx} 条消息的摘要，由会话笔记自动维护：\n\n"
                    f"{memory_content}\n\n"
                    "---\n"
                    "## 最近的对话\n"
                )
                messages.append({"role": "user", "content": summary})

                # 记录压缩点（下次从这之后的消息保持前缀稳定）
                await self.update_metadata(
                    session_id,
                    compacted_at=split_idx,
                    session_memory_message_count=split_idx,
                )

                logger.info(
                    f"会话 {session_id}: 压缩 {split_idx} 条消息 → 笔记 + {KEEP_RECENT_MESSAGES} 条"
                    f"（{total_tokens} → ~{self._estimate_total_tokens(system_prompt, raw_messages[split_idx:]) + self._estimate_tokens(memory_content)} tokens）"
                )
            else:
                # 没有笔记，只能截断（前缀会变，缓存失效）
                logger.info(f"会话 {session_id}: 无笔记，截断至最近 {max_messages} 条")
                raw_messages = raw_messages[-max_messages:]

            # 发送最近消息
            recent = raw_messages[split_idx:] if memory_content else raw_messages
            for msg in recent:
                messages.append({"role": msg.role, "content": msg.content})

        return messages

    # ------------------------------------------------------------------
    # 会话笔记
    # ------------------------------------------------------------------

    async def get_session_memory_path(self, session_id: str) -> str:
        return str(get_chat_session_dir(session_id) / "session_memory.md")

    async def read_session_memory(self, session_id: str) -> str:
        """读取会话笔记。"""
        path = get_chat_session_dir(session_id) / "session_memory.md"
        try:
            return await file_store.read_text(path) or ""
        except Exception:
            return ""

    async def should_update_session_memory(self, session_id: str) -> bool:
        """检查是否应该更新会话笔记（按轮计数）。"""
        meta = await self.get_metadata(session_id)
        if meta is None:
            return False
        last_update = getattr(meta, "session_memory_message_count", 0) or 0
        new_turns = (meta.message_count - last_update) // 2
        return new_turns >= SESSION_MEMORY_UPDATE_INTERVAL

    async def mark_session_memory_updated(self, session_id: str) -> None:
        """标记会话笔记已更新（更新消息计数锚点）。"""
        meta = await self.get_metadata(session_id)
        if meta:
            await self.update_metadata(
                session_id,
                session_memory_message_count=meta.message_count,
            )

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _read_session_memory(self, session_id: str) -> str:
        return await self.read_session_memory(session_id)

    async def _build_system_prompt(self, meta: SessionMetadata | None) -> str:
        """构建系统提示词。保持稳定以利用 API 前缀缓存。

        直接注入 MEMORY.md 内容，coding-agent-main 模式：
        不需要额外的 LLM 调用合成摘要。
        """
        today = date.today().isoformat()
        prompt = (
            f"当前日期: {today}\n\n"
            "你是一个友好的 AI 个人助手。你了解用户的背景和偏好，"
            "能够帮助用户记录日记、管理记忆、提供建议。\n"
            "请用中文与用户交流。\n"
            "重要: 在记录事件或推测时间时，必须以当前日期为基准进行计算。"
            "避免使用模糊的'推测时间'表述，不确定时间应与用户确认。\n"
        )

        # 直接注入 MEMORY.md 内容（coding-agent-main 方式）
        memory_section = await self._build_memory_section()
        if memory_section:
            prompt += memory_section

        return prompt

    async def _build_memory_section(self) -> str:
        """构建记忆相关的 system prompt 段落。"""
        from app.storage.paths import get_memory_index_path
        from app.storage import file_store as fs
        from app.memory.types import (
            MEMORY_TYPE_DEFINITIONS, WHAT_NOT_TO_SAVE, WHEN_TO_ACCESS,
            MEMORY_FRONTMATTER_FORMAT,
        )

        index_path = get_memory_index_path()
        if not index_path.exists():
            return ""

        content = await fs.read_text(index_path)
        if not content or not content.strip():
            return ""

        # 截断到 200 行 / 25KB（对齐 coding-agent-main）
        lines = content.strip().split("\n")
        if len(lines) > 200:
            lines = lines[:200]
            content = "\n".join(lines)
        if len(content.encode("utf-8")) > 25_000:
            content = content.encode("utf-8")[:25_000].decode("utf-8", errors="ignore")

        # 类型速查
        type_quick = []
        for key, info in MEMORY_TYPE_DEFINITIONS.items():
            type_quick.append(f"- **{key}**（{info['name']}）: {info['when_to_save']}")

        section = f"""

# 记忆系统

你有一个持久的文件记忆系统。MEMORY.md 是索引，每个条目一行指向具体的记忆文件。

{WHEN_TO_ACCESS}

## 记忆类型速查

{chr(10).join(type_quick)}

## 保存格式

{MEMORY_FRONTMATTER_FORMAT}

{WHAT_NOT_TO_SAVE}

## MEMORY.md

{content}

## 搜索过往上下文

当需要回忆用户之前提到的具体信息时：
- 用 search_memories 在记忆文件中搜索关键词
- 用 read_memory 读取具体记忆文件的完整内容
- MEMORY.md 中的 description 是一行摘要，正文可能有更多细节
"""
        return section

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, int(len(text) * 0.6))

    @classmethod
    def _estimate_total_tokens(cls, system_prompt: str, messages: list[ChatMessage]) -> int:
        total = cls._estimate_tokens(system_prompt) + 4
        for msg in messages:
            total += cls._estimate_tokens(msg.content) + 4
        return total

    # ------------------------------------------------------------------
    # 提取状态管理
    # ------------------------------------------------------------------

    async def get_extraction_offset(self, session_id: str) -> int:
        meta = await self.get_metadata(session_id)
        return meta.extraction_offset if meta else 0

    async def update_extraction_offset(self, session_id: str, offset: int) -> None:
        await self.update_metadata(session_id, extraction_offset=offset)

    async def should_extract(self, session_id: str, interval: int = 5) -> bool:
        """检查是否应触发记忆提取（按轮计数，每轮 = user + assistant）。"""
        meta = await self.get_metadata(session_id)
        if meta is None:
            return False
        new_turns = (meta.message_count - meta.extraction_offset) // 2
        return new_turns >= interval
