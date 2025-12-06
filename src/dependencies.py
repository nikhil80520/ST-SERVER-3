# ===== app/dependencies.py - Use core/dependencies.py instead =====
# This file is kept for backward compatibility
# New code should import from app.core.dependencies

from src.core.dependencies import (
    get_storage_service,
    get_current_user_from_header,
    get_optional_current_user,
    get_account_status,
    require_active_account,
    require_story_creation_access,
    get_user_with_status,
    security,
    optional_security
)

# Alias for backward compatibility
get_current_user = get_current_user_from_header

# Legacy function names for backward compatibility
async def verify_firebase_token(token: str) -> str:
    """Legacy function - use auth_service.verify_token instead"""
    from src.auth.service import auth_service
    return await auth_service.verify_token(token)

async def verify_firebase_token_from_header(credentials):
    """Legacy function - use get_current_user_from_header instead"""
    return await get_current_user_from_header(credentials)

__all__ = [
    'get_storage_service',
    'get_current_user_from_header',
    'get_current_user',
    'get_optional_current_user',
    'get_account_status',
    'require_active_account',
    'require_story_creation_access',
    'get_user_with_status',
    'security',
    'optional_security',
    'verify_firebase_token',
    'verify_firebase_token_from_header'
]
