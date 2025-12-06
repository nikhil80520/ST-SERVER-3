"""
Centralized dependency injection for FastAPI.
Separates authentication, authorization, and service dependencies.
"""
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from src.user.schema import AccountStatusInfo,User
from src.common_function.storage_s3_service import S3StorageService as StorageService
from src.user.account_status_service import account_status_service
from src.auth.service import auth_service
# HTTP Bearer security scheme
security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

# Singleton service instances
_storage_service_instance = None


def get_storage_service() -> StorageService:
    """Get shared StorageService instance."""
    global _storage_service_instance
    if _storage_service_instance is None:
        _storage_service_instance = StorageService()
    return _storage_service_instance


async def get_current_user_from_header(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    Extract and verify Firebase token from Authorization header.
    Returns User object with uid, email, name.
    Uses auth_service for token verification (with caching).
    """
    return await auth_service.verify_token_and_get_user(credentials.credentials)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(optional_security)
) -> Optional[User]:
    """
    Optional authentication - returns None if no token provided.
    """
    if credentials is None:
        return None
    try:
        return await auth_service.verify_token_and_get_user(credentials.credentials)
    except Exception:
        return None


async def get_account_status(
    user: User = Depends(get_current_user_from_header)
) -> AccountStatusInfo:
    """
    Get account status for authenticated user.
    
    Returns:
        AccountStatusInfo with current account status
    """
    return await account_status_service.get_account_status(user.uid)


async def require_active_account(
    user: User = Depends(get_current_user_from_header),
    account_status: AccountStatusInfo = Depends(get_account_status)
) -> User:
    """
    Require active account (can access content).
    Raises HTTPException if account cannot access content.
    
    Returns:
        User object if account is active
    """
    error = account_status_service.get_http_error_for_status(account_status, "access_content")
    if error:
        raise error
    return user


async def require_story_creation_access(
    user: User = Depends(get_current_user_from_header),
    account_status: AccountStatusInfo = Depends(get_account_status)
) -> User:
    """
    Require story creation access (paid or trial).
    Raises HTTPException if account cannot create stories.
    
    Returns:
        User object if account can create stories
    """
    error = account_status_service.get_http_error_for_status(account_status, "create_story")
    if error:
        raise error
    return user


async def get_user_with_status(
    user: User = Depends(get_current_user_from_header),
    account_status: AccountStatusInfo = Depends(get_account_status)
) -> tuple[User, AccountStatusInfo]:
    """
    Get both user and account status (no validation).
    Use when you want status info but don't want to block access.
    
    Returns:
        Tuple of (User, AccountStatusInfo)
    """
    return user, account_status
