"""
Children Schema Module
Contains all request and response models for children endpoints.
"""
from pydantic import BaseModel
from typing import List, Optional


# ===== CHILDREN DATA MODELS =====

class Child(BaseModel):
    """Full child model with ID (used for database storage)"""
    child_id: int  # Auto-increment integer from database
    name: str
    age: int
    interests: List[str]
    image_url: Optional[str] = None
    avatar_seed: Optional[str] = None
    avatar_style: Optional[str] = "avataaars"
    avatar_url: Optional[str] = None
    system_prompt: Optional[str] = None  # Child-specific system prompt
    voice_clone_id: Optional[int] = None  # FK to voice clone table (integer)
    is_active: bool = True  # For soft deletion
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ===== REQUEST SCHEMAS =====

class ChildCreate(BaseModel):
    """Request model for creating a new child"""
    firebase_token: str
    name: str
    age: int
    interests: List[str]
    image_base64: Optional[str] = None  # Base64 encoded profile image
    avatar_seed: Optional[str] = None
    avatar_style: Optional[str] = "avataaars"
    system_prompt: Optional[str] = None


class ChildUpdate(BaseModel):
    """Request model for updating a child"""
    firebase_token: str
    name: Optional[str] = None
    age: Optional[int] = None
    interests: Optional[List[str]] = None
    image_base64: Optional[str] = None
    avatar_seed: Optional[str] = None
    avatar_style: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_clone_id: Optional[int] = None  # FK to voice clone table (integer)


class ChildSelectRequest(BaseModel):
    """Request to set a child as default/selected"""
    firebase_token: str


class ChildSystemPromptUpdate(BaseModel):
    """Request to update only the child's system prompt"""
    firebase_token: str
    system_prompt: str


class ChildVoiceCloneSelectRequest(BaseModel):
    """Request to assign/select a voice clone for a child"""
    firebase_token: str
    voice_clone_id: str


class ChildReferenceImageLinkRequest(BaseModel):
    """Request to link an existing reference image to a child"""
    firebase_token: str
    reference_image_id: str


# ===== RESPONSE SCHEMAS =====

class ChildResponse(BaseModel):
    """Response model for child data with statistics"""
    child_id: int  # Auto-increment integer from database
    name: str
    age: int
    interests: List[str]
    image_url: Optional[str] = None
    avatar_seed: Optional[str] = None
    avatar_style: Optional[str] = None
    avatar_url: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_clone_id: Optional[int] = None  # FK to voice clone table (integer)
    is_active: bool
    story_count: Optional[int] = 0
    voice_clones_count: Optional[int] = 0
    reference_images_count: Optional[int] = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ChildrenListResponse(BaseModel):
    """Response for listing all children"""
    success: bool
    children: List[ChildResponse]
    default_child_id: Optional[int] = None  # Integer child_id
    total_count: int


class ChildProfilePictureResponse(BaseModel):
    """Response model for child profile picture information"""
    success: bool
    child_id: int
    image_url: Optional[str] = None
    has_profile_picture: bool


class ChildStatsResponse(BaseModel):
    """Response model for aggregated children statistics"""
    success: bool
    stats: dict


class ChildStoriesResponse(BaseModel):
    """Response model for child's stories"""
    success: bool
    child_id: int
    child_name: str
    stories: List[dict]
    total_count: int
    has_more: bool


class ChildOperationResponse(BaseModel):
    """Generic response for child operations (create, update, delete, select)"""
    success: bool
    message: str
    child: Optional[ChildResponse] = None
    child_id: Optional[int] = None
    default_child_id: Optional[int] = None


class HealthCheckResponse(BaseModel):
    """Response model for health check endpoint"""
    success: bool
    service: str
    firebase_available: bool
    status: str
