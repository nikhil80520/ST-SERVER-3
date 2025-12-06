"""
Authentication Routes Module
Contains only FastAPI route definitions that delegate to AuthService.
No business logic - all logic is in service.py.
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schema import (
    SignUpRequest,
    SignInRequest,
    TokenVerificationRequest,
    RefreshTokenRequest,
    PasswordResetRequest,
    ValidateOTPRequest,
    ResetPasswordWithOTPRequest,
    AuthenticationResponse,
    TokenRefreshResponse,
    PasswordResetResponse,
    OTPValidationResponse,
    SignOutResponse,
    AuthResponse,
    TokenVerificationResponse,
)
from src.user.schema import UserRegistration
from src.auth.service import AuthService, UserAuthService
from src.user.service import UserService
from src.user.service_pg import UserServicePostgreSQL
from src.db import get_session


router = APIRouter(prefix="/auth", tags=["authentication"])


# ===== DEPENDENCY INJECTION =====

def get_user_service():
    """Get UserService instance"""
    return UserService()


def get_user_service_pg():
    """Get UserServicePostgreSQL instance"""
    return UserServicePostgreSQL()


def get_auth_service():
    """Get AuthService instance"""
    return AuthService()


def get_user_auth_service(
    user_service: UserService = Depends(get_user_service),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Get UserAuthService instance with dependencies"""
    return UserAuthService(
        user_service_firebase=user_service,
        user_service_pg=None,
        auth_service=auth_service
    )


def add_cors_headers(response: Response):
    """Add CORS headers to response"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"


# ===== AUTHENTICATION ENDPOINTS =====

@router.post("/signup", response_model=AuthenticationResponse)
async def sign_up_user(
    request: SignUpRequest, 
    response: Response,
    db: AsyncSession = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Create a new Firebase user account and initialize PostgreSQL record.
    
    This endpoint:
    - Creates a Firebase Auth user
    - Creates a minimal PostgreSQL user record
    - Sends a welcome email
    - Returns Firebase authentication tokens
    """
    add_cors_headers(response)
    return await auth_service.sign_up_user(request, db)


@router.post("/signin", response_model=AuthenticationResponse)
async def sign_in_user(
    request: SignInRequest, 
    response: Response,
    db: AsyncSession = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
    user_service_pg: UserServicePostgreSQL = Depends(get_user_service_pg)
):
    """
    Sign in an existing Firebase user and load PostgreSQL profile.
    
    This endpoint:
    - Authenticates user with Firebase
    - Loads user profile from PostgreSQL
    - Auto-creates PostgreSQL record if missing
    - Sends login notification email
    - Returns Firebase tokens and user info
    """
    add_cors_headers(response)
    return await auth_service.sign_in_user(request, db, user_service_pg)


@router.post("/refresh-token", response_model=TokenRefreshResponse)
async def refresh_firebase_token(
    request: RefreshTokenRequest, 
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh Firebase ID token using refresh token.
    
    This endpoint:
    - Validates the refresh token
    - Generates new Firebase ID token
    - Returns new tokens with expiration time
    """
    add_cors_headers(response)
    return await auth_service.refresh_token(request)


@router.post("/password-reset", response_model=PasswordResetResponse)
async def request_password_reset(
    request: PasswordResetRequest, 
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Send password reset email with OTP.
    
    This endpoint:
    - Generates a 6-digit OTP
    - Sends OTP via email
    - Does not reveal if email exists (security)
    """
    add_cors_headers(response)
    return await auth_service.request_password_reset(request)


@router.post("/validate-otp", response_model=OTPValidationResponse)
async def validate_reset_otp(
    request: ValidateOTPRequest, 
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Validate a password reset OTP.
    
    This endpoint:
    - Checks if OTP is valid and not expired
    - Returns validation status
    - Instructs next step if valid
    """
    add_cors_headers(response)
    return await auth_service.validate_otp(request)


@router.post("/reset-password", response_model=PasswordResetResponse)
async def reset_password_with_otp(
    request: ResetPasswordWithOTPRequest, 
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Reset password using valid OTP.
    
    This endpoint:
    - Validates OTP
    - Updates Firebase user password
    - Invalidates the used OTP
    """
    add_cors_headers(response)
    return await auth_service.reset_password_with_otp(request)


@router.post("/signout", response_model=SignOutResponse)
async def sign_out_user(
    request: TokenVerificationRequest, 
    response: Response,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Sign out user (revoke refresh tokens).
    
    This endpoint:
    - Verifies user identity
    - Revokes all refresh tokens for the user
    - Forces re-authentication on next use
    """
    add_cors_headers(response)
    return await auth_service.sign_out_user(request.firebase_token)


# ===== USER REGISTRATION & PROFILE ENDPOINTS =====

@router.post("/register", response_model=AuthResponse)
async def register_user(
    request: UserRegistration, 
    response: Response,
    db: AsyncSession = Depends(get_session),
    auth_service: AuthService = Depends(get_auth_service),
    user_service_pg: UserServicePostgreSQL = Depends(get_user_service_pg)
):
    """
    Register a new user with parent and child profiles using PostgreSQL.
    
    This endpoint:
    - Verifies Firebase authentication
    - Creates or updates parent profile
    - Creates first child profile if needed
    - Returns complete user profile
    """
    add_cors_headers(response)
    
    user_auth_service = UserAuthService(
        user_service_firebase=None,
        user_service_pg=user_service_pg,
        auth_service=auth_service
    )
    
    return await user_auth_service.register_user_pg(request, db)


@router.delete("/profile/{firebase_token}")
async def delete_user_profile(
    firebase_token: str, 
    response: Response, 
    user_auth_service: UserAuthService = Depends(get_user_auth_service)
):
    """
    Delete user profile and associated data.
    
    This endpoint:
    - Verifies user identity
    - Deletes all user data from database
    - Returns confirmation
    """
    add_cors_headers(response)
    return await user_auth_service.delete_user_profile(firebase_token)


@router.post("/verify-token", response_model=TokenVerificationResponse)
async def verify_token_endpoint(
    token_request: TokenVerificationRequest,
    response: Response, 
    user_auth_service: UserAuthService = Depends(get_user_auth_service)
):
    """
    Verify Firebase token and return user info.
    
    This endpoint:
    - Validates Firebase ID token
    - Returns user information
    - Includes profile data if available
    """
    add_cors_headers(response)
    
    print(f"🔍 verify-token endpoint called")
    print(f"📝 Received token_request: {token_request}")
    print(f"📝 Token (first 20 chars): {token_request.firebase_token[:20] if token_request.firebase_token else 'None'}...")
    
    return await user_auth_service.verify_token_endpoint(token_request.firebase_token)


# ===== OPTIONS HANDLERS FOR CORS =====

@router.options("/signup")
@router.options("/signin") 
@router.options("/refresh-token")
@router.options("/password-reset")
@router.options("/validate-otp")
@router.options("/reset-password")
@router.options("/signout")
@router.options("/register")
@router.options("/profile/{firebase_token}")
@router.options("/verify-token")
async def auth_options(response: Response):
    """Handle preflight OPTIONS requests for auth endpoints"""
    add_cors_headers(response)
    return {"message": "OK"}
