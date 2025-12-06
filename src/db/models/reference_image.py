"""
ReferenceImage model - user-uploaded reference images
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Column, ForeignKey, Index, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .user import User


class UserReferenceImage(SQLModel, table=True):
    """ReferenceImage model - stores user-uploaded reference images for story generation"""
    __tablename__ = "user_reference_image"
    
    # Primary Key - Auto-incrementing integer
    user_reference_image_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=True))
    # Foreign Key to User
    user_id: int = Field( sa_column=Column( BigInteger,ForeignKey("user.user_id"),  nullable=False,index=True))
    # Image Information
    image_url: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
    storage_path: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    description: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    # File Metadata
    file_size: Optional[int] = Field(default=None, sa_column=Column(pg.INTEGER, nullable=True))
    mime_type: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
    # Relationship
    user: "User" = Relationship(back_populates="reference_images")
    
    # Indexes
    __table_args__ = (
        Index('idx_reference_images_created_at', 'created_at'),
    )
    
    def __repr__(self):
        return f"<ReferenceImage(reference_image_id={self.reference_image_id}, user_id={self.user_id})>"
