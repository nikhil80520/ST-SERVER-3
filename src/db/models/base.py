"""
Base models and mixins for all database tables
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, func
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import Field


class TimestampMixin:
    """Mixin for created_at and updated_at timestamp fields"""
    created_at: datetime = Field(
        sa_column=Column(
            pg.TIMESTAMP(timezone=True), 
            nullable=False, 
            server_default=func.now()
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            pg.TIMESTAMP(timezone=True), 
            nullable=False, 
            server_default=func.now(), 
            onupdate=func.now()
        )
    )


class AuditMixin:
    """Mixin for created_by and updated_by audit fields"""
    created_by: Optional[str] = Field(
        default=None,
        sa_column=Column(pg.VARCHAR, nullable=True)
    )
    updated_by: Optional[str] = Field(
        default=None,
        sa_column=Column(pg.VARCHAR, nullable=True)
    )
