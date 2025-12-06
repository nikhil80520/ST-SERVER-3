"""
Story model - represents generated stories
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, Index, CheckConstraint, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .user import User
    from .child import Child

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import BigInteger, ForeignKey, Index, func, JSON
from sqlalchemy.dialects import postgresql as pg
from typing import Optional, List
from datetime import datetime


class Story(SQLModel, table=True):
    """Story model - represents generated stories"""
    __tablename__ = "story"
    
    # Primary Key
    story_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    
    # Foreign Keys
    user_id: int = Field(sa_column=Column(BigInteger, ForeignKey("user.user_id"), nullable=False, index=True))
    child_id: int = Field(sa_column=Column(BigInteger, ForeignKey("child.child_id"), nullable=False, index=True))
    
    # Story Content
    title: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
    genre: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    story_length: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Thumbnails and Media
    thumbnail_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    local_thumbnail_path: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Story Metadata
    duration: Optional[int] = Field(default=None, sa_column=Column(pg.INTEGER, nullable=True))
    target_scenes: Optional[int] = Field(default=None, sa_column=Column(pg.INTEGER, nullable=True))
    age_group: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Child Info Snapshot
    child_name: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    child_age: Optional[int] = Field(default=None, sa_column=Column(pg.INTEGER, nullable=True))
    
    # Story Parameters
    story_theme: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    moral_lesson: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    morals: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    target_emotion: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    parent_context: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    
    # Style and Design
    art_style: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    ambient_sound: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    thumbnail_prompt: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Relationships
    user: "User" = Relationship(
        back_populates="stories",
        sa_relationship_kwargs={"foreign_keys": "[Story.user_id]"}
    )
    
    child: Optional["Child"] = Relationship(
        back_populates="stories",
        sa_relationship_kwargs={"foreign_keys": "[Story.child_id]"}
    )
    
    scenes: List["StoryScene"] = Relationship(
        back_populates="story",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "order_by": "StoryScene.scene_number"}
    )
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_stories_user_child', 'user_id', 'child_id'),
        Index('idx_stories_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Story(story_id={self.story_id}, title={self.title}, user_id={self.user_id})>"


class StoryScene(SQLModel, table=True):
    """Scene model - represents individual scenes in a story"""
    __tablename__ = "story_scene"
    
    # Primary Key
    story_scene_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    # Foreign Key
    story_id: int = Field(sa_column=Column(BigInteger, ForeignKey("story.story_id"), nullable=False, index=True))
    # Scene Metadata
    scene_number: int = Field(sa_column=Column(pg.INTEGER, nullable=False))
    includes_child: bool = Field(default=False, sa_column=Column(pg.BOOLEAN, nullable=False, server_default='false'))
    emotion: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    reference_image_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Relationships
    story: "Story" = Relationship(back_populates="scenes")
    
    images: List["StorySceneImage"] = Relationship(
        back_populates="story_scene",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    audio: List["StorySceneAudio"] = Relationship(
        back_populates="story_scene",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_scenes_story_number', 'story_id', 'scene_number'),
        Index('idx_scenes_story_id', 'story_id'),
    )
    
    def __repr__(self):
        return f"<StoryScene(story_scene_id={self.story_scene_id}, scene_number={self.scene_number}, story_id={self.story_id})>"


class StorySceneImage(SQLModel, table=True):
    """StorySceneImage model - stores images for each scene"""
    __tablename__ = "story_scene_image"
    
    # Primary Key
    story_scene_image_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    
    # Foreign Key
    story_scene_id: int = Field(sa_column=Column(BigInteger, ForeignKey("story_scene.story_scene_id"), nullable=False, index=True))
    
    # Content - Moved from Scene
    text: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    visual_prompt: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    
    # Image Data
    image_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    image_type: Optional[str] = Field(default='scene', sa_column=Column(pg.VARCHAR, nullable=True))  # 'scene', 'thumbnail', etc.
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Relationships
    story_scene: "StoryScene" = Relationship(back_populates="images")
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_story_scene_images_story_scene_id', 'story_scene_id'),
    )
    
    def __repr__(self):
        return f"<StorySceneImage(story_scene_image_id={self.story_scene_image_id}, story_scene_id={self.story_scene_id})>"


class StorySceneAudio(SQLModel, table=True):
    """StorySceneAudio model - stores audio for each scene"""
    __tablename__ = "story_scene_audio"
    
    # Primary Key
    story_scene_audio_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    # Foreign Key
    story_scene_id: int = Field(sa_column=Column(BigInteger, ForeignKey("story_scene.story_scene_id"), nullable=False, index=True))
    # Content - Moved from Scene
    text: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    # Audio Data
    audio_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    audio_type: Optional[str] = Field(default='narration', sa_column=Column(pg.VARCHAR, nullable=True))  # 'narration', 'background', 'effects'
    duration: Optional[int] = Field(default=None, sa_column=Column(pg.INTEGER, nullable=True))  # Duration in seconds
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    # Relationships
    story_scene: "StoryScene" = Relationship(back_populates="audio")
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_story_scene_audio_story_scene_id', 'story_scene_id'),
    )
    
    def __repr__(self):
        return f"<StorySceneAudio(story_scene_audio_id={self.story_scene_audio_id}, story_scene_id={self.story_scene_id})>"