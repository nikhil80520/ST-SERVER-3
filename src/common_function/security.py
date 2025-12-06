"""
Security utilities for IoT Device Management
HMAC verification, JWT minting, and crypto operations
"""

import hmac
import hashlib
import time
import secrets
import jwt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from pathlib import Path
from fastapi import HTTPException
from cryptography.fernet import Fernet
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from src.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Initialize password hasher for device secrets
ph = PasswordHasher()

# Initialize encryption for device secrets (if we store them encrypted)
def get_fernet_key() -> bytes:
    """Get or create Fernet encryption key"""
    return settings.device_secret_key.encode().ljust(32, b'0')[:32]

def get_fernet() -> Fernet:
    """Get Fernet cipher for encrypting device secrets"""
    key = get_fernet_key()
    return Fernet(Fernet.generate_key() if len(key) != 32 else key)

def verify_hmac(
    device_secret: bytes,
    method: str,
    path: str,
    body: bytes,
    timestamp: int,
    signature_hex: str,
    tolerance_seconds: int = None
) -> None:
    """
    Verify HMAC signature from device
    
    Args:
        device_secret: Raw device secret bytes
        method: HTTP method (GET, POST, etc.)
        path: Request path
        body: Request body bytes
        timestamp: Unix timestamp from request
        signature_hex: HMAC signature in hex format
        tolerance_seconds: Max time skew allowed
    
    Raises:
        HTTPException: If verification fails
    """
    if tolerance_seconds is None:
        tolerance_seconds = settings.hmac_tolerance_seconds
    
    # Check timestamp skew
    now = int(time.time())
    if abs(now - timestamp) > tolerance_seconds:
        logger.warning(f"HMAC timestamp skew: {abs(now - timestamp)}s > {tolerance_seconds}s")
        raise HTTPException(status_code=401, detail="timestamp_skew")
    
    # Build message for HMAC
    message = f"{method.upper()}|{path}|".encode() + body + f"|{timestamp}".encode()
    
    # Calculate expected HMAC
    expected_hmac = hmac.new(device_secret, message, hashlib.sha256).hexdigest()
    
    # Compare signatures (constant time)
    if not hmac.compare_digest(expected_hmac, signature_hex):
        logger.warning(f"HMAC verification failed for path: {path}")
        raise HTTPException(status_code=401, detail="invalid_signature")
    
    logger.debug(f"HMAC verified successfully for {method} {path}")

def hash_device_secret(secret: str) -> str:
    """Hash device secret using Argon2"""
    return ph.hash(secret)

def verify_device_secret(secret: str, hashed: str) -> bool:
    """Verify device secret against Argon2 hash"""
    try:
        ph.verify(hashed, secret)
        return True
    except VerifyMismatchError:
        return False

def encrypt_device_secret(secret: str) -> bytes:
    """Encrypt device secret for storage"""
    f = get_fernet()
    return f.encrypt(secret.encode())

def decrypt_device_secret(encrypted_secret: bytes) -> str:
    """Decrypt device secret from storage"""
    f = get_fernet()
    return f.decrypt(encrypted_secret).decode()

def load_jwt_keys():
    """Load JWT public/private keys"""
    try:
        # App JWT keys (for user authentication)
        app_private_key = None
        app_public_key = None
        
        if Path(settings.jwt_private_key_path).exists():
            app_private_key = Path(settings.jwt_private_key_path).read_text()
        if Path(settings.jwt_public_key_path).exists():
            app_public_key = Path(settings.jwt_public_key_path).read_text()
        
        # Device JWT keys
        device_private_key = None
        device_public_key = None
        
        if Path(settings.device_jwt_private_key_path).exists():
            device_private_key = Path(settings.device_jwt_private_key_path).read_text()
        if Path(settings.device_jwt_public_key_path).exists():
            device_public_key = Path(settings.device_jwt_public_key_path).read_text()
        
        return {
            "app_private": app_private_key,
            "app_public": app_public_key,
            "device_private": device_private_key,
            "device_public": device_public_key
        }
    except Exception as e:
        logger.warning(f"Could not load JWT keys: {e}")
        return {
            "app_private": None,
            "app_public": None,
            "device_private": None,
            "device_public": None
        }

# Load keys at module level
JWT_KEYS = load_jwt_keys()

def mint_device_jwt(
    device_id: str,
    ttl_seconds: int = None,
    audience: str = "device-api"
) -> str:
    """
    Mint a JWT for device authentication
    
    Args:
        device_id: Device identifier
        ttl_seconds: Token lifetime
        audience: JWT audience
    
    Returns:
        JWT token string
    """
    if ttl_seconds is None:
        ttl_seconds = settings.device_jwt_ttl_seconds
    
    now = datetime.now(timezone.utc)
    payload = {
        "sub": device_id,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "type": "device"
    }
    
    # Use device private key if available, otherwise use HS256 with secret
    if JWT_KEYS["device_private"]:
        return jwt.encode(payload, JWT_KEYS["device_private"], algorithm="RS256")
    else:
        return jwt.encode(payload, settings.device_secret_key, algorithm="HS256")

def verify_device_jwt(token: str, audience: str = "device-api") -> Dict[str, Any]:
    """
    Verify and decode device JWT
    
    Args:
        token: JWT token string
        audience: Expected audience
    
    Returns:
        JWT payload dict
    
    Raises:
        HTTPException: If verification fails
    """
    try:
        # Use device public key if available, otherwise use HS256 with secret
        if JWT_KEYS["device_public"]:
            payload = jwt.decode(
                token,
                JWT_KEYS["device_public"],
                algorithms=["RS256"],
                audience=audience
            )
        else:
            payload = jwt.decode(
                token,
                settings.device_secret_key,
                algorithms=["HS256"],
                audience=audience
            )
        
        if payload.get("type") != "device":
            raise HTTPException(status_code=401, detail="invalid_token_type")
        
        return payload
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token_expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"invalid_token: {str(e)}")

def generate_claim_token() -> str:
    """Generate a secure claim token"""
    return secrets.token_urlsafe(24)

def hash_public_ip(ip_address: str) -> str:
    """Hash public IP address for privacy"""
    return hashlib.sha256(ip_address.encode()).hexdigest()

def generate_device_secret() -> str:
    """Generate a secure device secret"""
    return secrets.token_urlsafe(32)

def is_strong_device_secret(secret: str) -> bool:
    """Check if device secret meets strength requirements"""
    return len(secret) >= 24 and any(c.isalpha() for c in secret) and any(c.isdigit() for c in secret)
