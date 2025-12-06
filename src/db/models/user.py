"""
User model - main parent table
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Column, Index, CheckConstraint, ForeignKey, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .child import Child
    from .story import Story
    from .reference_image import UserReferenceImage
    from .voice_clone import UserVoiceClone


class User(SQLModel, table=True):
    """User model - represents parent accounts"""
    __tablename__ = "user"
    
    # Primary Key - Auto-incrementing integer
    user_id: int = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    
    # Firebase User ID - Unique indexed field
    firebase_user_id: str = Field(
        sa_column=Column(pg.VARCHAR(255), nullable=False, unique=True, index=True)
    )
    
    # Parent Information
    first_name: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR(150), nullable=True))
    last_name: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR(150), nullable=True))
    email: str = Field(sa_column=Column(pg.VARCHAR(320), nullable=False, unique=True, index=True))
    phone_number: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR(20), nullable=True))
    
    # Profile
    profile_pic_url: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    
    # Avatar Configuration (legacy - can be removed if not needed)
    avatar_seed: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    avatar_style: str = Field(default="adventurer", sa_column=Column(pg.VARCHAR, nullable=False, server_default="adventurer"))
    avatar_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    avatar_generated: bool = Field(default=False, sa_column=Column(pg.BOOLEAN, nullable=False, server_default="false"))
    avatar_updated_at: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
    # Counts
    children_count: int = Field(default=0, sa_column=Column(pg.INTEGER, nullable=False, server_default="0"))
    default_child_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    story_count: int = Field(default=0, sa_column=Column(pg.INTEGER, nullable=False, server_default="0"))
    reference_images_count: int = Field(default=0, sa_column=Column(pg.INTEGER, nullable=False, server_default="0"))
    
    # Token Balance
    token_balance: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    
    # Account Status
    account_status: str = Field(default="trial_active", sa_column=Column(pg.VARCHAR, nullable=False, server_default="trial_active"))
    account_status_data: Optional[dict] = Field(default=None, sa_column=Column(pg.JSONB, nullable=True))
    is_archive: bool = Field(default=False, sa_column=Column(pg.BOOLEAN, nullable=False, server_default="false"))
    
    # Activity Tracking
    last_active: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Audit fields
    created_by: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    updated_by: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Relationships
    children: List["Child"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    stories: List["Story"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "Story.user_id"
        }
    )
    
    reference_images: List["UserReferenceImage"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    voice_clones: List["UserVoiceClone"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    # Constraints
    __table_args__ = (
        CheckConstraint('children_count >= 0', name='chk_children_count'),
        CheckConstraint('token_balance >= 0', name='chk_token_balance'),
        Index('idx_users_firebase_user_id', 'firebase_user_id'),
        Index('idx_users_email', 'email'),
        Index('idx_users_created_at', 'created_at'),
        Index('idx_users_last_active', 'last_active'),
    )
    
    def __repr__(self):
        return f"<User(user_id={self.user_id}, firebase_user_id={self.firebase_user_id}, email={self.email})>"
    
    class Config:
        from_attributes = True
