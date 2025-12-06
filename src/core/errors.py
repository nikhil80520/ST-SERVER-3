"""Centralized error handling and custom exceptions."""
from fastapi import HTTPException, status
from typing import Optional, Any, Dict


class AppException(Exception):
    """Base exception for application errors."""
    def __init__(self, message: str, status_code: int = 500, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppException):
    """Authentication related errors."""
    def __init__(self, message: str = "Authentication failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=401, details=details)


class AuthorizationError(AppException):
    """Authorization related errors."""
    def __init__(self, message: str = "Insufficient permissions", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=403, details=details)


class ValidationError(AppException):
    """Validation related errors."""
    def __init__(self, message: str = "Validation failed", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=400, details=details)


class NotFoundError(AppException):
    """Resource not found errors."""
    def __init__(self, message: str = "Resource not found", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=404, details=details)


class ConflictError(AppException):
    """Conflict errors (e.g., duplicate resources)."""
    def __init__(self, message: str = "Resource conflict", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=409, details=details)


class ServiceError(AppException):
    """External service errors."""
    def __init__(self, message: str = "External service error", details: Optional[Dict[str, Any]] = None):
        super().__init__(message, status_code=503, details=details)


def convert_to_http_exception(error: Exception) -> HTTPException:
    """Convert custom exceptions to FastAPI HTTPException."""
    if isinstance(error, AppException):
        return HTTPException(
            status_code=error.status_code,
            detail={
                "message": error.message,
                "details": error.details
            }
        )
    elif isinstance(error, HTTPException):
        return error
    else:
        # Generic server error
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": str(error)}
        )
