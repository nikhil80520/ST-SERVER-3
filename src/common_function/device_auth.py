"""
Device Authentication Middleware
Handles HMAC and JWT authentication for IoT devices
"""

import time
from typing import Union, Optional
from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.db.models import Device
from src.common_function.database import get_db
from src.common_function.security import verify_hmac, verify_device_jwt, decrypt_device_secret
import logging

logger = logging.getLogger(__name__)

class DeviceAuth:
    """Device authentication result"""
    def __init__(self, device_id: str, auth_method: str, device_status: str = None):
        self.device_id = device_id
        self.auth_method = auth_method  # "hmac" or "jwt"
        self.device_status = device_status

async def get_device_secret(device_id: str, db: AsyncSession) -> Optional[bytes]:
    """
    Get device secret for HMAC verification
    
    Args:
        device_id: Device identifier
        db: Database session
        
    Returns:
        Device secret bytes or None if not found
    """
    try:
        # Query device
        stmt = select(Device).where(Device.device_id == device_id)
        result = await db.execute(stmt)
        device = result.scalar_one_or_none()
        
        if not device:
            logger.warning(f"Device not found: {device_id}")
            return None
        
        # For now, we'll store the secret encrypted. In production, consider using a KMS
        # For this implementation, we'll assume the secret is stored as a hash and we need
        # to implement a different strategy (like storing encrypted secrets)
        
        # TODO: Implement proper secret storage/retrieval
        # For now, return a test secret (in production, decrypt from device.device_secret_hash)
        return b"test-device-secret-" + device_id.encode()[:16]
        
    except Exception as e:
        logger.error(f"Error getting device secret for {device_id}: {e}")
        return None

async def require_device_hmac(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DeviceAuth:
    """
    Middleware to require HMAC authentication from device
    
    Expected headers:
    - X-Device-Id: Device UUID
    - X-Timestamp: Unix timestamp
    - X-Signature: HMAC-SHA256 signature in hex
    
    Returns:
        DeviceAuth object with device_id and auth info
    """
    # Extract headers
    device_id = request.headers.get("X-Device-Id")
    timestamp_str = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")
    
    if not all([device_id, timestamp_str, signature]):
        logger.warning("Missing HMAC headers")
        raise HTTPException(
            status_code=401,
            detail="missing_auth_headers",
            headers={"WWW-Authenticate": "HMAC"}
        )
    
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_timestamp")
    
    # Get device secret
    device_secret = await get_device_secret(device_id, db)
    if not device_secret:
        raise HTTPException(status_code=401, detail="device_not_found")
    
    # Get request body
    body = await request.body()
    
    # Verify HMAC
    try:
        verify_hmac(
            device_secret=device_secret,
            method=request.method,
            path=request.url.path,
            body=body,
            timestamp=timestamp,
            signature_hex=signature
        )
    except HTTPException:
        # Log the attempt
        logger.warning(f"HMAC verification failed for device {device_id}")
        raise
    
    # Get device status
    stmt = select(Device.status).where(Device.device_id == device_id)
    result = await db.execute(stmt)
    device_status = result.scalar_one_or_none()
    
    logger.info(f"HMAC authentication successful for device {device_id}")
    return DeviceAuth(device_id=device_id, auth_method="hmac", device_status=device_status)

async def require_device_jwt(
    request: Request,
    audience: str = "device-api"
) -> DeviceAuth:
    """
    Middleware to require JWT authentication from device
    
    Expected header:
    - Authorization: Bearer <jwt_token>
    
    Returns:
        DeviceAuth object with device_id and auth info
    """
    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="missing_jwt_token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = auth_header[7:]  # Remove "Bearer " prefix
    
    # Verify JWT
    try:
        payload = verify_device_jwt(token, audience=audience)
        device_id = payload["sub"]
        
        logger.info(f"JWT authentication successful for device {device_id}")
        return DeviceAuth(device_id=device_id, auth_method="jwt")
        
    except HTTPException:
        logger.warning("JWT verification failed")
        raise

async def device_auth_either(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> DeviceAuth:
    """
    Middleware that accepts either HMAC or JWT authentication
    
    Tries JWT first (faster), falls back to HMAC
    """
    # Try JWT first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        try:
            return await require_device_jwt(request)
        except HTTPException:
            pass  # Fall through to HMAC
    
    # Try HMAC
    device_id = request.headers.get("X-Device-Id")
    if device_id:
        try:
            return await require_device_hmac(request, db)
        except HTTPException:
            pass
    
    # Neither worked
    raise HTTPException(
        status_code=401,
        detail="authentication_required",
        headers={"WWW-Authenticate": "HMAC, Bearer"}
    )

def require_device_claimed(auth: DeviceAuth = Depends(device_auth_either)) -> DeviceAuth:
    """
    Require that the device is in 'claimed' status
    """
    if auth.device_status != "claimed":
        raise HTTPException(
            status_code=403,
            detail=f"device_not_claimed_status_{auth.device_status}"
        )
    return auth

def require_device_active(auth: DeviceAuth = Depends(device_auth_either)) -> DeviceAuth:
    """
    Require that the device is not suspended
    """
    if auth.device_status == "suspended":
        raise HTTPException(
            status_code=403,
            detail="device_suspended"
        )
    return auth
