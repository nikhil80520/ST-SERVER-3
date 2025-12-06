"""
PasswordResetOTP model - OTP tokens for password reset
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Index, func, BigInteger
from sqlalchemy.dialects import postgresql as pg
from sqlmodel import SQLModel, Field


class PasswordResetOTP(SQLModel, table=True):
    """PasswordResetOTP model - stores OTP tokens for password reset"""
    __tablename__ = "password_reset_otps"
    
    # Primary Key - Auto-incrementing integer
    password_reset_otp_id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    
    # User Identification
    email: str = Field(sa_column=Column(pg.VARCHAR, nullable=False, index=True))
    user_id: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))  # Keep as string for backward compatibility
    
    # OTP Information
    otp_hash: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
    used: bool = Field(default=False, sa_column=Column(pg.BOOLEAN, nullable=False, server_default="false"))
    attempts: int = Field(default=0, sa_column=Column(pg.INTEGER, nullable=False, server_default="0"))
    
    # Timestamps
    created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
    expires_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False))
    used_at: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
    # Indexes
    __table_args__ = (
        Index('idx_password_reset_email_used', 'email', 'used'),
        Index('idx_password_reset_expires_at', 'expires_at'),
    )
    
    def __repr__(self):
        return f"<PasswordResetOTP(password_reset_otp_id={self.password_reset_otp_id}, email={self.email}, used={self.used})>"
