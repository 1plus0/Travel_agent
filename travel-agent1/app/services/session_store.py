# app/services/session_store.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Any, List

from langchain_core.messages import BaseMessage, messages_to_dict, messages_from_dict

from app.users.profile import UserProfile


@dataclass
class SessionState:
    profile: UserProfile
    history: List[BaseMessage]
    updated_at: float


class InMemorySessionStore:
    """
    开发用内存 store：单进程有效。
    上线建议替换为 RedisStore（接口保持一致即可）。
    """
    def __init__(self, ttl_seconds: int = 3600):
        self._db: Dict[str, Dict[str, Any]] = {}
        self.ttl_seconds = ttl_seconds

    def create(self) -> str:
        sid = str(uuid.uuid4())
        self.save(sid, UserProfile(), [], time.time())
        return sid

    def load(self, sid: str) -> Optional[SessionState]:
        row = self._db.get(sid)
        if not row:
            return None

        # TTL 过期清理
        if time.time() - row["updated_at"] > self.ttl_seconds:
            self._db.pop(sid, None)
            return None

        profile_dict = row["profile"]
        history_dicts = row["history"]

        profile = UserProfile(**profile_dict)  # 你的 UserProfile 是 dataclass/pydantic 都可调整
        history = messages_from_dict(history_dicts)

        return SessionState(profile=profile, history=history, updated_at=row["updated_at"])

    def save(self, sid: str, profile: UserProfile, history: List[BaseMessage], updated_at: Optional[float] = None) -> None:
        if updated_at is None:
            updated_at = time.time()

        self._db[sid] = {
            "profile": profile.to_dict(),               # 你已有 to_dict()
            "history": messages_to_dict(history),       # 序列化 BaseMessage
            "updated_at": updated_at,
        }
