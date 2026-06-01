"""
PersonalAgent — AI 个人助手系统。

FastAPI 应用入口，管理生命周期、挂载路由。
记忆系统（提取 + Dream 调度器）在 lifespan 中启动。
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.storage.paths import ensure_directories
from app.web.dependencies import (
    init_engines,
    shutdown_engines,
    get_memory_engine,
    get_profile_manager,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# 全局调度器引用
_dream_scheduler = None


# =============================================================================
# 应用生命周期
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global _dream_scheduler

    logger.info("🚀 PersonalAgent 启动中...")

    # 创建数据目录
    ensure_directories()
    logger.info("数据目录已就绪")

    # 初始化引擎（LLM、Chat、Memory）
    await init_engines()

    # 启动 DreamScheduler
    _dream_scheduler = await _start_dream_scheduler()

    yield

    # 停止 DreamScheduler
    if _dream_scheduler:
        await _dream_scheduler.stop()

    # 关闭引擎
    await shutdown_engines()
    logger.info("PersonalAgent 已关闭")


async def _start_dream_scheduler():
    """初始化并启动 DreamScheduler。"""
    from app.scheduler.dream_scheduler import init_dream_scheduler
    from app.agent.dream import DreamAgent
    from app.web.dependencies import get_chat_engine

    engine = get_chat_engine()
    memory_engine = get_memory_engine()

    if memory_engine is None:
        logger.warning("DreamScheduler 跳过 — 记忆引擎未初始化")
        return None

    dream_agent = DreamAgent(
        provider=engine.provider,
        memory_engine=memory_engine,
        profile_manager=get_profile_manager(),
    )

    scheduler = await init_dream_scheduler(
        dream_agent=dream_agent,
        memory_engine=memory_engine,
    )
    await scheduler.start()

    return scheduler


# =============================================================================
# 创建应用
# =============================================================================

app = FastAPI(
    title="PersonalAgent",
    description="AI 个人助手 — 聊天、日记、记忆系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 静态文件
static_dir = Path(__file__).parent / "web" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 注册聊天路由
from app.web.routes.chat import router as chat_router
from app.web.routes.chat import register_page_routes as register_chat_pages

app.include_router(chat_router)
register_chat_pages(app)

# 注册日记路由
from app.web.routes.diary import router as diary_router
from app.web.routes.diary import register_page_routes as register_diary_pages

app.include_router(diary_router)
register_diary_pages(app)

# 注册记忆路由
from app.web.routes.memory import router as memory_router
from app.web.routes.memory import register_page_routes as register_memory_pages

app.include_router(memory_router)
register_memory_pages(app)

# 注册系统路由
from app.web.routes.system import router as system_router
from app.web.routes.system import register_page_routes as register_system_pages

app.include_router(system_router)
register_system_pages(app)


# =============================================================================
# 健康检查
# =============================================================================

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
