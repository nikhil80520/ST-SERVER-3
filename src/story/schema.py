# ===== app/models/story.py =====
from pydantic import BaseModel
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime


class StoryPromptRequest(BaseModel):
    firebase_token: str
    
    # NEW: Child selection (parent-centric model)
    child_id: Optional[int] = None  # If provided, use this child's profile. If None, use default child.
    
    # New format fields (these override child profile if provided)
    child_name: Optional[str] = None  # Optional: Override child's name from profile
    child_age: Optional[int] = None  # Optional: Override child's age from profile
    morals: Optional[List[str]] = None  # List of morals (e.g., ["sharing", "kindness", "friendship"])
    story_length: Optional[str] = "medium"  # "short", "medium", "long"
    art_style: Optional[str] = "magical"  # Art style for image generation
    dimensions: Optional[str] = "portrait"  # "portrait", "landscape", or "square"
    cloned: Optional[bool] = True  # If true, use user's voice clone for audio generation (default True)
    voice_clone: Optional[bool] = True  # New parameter: if true, use user's cloned voice (default True)
    voice_clone_id: Optional[str] = None  # Specific voice clone ID to use (overrides auto-detection)
    language: Optional[str] = "english"  # Language for story generation and audio (e.g., "english", "hindi", "spanish", etc.)
    reference_image_ids: Optional[List[str]] = None  # Reference images to guide character likeness in generated art
    
    # Legacy fields for backward compatibility
    prompt: Optional[str] = None
    voice_option: Optional[str] = "auto"  # Voice selection
    
    # Legacy fields for backward compatibility
    genre: Optional[List[str]] = None
    illustration_style: Optional[str] = None
    use_cloned_voice: bool = True
    age_group: Optional[str] = "6-8"
    moral_lesson: Optional[str] = "friendship"
    emotion: Optional[str] = "happiness"
    isfemale: Optional[bool] = None

    @property
    def is_female_voice(self) -> bool:
        if self.voice_option and self.voice_option.lower() in ["eve", "female"]:
            return True
        elif self.voice_option and self.voice_option.lower() in ["adam", "male"]:
            return False
        elif self.voice_option == "auto":
            # Auto-detect based on child info or default to female
            return True
        return self.isfemale if self.isfemale is not None else True
    
    @property
    def should_use_voice_clone(self) -> bool:
        """Determine if user's cloned voice should be used"""
        # Prioritize new voice_clone parameter
        if self.voice_clone is not None:
            return self.voice_clone
        # Fall back to legacy cloned parameter
        if self.cloned is not None:
            return self.cloned
        # Fall back to legacy use_cloned_voice parameter
        return self.use_cloned_voice
    
    @property
    def scene_count(self) -> int:
        """Get number of scenes based on story length"""
        length_map = {
            "short": 5,
            "medium": 7,
            "long": 10
        }
        return length_map.get(self.story_length, 7)  # Default to medium (7 scenes)

class SystemPromptUpdate(BaseModel):
    firebase_token: str
    system_prompt: str

@dataclass
class StoryScene:
    scene_number: int
    text: str
    visual_prompt: str
    audio_url: str = ""
    image_url: str = ""  # Main colored image URL
    start_time: int = 0
    includes_child: bool = False  # Whether this scene includes the child as a character
    ambient_sound_keywords: str = ""  # 1-2 words for ambient sound (e.g., "forest birds", "ocean waves")
    emotion: str = "neutral"  # Emotion for TTS narration (e.g., "happy", "sad", "excited", "calm")
    reference_image_ids: List[str] = field(default_factory=list)  # NEW: per-scene reference image IDs (always a list, never None)

@dataclass
class StoryManifest:
    story_id: str
    title: str
    total_duration: int
    segments: List[Dict[str, Any]]

class UserStoriesRequest(BaseModel):
    firebase_token: str
    child_id: Optional[str] = None  # NEW: Filter by specific child. If None, return all children's stories
    limit: Optional[int] = 20
    offset: Optional[int] = 0

class StoryListItem(BaseModel):
    story_id: str
    title: str
    user_prompt: str
    created_at: datetime
    total_scenes: int
    total_duration: int
    status: str
    story_number: int
    thumbnail_url: Optional[str] = None
    created_at_formatted: str
    days_ago: int
    child_id: Optional[str] = None  # NEW: Associated child ID
    child_name: Optional[str] = None  # NEW: Child name for display

class UserStoriesResponse(BaseModel):
    success: bool
    user_id: str
    stories: List[StoryListItem]
    total_count: int
    has_more: bool
    user_info: Optional[Dict[str, Any]] = None