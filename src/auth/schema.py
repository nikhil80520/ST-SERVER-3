"""
Authentication Schema Module
Contains all request and response models for authentication endpoints.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Dict, Any, Optional


# ===== AUTHENTICATION REQUEST SCHEMAS =====

class SignUpRequest(BaseModel):
    """Request model for user sign-up"""
    email: EmailStr
    password: str
    display_name: Optional[str] = None


class SignInRequest(BaseModel):
    """Request model for user sign-in"""
    email: EmailStr
    password: str


class TokenVerificationRequest(BaseModel):
    """Request model for token verification"""
    firebase_token: str


class RefreshTokenRequest(BaseModel):
    """Request model for refreshing Firebase token"""
    refresh_token: str


class PasswordResetRequest(BaseModel):
    """Request model for initiating password reset"""
    email: EmailStr


class ValidateOTPRequest(BaseModel):
    """Request model for validating OTP"""
    otp: str
    email: EmailStr


class ResetPasswordWithOTPRequest(BaseModel):
    """Request model for resetting password with OTP"""
    otp: str
    email: EmailStr
    new_password: str


class ChangePasswordRequest(BaseModel):
    """Request model for changing password"""
    firebase_token: str
    new_password: str


# ===== AUTHENTICATION RESPONSE SCHEMAS =====

class AuthenticationResponse(BaseModel):
    """Response model for authentication operations (sign-up, sign-in)"""
    success: bool
    message: str
    firebase_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    user_info: Optional[Dict[str, Any]] = None


class AuthResponse(BaseModel):
    """Response model for user registration and profile operations"""
    success: bool
    message: str
    user_id: str
    profile: Optional[Dict[str, Any]] = None


class TokenRefreshResponse(BaseModel):
    """Response model for token refresh operation"""
    success: bool
    message: str
    firebase_token: str
    refresh_token: str
    expires_in: int


class PasswordResetResponse(BaseModel):
    """Response model for password reset operations"""
    success: bool
    message: str


class OTPValidationResponse(BaseModel):
    """Response model for OTP validation"""
    success: bool
    message: str
    valid: bool
    otp_verified: bool
    next_step: Optional[str] = None
    email: Optional[str] = None


class TokenVerificationResponse(BaseModel):
    """Response model for token verification"""
    success: bool
    valid: bool
    user_info: Optional[Dict[str, Any]] = None
    has_profile: Optional[bool] = None
    profile: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SignOutResponse(BaseModel):
    """Response model for sign-out operation"""
    success: bool
    message: str


class DeleteProfileResponse(BaseModel):
    """Response model for profile deletion"""
    success: bool
    message: str
    user_id: str


# ===== LEGACY COMPATIBILITY =====

class TokenVerification(BaseModel):
    """Legacy model - kept for backward compatibility"""
    firebase_token: str