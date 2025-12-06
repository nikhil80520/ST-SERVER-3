"""
VoiceClone model - Cartesia voice clones
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, Index, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .user import User
    from .child import Child


class UserVoiceClone(SQLModel, table=True):
    """VoiceClone model - stores Cartesia voice clone configurations"""
    __tablename__ = "user_voice_clone"
    
    # Primary Key - Auto-incrementing integer
    user_voice_clone_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    
    # Foreign Key to User
    user_id: int = Field(sa_column=Column( BigInteger,ForeignKey("user.user_id"), nullable=False, index=True))
    # Voice Clone Information
    name: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
    description: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    language: str = Field(default="en", sa_column=Column(pg.VARCHAR, nullable=False, server_default="en"))
    
    # Cartesia Integration
    cartesia_voice_id: str = Field(sa_column=Column(pg.VARCHAR, unique=True, nullable=False, index=True))
    sample_audio_url: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Status
    is_active: bool = Field(default=True, sa_column=Column(pg.BOOLEAN, nullable=False, server_default="true"))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Relationships
    user: "User" = Relationship(back_populates="voice_clones")
    children: List["Child"] = Relationship(
        back_populates="voice_clone",
        sa_relationship_kwargs={"foreign_keys": "Child.voice_clone_id"}
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_voice_clones_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<VoiceClone(voice_clone_id={self.voice_clone_id}, name={self.name}, cartesia_id={self.cartesia_voice_id})>"
