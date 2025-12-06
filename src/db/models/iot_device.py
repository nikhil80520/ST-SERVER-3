# """
# IoTDevice model - ESP32 and other IoT devices
# """
# from datetime import datetime
# from typing import Optional, TYPE_CHECKING
# from sqlalchemy import Column, ForeignKey, Index, func, BigInteger
# from sqlalchemy.dialects import postgresql as pg
# from sqlmodel import SQLModel, Field, Relationship

# if TYPE_CHECKING:
#     from .user import User


# class IoTDevice(SQLModel, table=True):
#     """IoTDevice model - represents ESP32 and other IoT devices"""
#     __tablename__ = "iot_devices"
    
#     # Primary Key - Auto-incrementing integer
#     iot_device_id: int = Field(
#         sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
#     )
    
#     # Device Information
#     device_type: str = Field(sa_column=Column(pg.VARCHAR, nullable=False))
#     device_name: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
#     firmware_version: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
    
#     # Security
#     device_secret_hash: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, nullable=True))
#     claim_token: Optional[str] = Field(default=None, sa_column=Column(pg.VARCHAR, unique=True, nullable=True, index=True))
#     claim_token_expires: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
#     # Ownership - Optional FK to User
#     claimed_by_user_id: Optional[int] = Field(
#         default=None,
#         sa_column=Column(
#             BigInteger,
#             ForeignKey("users.user_id", ondelete="SET NULL"),
#             nullable=True,
#             index=True
#         )
#     )
#     claimed_at: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
#     # Status
#     status: str = Field(default="unclaimed", sa_column=Column(pg.VARCHAR, nullable=False, server_default="unclaimed"))
#     last_seen_at: Optional[datetime] = Field(default=None, sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=True))
    
#     # Device Metadata
#     device_metadata: Optional[dict] = Field(default=None, sa_column=Column(pg.JSONB, nullable=True))
    
#     # Timestamps
#     created_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now()))
#     updated_at: datetime = Field(sa_column=Column(pg.TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()))
    
#     # Relationship
#     claimed_by_user: Optional["User"] = Relationship(
#         back_populates="iot_devices",
#         sa_relationship_kwargs={"foreign_keys": "[IoTDevice.claimed_by_user_id]"}
#     )
    
#     # Indexes
#     __table_args__ = (
#         Index('idx_iot_devices_created_at', 'created_at'),
#     )
    
#     def __repr__(self):
#         return f"<IoTDevice(iot_device_id={self.iot_device_id}, type={self.device_type}, claimed_by={self.claimed_by_user_id})>"
