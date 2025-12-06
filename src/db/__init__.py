"""
Database package
"""
from .session import (
    init_database,
    close_database,
    create_tables,
    drop_tables,
    get_db,
    get_db_info,
)
from .main import (
    async_engine,
    get_session,
)
from .models import (
    User,
    Child,
    Story,
    StoryScene,
    StorySceneAudio,
    StorySceneImage,
    UserReferenceImage,
    UserVoiceClone,
    # IoTDevice,
    PasswordResetOTP
    # UserActivity,
)

__all__ = [
    # Session management
    "init_database",
    "close_database",
    "create_tables",
    "drop_tables",
    "get_db",
    "get_db_info",
    # New async engines and sessions
    "async_engine",
    "get_session",
    # Models
    "User",
    "Child",
    "Story",
    "StoryShare",
    "ReferenceImage",
    "VoiceClone",
    "IoTDevice",
    "PasswordResetOTP",
    "UserActivity",
]
