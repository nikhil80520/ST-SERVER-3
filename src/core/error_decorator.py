"""
Centralized error handling decorator for API endpoints.
Eliminates code duplication and ensures consistent error responses.
"""
from functools import wraps
from fastapi import HTTPException, status
from typing import Callable, Any
import traceback
import logging

from src.core.errors import AppException, convert_to_http_exception

logger = logging.getLogger(__name__)


def handle_api_errors(endpoint_name: str):
    """
    Decorator for handling errors in API endpoints consistently.
    
    Features:
    - Catches all exceptions and converts them to proper HTTP responses
    - Logs errors with endpoint context
    - Maintains FastAPI's HTTPException handling
    - Converts custom AppException to HTTPException
    - Returns structured error responses
    
    Args:
        endpoint_name: Name of the endpoint for logging (e.g., "auth-signup", "story-create")
    
    Usage:
        @router.post("/signup")
        @handle_api_errors("auth-signup")
        async def signup(request: SignUpRequest):
            # Just business logic - decorator handles errors
            return await auth_service.create_user(request)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Re-raise FastAPI's HTTPException as-is
                raise
            except AppException as e:
                # Convert custom exceptions to HTTPException
                logger.error(f"[{endpoint_name}] AppException: {e.message}", exc_info=True)
                raise convert_to_http_exception(e)
            except Exception as e:
                # Log unexpected errors with full traceback
                logger.error(
                    f"[{endpoint_name}] Unexpected error: {str(e)}\n{traceback.format_exc()}"
                )
                
                # Return generic 500 error to client (don't expose internal details)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "message": "Internal server error",
                        "endpoint": endpoint_name,
                        "error_type": type(e).__name__
                    }
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except AppException as e:
                logger.error(f"[{endpoint_name}] AppException: {e.message}", exc_info=True)
                raise convert_to_http_exception(e)
            except Exception as e:
                logger.error(
                    f"[{endpoint_name}] Unexpected error: {str(e)}\n{traceback.format_exc()}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "message": "Internal server error",
                        "endpoint": endpoint_name,
                        "error_type": type(e).__name__
                    }
                )
        
        # Return appropriate wrapper based on whether function is async
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator
