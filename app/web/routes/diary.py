"""
日记相关路由。
"""

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request

from app.diary.engine import DiaryEngine
from app.diary.schemas import DiaryEntryCreate, DiaryEntrySummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diary", tags=["diary"])

# 日记引擎单例
_diary_engine: DiaryEngine | None = None


def get_diary_engine() -> DiaryEngine:
    global _diary_engine
    if _diary_engine is None:
        _diary_engine = DiaryEngine()
    return _diary_engine


def register_page_routes(app):
    """注册日记页面路由。"""

    @app.get("/diary")
    async def diary_page(request: Request):
        from app.web.dependencies import templates
        return templates.TemplateResponse("diary.html", {"request": request})


# =============================================================================
# API 路由
# =============================================================================


@router.get("/entries")
async def list_entries(year: int | None = None, month: int | None = None):
    """获取日记列表。

    Query params:
        year: 年份筛选
        month: 月份筛选（需配合 year）
    """
    engine = get_diary_engine()
    entries = await engine.list_entries(year=year, month=month)
    return [e.model_dump() for e in entries]


@router.post("/entries")
async def save_entry(entry_data: DiaryEntryCreate):
    """创建或更新日记条目。"""
    engine = get_diary_engine()
    entry = await engine.save_entry(entry_data)
    return entry.model_dump()


@router.get("/entries/{entry_date}")
async def get_entry(entry_date: str):
    """获取指定日期的日记。entry_date 格式: YYYY-MM-DD"""
    try:
        parts = entry_date.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="日期格式无效，应为 YYYY-MM-DD")

    entry = await get_diary_engine().get_entry(year, month, day)
    if entry is None:
        raise HTTPException(status_code=404, detail="该日期没有日记")
    return entry.model_dump()


@router.delete("/entries/{entry_date}")
async def delete_entry(entry_date: str):
    """删除指定日期的日记。"""
    try:
        parts = entry_date.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="日期格式无效，应为 YYYY-MM-DD")

    deleted = await get_diary_engine().delete_entry(year, month, day)
    if not deleted:
        raise HTTPException(status_code=404, detail="该日期没有日记")
    return {"status": "deleted"}


@router.get("/month/{year}/{month}")
async def get_month_view(year: int, month: int):
    """获取某月的日记概览（哪些日期有日记）。"""
    entries = await get_diary_engine().get_month_view(year, month)
    return {
        "year": year,
        "month": month,
        "entries": {str(k): v.model_dump() for k, v in entries.items()},
    }
