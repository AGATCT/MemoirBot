"""
会话初始化 Agent。

在创建新聊天会话时，读取用户记忆和画像，生成上下文摘要
注入到 system prompt 中，让 LLM 从一开始就了解用户。

参考 coding-agent-main：系统 prompt 中的 auto memory 部分 + MEMORY.md 加载。
"""

import logging
from app.agent.base import SubAgent, SubAgentResult, Tool
from app.chat.providers.base import LLMProvider
from app.memory.engine import MemoryEngine

logger = logging.getLogger(__name__)


class SessionInitAgent(SubAgent):
    """会话初始化 Agent：为新会话构建用户上下文。

    不直接使用 tool-use（仅需要读取记忆），而是通过 MemoryEngine
    获取已有记忆，让 LLM 合成上下文摘要。
    """

    SYSTEM_PROMPT = """你是 PersonalAgent 上下文构建器。

你的任务是根据用户的记忆和画像，生成一段简洁的中文上下文摘要，
注入到新会话的系统提示中。

## 分析方法

阅读下面提供的用户信息，生成包含以下内容的摘要（2-3 段）：
1. 用户是谁（角色、背景、偏好）
2. 用户当前在做什么（活跃项目、关注事项、近期事件）
3. 与用户互动时应该注意什么（沟通风格、行为指引）

## 输出格式

返回严格 JSON：
{
  "context_summary": "2-3段中文摘要，每段不超过3句话",
  "key_points": ["要点1", "要点2", "要点3"],
  "greeting_suggestion": "建议的打招呼内容（可选）",
  "has_sufficient_context": true/false
}

如果提供的用户信息不足以构建有意义的上下文（比如记忆很少或全是reference类型），
设置 has_sufficient_context: false 并返回简短摘要。
"""

    def __init__(self, provider: LLMProvider, memory_engine: MemoryEngine):
        super().__init__(provider, self.SYSTEM_PROMPT, max_turns=1)
        self.memory_engine = memory_engine

    async def build_context(self) -> str:
        """构建会话上下文。

        Returns:
            上下文摘要字符串，可直接注入 system prompt。
            如果没有足够记忆，返回空字符串。
        """
        # 获取相关上下文
        context_text = await self.memory_engine.get_relevant_context(limit=15)
        manifest = await self.memory_engine.get_memory_manifest()

        if not context_text:
            logger.info("SessionInitAgent: 暂无记忆，跳过上下文构建")
            return ""

        # 获取用户画像（如果有）
        profile_text = ""
        if self.memory_engine._profile:
            try:
                profile = await self.memory_engine._profile.get_profile()
                if profile.summary:
                    profile_text = f"\n## 用户画像\n{profile.summary}"
                    if profile.current_focus:
                        profile_text += f"\n当前关注: {profile.current_focus}"
                    if profile.traits:
                        profile_text += f"\n特质: {', '.join(profile.traits)}"
            except Exception:
                pass

        input_text = f"""当前日期: {__import__('datetime').date.today().isoformat()}

请根据以下用户信息生成上下文摘要：

## 已存储的记忆
{context_text}

## 记忆索引
{manifest}
{profile_text}"""

        # 1. 先尝试 LLM 合成
        try:
            result = await self.run(input_text)

            if result.success and result.output:
                summary = result.output.get("context_summary", "")
                if result.output.get("has_sufficient_context", True) and summary:
                    logger.info(
                        f"SessionInitAgent: LLM 生成上下文摘要"
                        f"（{len(result.output.get('key_points', []))} 个关键点）"
                    )
                    return summary
        except Exception as e:
            logger.warning(f"SessionInitAgent LLM 调用失败: {e}")

        # 2. LLM 失败或上下文不足时，回退到原始记忆文本
        logger.info("SessionInitAgent: LLM 不可用，使用原始记忆作为回退上下文")
        return context_text
