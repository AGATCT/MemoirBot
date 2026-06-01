"""
数据目录路径管理。

从配置中获取基础路径，提供便捷的路径构建方法。
"""

from pathlib import Path
from app.config import settings


def get_data_dir() -> Path:
    return settings.data_dir


def get_diaries_dir() -> Path:
    return settings.diaries_dir


def get_chats_dir() -> Path:
    return settings.chats_dir


def get_memories_dir() -> Path:
    return settings.memories_dir


def get_profile_dir() -> Path:
    return settings.profile_dir


def get_system_dir() -> Path:
    return settings.system_dir


def get_chat_session_dir(session_id: str) -> Path:
    return get_chats_dir() / session_id


def get_diary_path(year: int, month: int, day: int) -> Path:
    return get_diaries_dir() / str(year) / f"{month:02d}" / f"{day:02d}.md"


def get_memory_index_path() -> Path:
    return get_memories_dir() / "MEMORY.md"


def get_consolidation_lock_path() -> Path:
    return get_memories_dir() / ".consolidate-lock"


def get_profile_path() -> Path:
    return get_profile_dir() / "profile.json"


def get_dream_state_path() -> Path:
    return get_system_dir() / "dream_state.json"


def get_settings_path() -> Path:
    return get_system_dir() / "settings.json"


def ensure_directories() -> None:
    """创建所有必要的数据目录。"""
    dirs = [
        get_diaries_dir(),
        get_chats_dir(),
        get_memories_dir(),
        get_profile_dir(),
        get_system_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
