"""
系统路由。

提供系统状态、设置管理、手动 Dream 触发等 API。
"""

import logging

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


def get_dream_scheduler():
    """延迟获取 DreamScheduler。"""
    from app.scheduler.dream_scheduler import get_dream_scheduler as _get
    return _get()


def get_memory_engine():
    from app.web.dependencies import get_memory_engine as _get
    return _get()


def register_page_routes(app):
    """注册系统页面路由。"""

    @app.get("/settings")
    async def settings_page(request: Request):
        from app.web.dependencies import templates
        return templates.TemplateResponse("settings.html", {"request": request})


# =============================================================================
# 系统状态
# =============================================================================


@router.get("/api/system/status")
async def system_status():
    """获取系统状态概览。"""
    scheduler = get_dream_scheduler()
    engine = get_memory_engine()

    memory_count = 0
    if engine:
        memory_count = await engine.store.memory_count()

    dream_status = {
        "is_running": scheduler.is_running() if scheduler else False,
        "scheduler_active": scheduler is not None and scheduler._task is not None,
    }

    # 读取 dream 状态
    from app.storage.paths import get_dream_state_path
    from app.storage import file_store
    dream_state = await file_store.read_json(get_dream_state_path()) or {}

    return {
        "status": "ok",
        "version": "0.1.0",
        "memory_count": memory_count,
        "dream": {
            **dream_status,
            "last_dream_run": dream_state.get("last_dream_run", "从未运行"),
            "last_dream_result": dream_state.get("last_dream_result", ""),
        },
    }


@router.post("/api/system/dream/trigger")
async def trigger_dream():
    """手动触发 Dream 过程。"""
    scheduler = get_dream_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=503, detail="DreamScheduler 未初始化")

    result = await scheduler.trigger_manual()
    return result


@router.get("/api/system/agent-activity")
async def get_agent_activity(limit: int = 20):
    """获取最近的 Agent 活动记录。"""
    from app.agent.activity_log import get_activity_log
    log = get_activity_log()
    return {
        "activities": log.get_recent(limit),
        "running_count": log.running_count(),
    }


# =============================================================================
# 设置
# =============================================================================


@router.get("/api/settings")
async def get_settings():
    """获取当前设置。"""
    from app.config import settings as app_settings
    from app.storage.paths import get_settings_path
    from app.storage import file_store

    # 合并默认设置和用户自定义设置
    user_settings = await file_store.read_json(get_settings_path()) or {}

    return {
        "llm": {
            "model": user_settings.get("llm_model", app_settings.llm_model),
            "temperature": user_settings.get("llm_temperature", app_settings.llm_temperature),
            "max_tokens": user_settings.get("llm_max_tokens", app_settings.llm_max_tokens),
            "provider": user_settings.get("llm_provider", "deepseek"),
        },
        "memory": {
            "extraction_interval": user_settings.get(
                "extraction_interval", app_settings.extraction_interval
            ),
            "dream_interval_hours": user_settings.get(
                "dream_interval_hours", app_settings.dream_interval_hours
            ),
            "dream_min_sessions": user_settings.get(
                "dream_min_sessions", app_settings.dream_min_sessions
            ),
        },
    }


@router.put("/api/settings")
async def update_settings(settings_update: dict):
    """更新用户设置。"""
    from app.storage.paths import get_settings_path
    from app.storage import file_store

    # 读取现有设置
    existing = await file_store.read_json(get_settings_path()) or {}

    # 合并更新
    for key, value in settings_update.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            existing[key].update(value)
        else:
            existing[key] = value

    await file_store.write_json(get_settings_path(), existing)
    logger.info("用户设置已更新")
    return {"status": "updated"}
