"""
聊天相关路由。

提供会话 CRUD 和消息 SSE 流式接口。
"""

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.chat.engine import ChatEngine
from app.chat.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    RenameSessionRequest,
    SendMessageRequest,
    SessionListItem,
)
from app.web.dependencies import get_chat_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


# =============================================================================
# 页面路由
# =============================================================================


def register_page_routes(app):
    """注册聊天页面路由到 FastAPI 应用。"""

    @app.get("/")
    async def index(request: Request):
        """首页重定向到聊天页面。"""
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/chat")

    @app.get("/chat")
    async def chat_page(request: Request):
        """聊天页面。"""
        from app.web.dependencies import templates
        return templates.TemplateResponse("chat.html", {"request": request})


# =============================================================================
# API 路由
# =============================================================================


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest | None = None):
    """创建新聊天会话。"""
    engine = get_chat_engine()
    title = req.title if req else None
    session_id = await engine.create_session(title)
    return CreateSessionResponse(
        session_id=session_id,
        title=title or "新对话",
        created_at="",  # 将由前端从详情获取
    )


@router.get("/sessions", response_model=list[SessionListItem])
async def list_sessions():
    """获取所有会话列表。"""
    engine = get_chat_engine()
    sessions = await engine.session_mgr.list_sessions()
    return [
        SessionListItem(
            session_id=s.session_id,
            title=s.title,
            updated_at=s.updated_at,
            message_count=s.message_count,
            is_active=s.is_active,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情（含消息历史）。"""
    engine = get_chat_engine()
    meta = await engine.session_mgr.get_metadata(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = await engine.session_mgr.get_messages(session_id)
    return {
        "metadata": meta.model_dump(),
        "messages": [m.model_dump() for m in messages],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话。"""
    engine = get_chat_engine()
    deleted = await engine.session_mgr.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "deleted"}


@router.patch("/sessions/{session_id}")
async def rename_session(session_id: str, req: RenameSessionRequest):
    """重命名会话。"""
    engine = get_chat_engine()
    meta = await engine.session_mgr.update_metadata(session_id, title=req.title)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "renamed", "title": req.title}


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, req: SendMessageRequest):
    """发送消息并流式返回 AI 响应（SSE）。

    返回 Server-Sent Events 流：
      event: token
      data: {"content": "..."}

      event: done
      data: {"msg_id": "..."}

      event: extraction
      data: {"status": "started", "message": "..."}

      event: error
      data: {"message": "..."}
    """
    engine = get_chat_engine()

    # 验证会话存在
    meta = await engine.session_mgr.get_metadata(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    async def event_stream():
        try:
            async for event in engine.send_message(session_id, req.content):
                event_type = event.get("type", "token")
                data = {k: v for k, v in event.items() if k != "type"}
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"SSE 流错误: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
