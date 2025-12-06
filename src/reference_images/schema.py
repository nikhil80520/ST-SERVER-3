"""
Reference Images Schema
Pydantic models for reference images API
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ReferenceImageBase(BaseModel):
    """Base reference image model"""
    title: str
    description: Optional[str] = None
    image_url: str
    age_group: Optional[str] = None
    category: Optional[str] = None


class ReferenceImageCreate(ReferenceImageBase):
    """Schema for creating reference image"""
    firebase_token: str


class ReferenceImageUpdate(BaseModel):
    """Schema for updating reference image"""
    title: Optional[str] = None
    description: Optional[str] = None
    age_group: Optional[str] = None
    category: Optional[str] = None


class ReferenceImageResponse(ReferenceImageBase):
    """Schema for reference image response"""
    reference_image_id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReferenceImageListRequest(BaseModel):
    """Schema for listing reference images"""
    firebase_token: Optional[str] = None
    limit: int = 20
    offset: int = 0
    category: Optional[str] = None


class ReferenceImageListResponse(BaseModel):
    """Schema for reference images list response"""
    success: bool
    reference_images: List[ReferenceImageResponse]
    total_count: int
    has_more: bool
