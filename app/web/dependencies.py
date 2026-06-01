"""
Web 层依赖注入。

管理全局单例（ChatEngine、LLMProvider 等）的创建和获取。
"""

import logging

from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.chat.engine import ChatEngine
from app.chat.providers.base import LLMConfig
from app.chat.providers.registry import get_provider
from app.chat.session import SessionManager
from app.config import settings

logger = logging.getLogger(__name__)

# Jinja2 模板
_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# 全局单例
_chat_engine: ChatEngine | None = None
_memory_engine = None  # MemoryEngine
_profile_manager = None  # UserProfileManager


def get_chat_engine() -> ChatEngine:
    """获取 ChatEngine 单例。"""
    global _chat_engine
    if _chat_engine is None:
        raise RuntimeError("ChatEngine 尚未初始化，请先调用 init_engines()")
    return _chat_engine


def get_memory_engine():
    """获取 MemoryEngine 单例。"""
    global _memory_engine
    return _memory_engine


def get_profile_manager():
    """获取 UserProfileManager 单例。"""
    global _profile_manager
    return _profile_manager


async def init_engines() -> None:
    """初始化所有引擎（在 FastAPI lifespan 中调用）。"""
    global _chat_engine, _memory_engine, _profile_manager

    logger.info("正在初始化引擎...")

    # 检查 API Key
    if not settings.deepseek_api_key:
        logger.warning(
            "⚠️  未设置 DEEPSEEK_API_KEY 环境变量！"
            "请在 .env 文件中配置 API Key。"
        )

    # 创建 LLM Provider
    config = LLMConfig(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    provider = get_provider("deepseek", config)

    # 创建 SessionManager
    session_mgr = SessionManager()

    # 创建 MemoryEngine
    from app.memory.engine import MemoryEngine
    from app.memory.profile import UserProfileManager

    _memory_engine = MemoryEngine()
    _profile_manager = UserProfileManager()
    _memory_engine._profile = _profile_manager

    # 创建 ChatEngine（注入记忆引擎）
    _chat_engine = ChatEngine(
        provider=provider,
        session_mgr=session_mgr,
        memory_engine=_memory_engine,
    )

    logger.info("引擎初始化完成 ✓")
async def shutdown_engines() -> None:
    """关闭所有引擎。"""
    global _chat_engine
    if _chat_engine and hasattr(_chat_engine.provider, "close"):
        await _chat_engine.provider.close()
    logger.info("引擎已关闭")
