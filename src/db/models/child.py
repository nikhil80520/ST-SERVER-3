"""
Child model - children profiles for personalized stories
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Column, Index, CheckConstraint, ForeignKey, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .user import User
    from .story import Story
    from .voice_clone import UserVoiceClone


class Child(SQLModel, table=True):
    """Child model - represents child profiles for personalized stories"""
    __tablename__ = "child"
    
    # Primary Key - Auto-incrementing integer
    child_id: int = Field( sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    
    # Foreign Key to User (integer) - REQUIRED
    user_id: int = Field(sa_column=Column( BigInteger,ForeignKey("user.user_id"),nullable=False, index=True ))
    
    # Child Information
    name: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
    age: int = Field(sa_column=Column(pg.INTEGER, nullable=False))
    interests: Optional[List[str]] = Field( default=None, sa_column=Column(pg.ARRAY(pg.VARCHAR), nullable=True))
    # Avatar/Image
    image_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    # System Configuration
    child_prompt: Optional[str] = Field(default=None, sa_column=Column(pg.TEXT, nullable=True))
    # Voice Clone - Optional FK to VoiceClone
    voice_clone_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("user_voice_clone.user_voice_clone_id", ondelete="SET NULL"),nullable=True))
    # Status
    is_active: bool = Field(
        default=True,
        sa_column=Column(pg.BOOLEAN, nullable=False, server_default="true")
    )
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Audit fields
    created_by: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    updated_by: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Relationships
    user: "User" = Relationship(back_populates="children")
    
    voice_clone: Optional["UserVoiceClone"] = Relationship(back_populates="children")
    
    stories: List["Story"] = Relationship(
        back_populates="child",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    
    # Constraints
    __table_args__ = (
        CheckConstraint('age > 0 AND age < 18', name='chk_age_positive'),
        Index('idx_children_user_id', 'user_id'),
        Index('idx_children_voice_clone_id', 'voice_clone_id'),
        Index('idx_children_user_active', 'user_id', 'is_active'),
        Index('idx_children_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<Child(child_id={self.child_id}, name={self.name}, age={self.age}, user_id={self.user_id})>"
    
    class Config:
        from_attributes = True
