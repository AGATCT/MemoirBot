"""
记忆系统路由。

提供记忆搜索、浏览、矛盾管理等 API 和页面。
"""

import logging

from fastapi import APIRouter, HTTPException, Request, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


def get_memory_engine():
    """延迟获取 MemoryEngine。"""
    from app.web.dependencies import get_memory_engine as _get
    return _get()


def register_page_routes(app):
    """注册记忆页面路由。"""

    @app.get("/memory")
    async def memory_page(request: Request):
        from app.web.dependencies import templates
        return templates.TemplateResponse("memory.html", {"request": request})


# =============================================================================
# API 路由
# =============================================================================


@router.get("/search")
async def search_memories(q: str = "", type: str | None = None, limit: int = 50):
    """搜索记忆。

    Query params:
        q: 搜索关键词（在描述和内容中匹配）
        type: 按类型筛选
        limit: 返回条数上限
    """
    engine = get_memory_engine()
    if engine is None:
        return {"memories": [], "count": 0}

    headers = await engine.store.list_memories(mem_type=type)
    memories = []
    for h in headers:
        if q and q.lower() not in h.description.lower():
            mem = await engine.store.read_memory(h.id)
            if mem and q.lower() not in mem.content.lower():
                continue
        memories.append({
            "id": h.id,
            "filename": h.filename,
            "type": h.type,
            "description": h.description,
        })

    if limit:
        memories = memories[:limit]

    return {"memories": memories, "count": len(memories)}


@router.get("/all")
async def list_all_memories(
    type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """列出所有记忆（带完整内容）。"""
    engine = get_memory_engine()
    if engine is None:
        return {"memories": [], "count": 0}

    headers = await engine.store.list_memories(mem_type=type)
    memories = []
    for h in headers[offset : offset + limit]:
        mem = await engine.store.read_memory(h.id)
        if mem:
            memories.append({
                "id": mem.id,
                "type": mem.type,
                "name": mem.name,
                "description": mem.description,
                "content": mem.content,
                "source": mem.source,
                "updated_at": mem.updated_at,
            })

    return {
        "memories": memories,
        "count": len(memories),
        "total": len(headers),
    }


@router.get("/{memory_name}")
async def get_memory_detail(memory_name: str):
    """获取单条记忆的完整内容。"""
    engine = get_memory_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="记忆引擎未就绪")

    mem = await engine.store.read_memory(memory_name)
    if mem is None:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {
        "id": mem.id,
        "type": mem.type,
        "name": mem.name,
        "description": mem.description,
        "content": mem.content,
        "source": mem.source,
        "created_at": mem.created_at,
        "updated_at": mem.updated_at,
    }


@router.delete("/{memory_name}")
async def delete_memory(memory_name: str):
    """删除一条记忆。"""
    engine = get_memory_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="记忆引擎未就绪")

    deleted = await engine.store.delete_memory(memory_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"status": "deleted"}


@router.get("/stats/counts")
async def get_memory_stats():
    """获取记忆统计信息。"""
    engine = get_memory_engine()
    if engine is None:
        return {"total": 0, "by_type": {}}

    headers = await engine.store.list_memories()
    by_type = {}
    for h in headers:
        by_type[h.type] = by_type.get(h.type, 0) + 1

    return {
        "total": len(headers),
        "by_type": by_type,
    }
