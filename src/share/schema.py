from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ShareSettings(BaseModel):
    allow_copy: bool = True
    show_creator: bool = True
    track_analytics: bool = True

class SharingInfo(BaseModel):
    is_shareable: bool = False
    share_token: Optional[str] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    view_count: int = 0
    copy_count: int = 0
    disabled_at: Optional[datetime] = None

class AccessLogEntry(BaseModel):
    user_id: str
    timestamp: datetime
    action: str

class StoryAnalytics(BaseModel):
    views: int = 0
    copies_made: int = Field(0, alias='copies')
    access_log: List[AccessLogEntry] = []
    last_viewed: Optional[datetime] = None

    class Config:
        populate_by_name = True

class ShareStoryRequest(BaseModel):
    story_id: str
    settings: Optional[ShareSettings] = Field(default_factory=ShareSettings)
    expires_at: Optional[datetime] = None

class SharedStoryResponse(BaseModel):
    share_url: str
    qr_code_url: str
    share_token: str
    expires_at: Optional[datetime] = None

class CopyStoryRequest(BaseModel):
    share_token: str

class ShareUpdate(BaseModel):
    allow_copy: Optional[bool] = None
    show_creator: Optional[bool] = None
    expires_at: Optional[datetime] = None

class ShareToken(BaseModel):
    share_token: str

class SharedStoryAccessLog(BaseModel):
    user_id: str = "anonymous"
    accessed_at: datetime = Field(default_factory=datetime.utcnow)
    action: str # "viewed" or "copied"
    new_story_id: Optional[str] = None

class SharedStory(BaseModel):
    share_id: str
    story_id: str
    owner_id: str
    share_token: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    is_active: bool = True
    disabled_at: Optional[datetime] = None
    settings: ShareSettings = Field(default_factory=ShareSettings)
    access_log: List[SharedStoryAccessLog] = []
    stats: dict = {"total_views": 0, "unique_viewers": 0, "total_copies": 0}

class StorySharingStats(BaseModel):
    stories_shared_by_me: int = 0
    total_story_views: int = 0
    most_viewed_story_id: Optional[str] = None

class UserSharingStats(BaseModel):
    stories_shared_by_me: int = 0
    total_story_views: int = 0
    most_viewed_story_id: Optional[str] = None
    stories_shared_with_me: int = 0
    stories_copied: int = 0
    first_share_date: Optional[datetime] = None
    last_copy_date: Optional[datetime] = None
    total_shares: Optional[int] = 0 # From service
    total_views: Optional[int] = 0 # From service

class TopSharedStory(BaseModel):
    story_id: str
    title: str
    views: int
    copies: int

class SharingDashboard(BaseModel):
    user_id: str
    stats: UserSharingStats
    top_shared_stories: List[TopSharedStory]

class BatchUpdateRequest(BaseModel):
    story_ids: List[str]
    enable: bool
    settings: Optional[ShareSettings] = None

class BatchUpdateResponse(BaseModel):
    success: int
    failed: int

class RenewRequest(BaseModel):
    new_expires_at: Optional[datetime] = None

class RenewLinkResponse(BaseModel):
    story_id: str
    message: str
    new_expires_at: Optional[datetime] = None
