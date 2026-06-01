"""
用户画像管理。

由 DreamAgent 定期从记忆中重建。
"""

import logging
from datetime import datetime

from app.memory.schemas import UserProfile
from app.storage import file_store
from app.storage.paths import get_profile_path

logger = logging.getLogger(__name__)


class UserProfileManager:
    """用户画像管理器。"""

    def __init__(self):
        self._profile: UserProfile | None = None

    async def get_profile(self) -> UserProfile:
        if self._profile is None:
            self._profile = await self._load()
        return self._profile

    async def update_profile(self, **kwargs) -> UserProfile:
        profile = await self.get_profile()
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.last_updated = datetime.now().isoformat()
        await self._save(profile)
        self._profile = profile
        return profile

    async def rebuild_from_memories(self, memories: list) -> UserProfile:
        """从记忆中重建画像（精炼摘要）。"""
        profile = await self.get_profile()

        user_mems = [m for m in memories if m.type == "user"]
        profile.summary = "；".join([m.description for m in user_mems[:5]])

        state_mems = [m for m in memories if m.type == "state"]
        if state_mems:
            profile.current_focus = state_mems[0].description

        event_mems = [m for m in memories if m.type == "event"]
        profile.recent_events = [
            {"summary": m.description, "date": "", "memory_id": m.id}
            for m in event_mems[:3]
        ]

        feedback_mems = [m for m in memories if m.type == "feedback"]
        if feedback_mems:
            profile.preferences["behavior_notes"] = "；".join(
                [m.description for m in feedback_mems]
            )

        profile.last_updated = datetime.now().isoformat()
        profile.version += 1
        await self._save(profile)
        self._profile = profile
        logger.info(f"从 {len(memories)} 条记忆重建用户画像")
        return profile

    async def _load(self) -> UserProfile:
        data = await file_store.read_json(get_profile_path())
        if data:
            try:
                return UserProfile(**data)
            except Exception:
                pass
        return UserProfile()

    async def _save(self, profile: UserProfile) -> None:
        await file_store.write_json(get_profile_path(), profile.model_dump())
