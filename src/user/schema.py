"""
User Schema Module
Contains all request and response models for user endpoints.
Does not include child-related schemas (those are in children/schema.py).
"""
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime

# ===== ACCOUNT STATUS MODELS =====

class AccountStatus(str, Enum):
    """Account status enum for subscription and payment states"""
    TRIAL_ACTIVE = "trial_active"  # On free trial, full access
    TRIAL_EXPIRED = "trial_expired"  # Trial ended, no payment yet
    ACTIVE_PAID = "active_paid"  # Fully paid & active
    PAYMENT_FAILED = "payment_failed"  # Payment method invalid
    GRACE_PERIOD = "grace_period"  # Payment failed but grace period active
    SUSPENDED_UNPAID = "suspended_unpaid"  # Account access limited due to unpaid status
    CANCELLED = "cancelled"  # Subscription canceled by user
    DISABLED_BY_ADMIN = "disabled_by_admin"  # Admin/team manually deactivated
    DELETED = "deleted"  # Data permanently deleted or queued for deletion

class AccountStatusInfo(BaseModel):
    """Detailed account status information"""
    status: AccountStatus
    trial_end_date: Optional[str] = None  # ISO 8601 datetime
    subscription_end_date: Optional[str] = None  # ISO 8601 datetime
    grace_period_end_date: Optional[str] = None  # ISO 8601 datetime
    payment_failed_date: Optional[str] = None  # ISO 8601 datetime
    last_payment_date: Optional[str] = None  # ISO 8601 datetime
    cancellation_date: Optional[str] = None  # ISO 8601 datetime
    disabled_date: Optional[str] = None  # ISO 8601 datetime
    disabled_reason: Optional[str] = None  # Reason for admin disable
    can_access_content: bool = True  # Whether user can access stories
    can_create_stories: bool = True  # Whether user can generate new stories
    requires_payment: bool = False  # Whether payment is required
    message: Optional[str] = None  # Human-readable status message
    action_required: Optional[str] = None  # What action user needs to take


# ===== PROFILE MODELS =====

class ChildProfile(BaseModel):
    """Legacy child profile (for backward compatibility with old registration)"""
    name: str
    age: int
    interests: List[str]
    image_url: Optional[str] = None  # URL to child's profile image
    avatar_seed: Optional[str] = None  # Custom seed for avatar generation
    avatar_style: Optional[str] = "avataaars"  # Avatar style (avataaars, etc.)
    avatar_generated: Optional[bool] = False  # Whether avatar has been generated

class ParentProfile(BaseModel):
    name: str
    email: EmailStr
    phone_number: Optional[str] = None
    avatar_seed: Optional[str] = None  # Custom seed for parent avatar
    avatar_style: Optional[str] = "avataaars"  # Avatar style
    avatar_generated: Optional[bool] = False  # Whether avatar has been generated

class UserRegistration(BaseModel):
    firebase_token: str
    parent: ParentProfile
    child: ChildProfile
    system_prompt: Optional[str] = None
    child_image_base64: Optional[str] = None  # Base64 encoded image data
    voice_audio_base64: Optional[str] = None  # Base64 encoded audio data for voice cloning (MP3)

class UserProfileUpdate(BaseModel):
    firebase_token: str
    parent: Optional[ParentProfile] = None
    child: Optional[ChildProfile] = None
    system_prompt: Optional[str] = None
    child_image_base64: Optional[str] = None  # Base64 encoded image data
    voice_audio_base64: Optional[str] = None  # Base64 encoded audio data for voice cloning (MP3)

class UserProfileResponse(BaseModel):
    user_id: str
    parent: ParentProfile
    child: ChildProfile
    system_prompt: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    story_count: Optional[int] = 0
    last_active: Optional[str] = None
    account_status: Optional[AccountStatusInfo] = None  # Account subscription/payment status

class AvatarUpdateRequest(BaseModel):
    firebase_token: str
    target: str  # "child" or "parent"
    avatar_seed: str
    avatar_style: Optional[str] = "avataaars"

# New models for unified avatar consistency system
class UserAvatarUpdate(BaseModel):
    avatar_style: str
    avatar_seed: str
    avatar_url: str

class UserAvatarResponse(BaseModel):
    success: bool
    message: str
    avatar_url: Optional[str] = None
    user_id: Optional[str] = None

# Voice Clone Models
class AudioCorruptionCheck(BaseModel):
    null_bytes: int = 0
    base64_length: int
    is_valid_base64: bool

class AudioData(BaseModel):
    base64: str
    format: str  # m4a, wav, mp3
    mime_type: str  # audio/mp4, audio/wav, audio/mpeg
    size_bytes: int
    duration_ms: Optional[int] = None
    sample_rate: Optional[int] = 44100
    channels: Optional[int] = 1
    platform: Optional[str] = None  # ios, android
    corruption_check: AudioCorruptionCheck

class VoiceCloneCreate(BaseModel):
    firebase_token: str
    voice_name: str
    description: str = "Custom voice clone"
    audio_data: AudioData

class VoiceCloneUpdate(BaseModel):
    firebase_token: str
    voice_clone_id: str  # Which voice clone to update
    voice_name: str
    description: str = "Updated voice clone"
    audio_data: AudioData

class VoiceCloneMetadata(BaseModel):
    voice_clone_id: str
    voice_id: str  # Cartesia voice ID
    voice_name: str
    description: Optional[str] = None
    is_active: bool = False  # Which voice is currently selected
    created_at: str
    updated_at: str

class VoiceCloneListResponse(BaseModel):
    user_id: str
    voice_clones: List[VoiceCloneMetadata]
    active_voice_clone_id: Optional[str] = None
    default_voice: Dict[str, Any]  # Default Cartesia voice info

class VoiceCloneSetActiveRequest(BaseModel):
    firebase_token: str
    voice_clone_id: str  # "default" or "vc_xxxxx"

class VoiceCloneDeleteRequest(BaseModel):
    firebase_token: str
    voice_clone_id: str

class VoiceCloneListRequest(BaseModel):
    firebase_token: Optional[str] = None  # Optional - can use Authorization header instead

class VoicePreviewRequest(BaseModel):
    firebase_token: str
    voice_clone_id: str  # "default" or "vc_xxxxx"
    preview_text: Optional[str] = None

class User(BaseModel):
    uid: str
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    token: Optional[Dict[str, Any]] = None