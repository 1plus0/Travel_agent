# app/routers/chat.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from app.services.session_store import InMemorySessionStore
from app.services.chat_runtime import run_one_turn


router = APIRouter(prefix="/chat", tags=["chat"])

store = InMemorySessionStore(ttl_seconds=3600)


class StartResp(BaseModel):
    session_id: str


@router.post("/start", response_model=StartResp)
def start_chat():
    sid = store.create()
    return StartResp(session_id=sid)


class ChatReq(BaseModel):
    session_id: str = Field(..., description="会话ID：从 /chat/start 获取")
    message: str = Field(..., description="用户输入文本")
    # 可选：前端也可以把 profile 传上来作为“客户端缓存”兜底，但以服务端为准
    client_meta: Optional[Dict[str, Any]] = None


class ChatResp(BaseModel):
    session_id: str
    reply: str
    profile: Dict[str, Any]


@router.post("/message1", response_model=ChatResp)
def chat_message(req: ChatReq):
    state = store.load(req.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新 start")

    user_text = req.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="message 不能为空")

    reply, profile, history = run_one_turn(state.profile, state.history, user_text)

    store.save(req.session_id, profile, history)
    return ChatResp(session_id=req.session_id, reply=reply, profile=profile.to_dict())


