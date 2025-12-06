"""
Authentication Service Module
Contains all business logic for authentication, user management, and Firebase operations.
"""
import httpx
import time
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from fastapi import HTTPException
from firebase_admin import auth
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schema import (
    AuthenticationResponse,
    AuthResponse,
    TokenRefreshResponse,
    PasswordResetResponse,
    OTPValidationResponse,
    TokenVerificationResponse,
    SignOutResponse,
    DeleteProfileResponse,
    SignUpRequest,
    SignInRequest,
    RefreshTokenRequest,
    PasswordResetRequest,
    ValidateOTPRequest,
    ResetPasswordWithOTPRequest,
)
from src.user.schema import UserRegistration, UserProfileUpdate, User
from src.user.service import UserService
from src.user.service_pg import UserServicePostgreSQL
from src.common_function.ses_email_service import email_service
from src.common_function.password_reset_service import password_reset_service
from src.core.config import settings


class AuthService:
    """
    Service class for all authentication operations.
    Handles Firebase authentication, token management, and user operations.
    """
    
    def __init__(self):
        # Token verification cache (short TTL to balance security and performance)
        self._token_cache: Dict[str, Dict[str, any]] = {}
        self._token_cache_ttl = 60  # 1 minute cache for token verification
    
    # ===== TOKEN VERIFICATION =====
    
    async def verify_token(self, token: str) -> str:
        """
        Verify Firebase ID token and return Firebase user ID (firebase_user_id).
        WITH CACHING: 1-minute TTL to reduce Firebase Auth API calls.
        
        Args:
            token: Firebase ID token
            
        Returns:
            Firebase User ID (uid) - use this to lookup user in database by firebase_user_id
            
        Raises:
            HTTPException: If token is invalid
        """
        # Local debug bypass: only enable when both debug and explicit allow flag are set
        if getattr(settings, 'debug', False) and getattr(settings, 'allow_local_auth_bypass', False):
            print("⚠️ DEBUG + ALLOW_LOCAL_AUTH_BYPASS: bypassing Firebase token verification and returning debug-user")
            return "debug-user"

        # Check cache first
        if token in self._token_cache:
            cached_data = self._token_cache[token]
            cache_age = time.time() - cached_data['timestamp']
            if cache_age < self._token_cache_ttl:
                return cached_data['firebase_uid']
            else:
                del self._token_cache[token]

        try:
            # Verify token with clock skew tolerance (allow 10 seconds)
            decoded_token = auth.verify_id_token(token, check_revoked=False, clock_skew_seconds=10)
            firebase_uid = decoded_token.get('uid') or decoded_token.get('user_id') or decoded_token.get('sub')
            
            # Cache the result
            self._token_cache[token] = {
                'firebase_uid': firebase_uid,
                'timestamp': time.time()
            }
            
            # Clean old cache entries (simple cleanup - keep cache size manageable)
            if len(self._token_cache) > 1000:
                current_time = time.time()
                expired_tokens = [
                    t for t, data in self._token_cache.items()
                    if current_time - data['timestamp'] > self._token_cache_ttl
                ]
                for t in expired_tokens:
                    del self._token_cache[t]
            
            return firebase_uid
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {str(e)}")
    
    async def verify_token_and_get_user(self, token: str) -> User:
        """
        Verify Firebase token and return User object.
        
        Args:
            token: Firebase ID token
            
        Returns:
            User object with uid, email, name
            
        Raises:
            HTTPException: If token is invalid
        """
        # Local debug bypass
        if getattr(settings, 'debug', False) and getattr(settings, 'allow_local_auth_bypass', False):
            print("⚠️ DEBUG + ALLOW_LOCAL_AUTH_BYPASS: bypassing Firebase token verification and returning debug user")
            return User(
                uid='debug-user',
                email='debug@example.com',
                name='Debug User',
                token={}
            )

        try:
            # Verify token with clock skew tolerance (allow 10 seconds for clock drift)
            decoded_token = auth.verify_id_token(token, check_revoked=False, clock_skew_seconds=10)
            return User(
                uid=decoded_token.get('uid') or decoded_token.get('user_id') or decoded_token.get('sub'),
                email=decoded_token.get('email'),
                name=decoded_token.get('name'),
                token=decoded_token
            )
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {str(e)}")

    # ===== USER SIGN UP =====
    
    async def sign_up_user(
        self, 
        request: SignUpRequest, 
        db: AsyncSession
    ) -> AuthenticationResponse:
        """
        Create a new Firebase user account and initialize PostgreSQL record.
        
        Args:
            request: Sign-up request containing email, password, display_name
            db: Database session
            
        Returns:
            AuthenticationResponse with Firebase token and user info
            
        Raises:
            HTTPException: If sign-up fails
        """
        try:
            print(f"🔐 Creating new Firebase user: {request.email}")
            
            # Create user with Firebase Admin SDK
            user_record = auth.create_user(
                email=request.email,
                password=request.password,
                display_name=request.display_name,
                email_verified=False
            )
            
            print(f"✅ Firebase user created: {user_record.uid}")
            
            # Create minimal user record in PostgreSQL
            from src.db.models import User
            try:
                # Parse display name into first/last name
                name_parts = (user_record.display_name or "").split(maxsplit=1)
                first_name = name_parts[0] if len(name_parts) > 0 else None
                last_name = name_parts[1] if len(name_parts) > 1 else None
                
                # Create user record
                db_user = User(
                    firebase_user_id=user_record.uid,
                    email=user_record.email,
                    first_name=first_name,
                    last_name=last_name,
                    account_status="trial_active",
                    last_active=datetime.utcnow()
                )
                
                db.add(db_user)
                await db.commit()
                await db.refresh(db_user)
                
                print(f"✅ PostgreSQL user record created: user_id={db_user.user_id}, firebase_user_id={user_record.uid}")
            except Exception as e:
                await db.rollback()
                print(f"⚠️ Failed to create PostgreSQL user record: {str(e)}")
                # Continue - Firebase user is created, PostgreSQL record can be created later via /users/register
            
            # Send welcome email
            try:
                await email_service.send_welcome_email(
                    user_email=user_record.email,
                    user_name=user_record.display_name
                )
                print(f"📧 Welcome email sent to {user_record.email}")
            except Exception as e:
                print(f"⚠️ Failed to send welcome email: {str(e)}")
            
            # Generate custom token for immediate sign-in
            custom_token = auth.create_custom_token(user_record.uid)
            
            # Exchange custom token for ID token using Firebase REST API
            firebase_token, refresh_token, expires_in = await self._exchange_custom_token_for_id_token(custom_token)
            
            return AuthenticationResponse(
                success=True,
                message="User account created successfully",
                firebase_token=firebase_token,
                refresh_token=refresh_token,
                expires_in=expires_in,
                user_info={
                    "uid": user_record.uid,
                    "email": user_record.email,
                    "display_name": user_record.display_name,
                    "email_verified": user_record.email_verified,
                    "created_at": user_record.user_metadata.creation_timestamp
                }
            )
            
        except auth.EmailAlreadyExistsError:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        except auth.WeakPasswordError:
            raise HTTPException(status_code=400, detail="Password is too weak")
        except auth.InvalidEmailError:
            raise HTTPException(status_code=400, detail="Invalid email address")
        except Exception as e:
            print(f"❌ Sign-up error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create user account: {str(e)}")
    
    # ===== USER SIGN IN =====
    
    async def sign_in_user(
        self, 
        request: SignInRequest, 
        db: AsyncSession,
        user_service_pg: UserServicePostgreSQL
    ) -> AuthenticationResponse:
        """
        Sign in an existing Firebase user and load PostgreSQL profile.
        
        Args:
            request: Sign-in request containing email and password
            db: Database session
            user_service_pg: PostgreSQL user service instance
            
        Returns:
            AuthenticationResponse with Firebase token and user info
            
        Raises:
            HTTPException: If sign-in fails
        """
        try:
            print(f"🔐 Signing in Firebase user: {request.email}")
            
            # Use Firebase REST API to sign in (Admin SDK doesn't have direct sign-in)
            firebase_token, refresh_token, expires_in, user_info = await self._sign_in_with_email_password(
                request.email, 
                request.password
            )
            
            firebase_user_id = user_info.get('localId')
            print(f"✅ User signed in successfully: firebase_user_id={firebase_user_id}")
            
            # Get user profile from PostgreSQL database using firebase_user_id
            try:
                user_profile = await user_service_pg.get_user_profile(db, firebase_user_id)
                if user_profile:
                    # Merge Firebase user info with database profile
                    user_info['profile'] = user_profile
                    user_info['user_id'] = user_profile.get('user_id')  # Add integer user_id
                    print(f"📋 User profile loaded from PostgreSQL: user_id={user_profile.get('user_id')}")
                else:
                    # User exists in Firebase Auth but not in PostgreSQL - create entry automatically
                    print(f"⚠️ No profile found in PostgreSQL for firebase_user_id={firebase_user_id}")
                    print(f"🔧 Auto-creating PostgreSQL user record for existing Firebase user...")
                    
                    from src.db.models import User
                    try:
                        # Parse display name into first/last name
                        display_name = user_info.get('displayName') or user_info.get('email', '').split('@')[0]
                        name_parts = display_name.split(maxsplit=1)
                        first_name = name_parts[0] if len(name_parts) > 0 else None
                        last_name = name_parts[1] if len(name_parts) > 1 else None
                        
                        # Create minimal user record
                        db_user = User(
                            firebase_user_id=firebase_user_id,
                            email=user_info.get('email'),
                            first_name=first_name,
                            last_name=last_name,
                            account_status="trial_active",
                            last_active=datetime.utcnow()
                        )
                        
                        db.add(db_user)
                        await db.commit()
                        await db.refresh(db_user)
                        
                        print(f"✅ PostgreSQL user record auto-created: user_id={db_user.user_id}, firebase_user_id={firebase_user_id}")
                        
                        # Add user_id to response
                        user_info['user_id'] = db_user.user_id
                        user_info['profile'] = {
                            'user_id': db_user.user_id,
                            'firebase_user_id': db_user.firebase_user_id,
                            'email': db_user.email,
                            'first_name': db_user.first_name,
                            'last_name': db_user.last_name,
                            'account_status': db_user.account_status,
                            'auto_created': True  # Flag to indicate this was auto-created
                        }
                    except Exception as create_error:
                        await db.rollback()
                        print(f"⚠️ Failed to auto-create PostgreSQL user record: {str(create_error)}")
                        # Continue with Firebase data only
            except Exception as e:
                print(f"⚠️ Failed to load user profile from PostgreSQL: {str(e)}")
                import traceback
                print(f"📋 Traceback: {traceback.format_exc()}")
                # Continue with Firebase data only
            
            # Send login notification email
            try:
                await email_service.send_login_notification(
                    user_email=request.email,
                    user_name=user_info.get('displayName'),
                    login_time=datetime.utcnow()
                )
                print(f"📧 Login notification sent to {request.email}")
            except Exception as e:
                print(f"⚠️ Failed to send login notification: {str(e)}")
            
            return AuthenticationResponse(
                success=True,
                message="User signed in successfully",
                firebase_token=firebase_token,
                refresh_token=refresh_token,
                expires_in=int(expires_in),
                user_info=user_info
            )
            
        except Exception as e:
            print(f"❌ Sign-in error: {str(e)}")
            error_message = str(e)
            
            # Handle specific Firebase errors
            if "INVALID_EMAIL" in error_message:
                raise HTTPException(status_code=400, detail="Invalid email address")
            elif "INVALID_PASSWORD" in error_message or "INVALID_LOGIN_CREDENTIALS" in error_message:
                raise HTTPException(status_code=401, detail="Invalid email or password")
            elif "USER_DISABLED" in error_message:
                raise HTTPException(status_code=403, detail="User account has been disabled")
            elif "TOO_MANY_ATTEMPTS" in error_message:
                raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again later")
            else:
                raise HTTPException(status_code=500, detail="Sign-in failed")
    
    # ===== TOKEN REFRESH =====
    
    async def refresh_token(self, request: RefreshTokenRequest) -> TokenRefreshResponse:
        """
        Refresh Firebase ID token using refresh token.
        
        Args:
            request: Refresh token request
            
        Returns:
            TokenRefreshResponse with new Firebase token
            
        Raises:
            HTTPException: If token refresh fails
        """
        try:
            refresh_token = request.refresh_token
            if not refresh_token:
                raise HTTPException(status_code=400, detail="Refresh token is required")
            
            # Log a short prefix of the refresh token for debugging (do not log full token in prod)
            try:
                token_preview = refresh_token[:32]
            except Exception:
                token_preview = str(refresh_token)[:32]
            print(f"🔄 Refreshing Firebase token - token_preview={token_preview} (len={len(refresh_token)})")
            
            # Use Firebase REST API to refresh token
            new_firebase_token, new_refresh_token, expires_in = await self._refresh_firebase_id_token(refresh_token)
            
            return TokenRefreshResponse(
                success=True,
                message="Token refreshed successfully",
                firebase_token=new_firebase_token,
                refresh_token=new_refresh_token,
                expires_in=int(expires_in)
            )
            
        except Exception as e:
            # Log full error and return Firebase's message to client so it can reauthenticate if needed
            err_str = str(e)
            print(f"❌ Token refresh error: {err_str}")
            # If Firebase indicated token expiration, return that detail so client can re-login
            # Do not leak sensitive tokens - err_str here is an error message from Firebase endpoint
            raise HTTPException(status_code=401, detail=err_str)
    
    # ===== PASSWORD RESET =====
    
    async def request_password_reset(self, request: PasswordResetRequest) -> PasswordResetResponse:
        """
        Send password reset email with OTP.
        
        Args:
            request: Password reset request
            
        Returns:
            PasswordResetResponse
        """
        try:
            print(f"📧 Initiating password reset for: {request.email}")
            
            # Use our custom password reset service
            result = await password_reset_service.initiate_password_reset(request.email)
            
            return PasswordResetResponse(
                success=result["success"],
                message=result["message"]
            )
            
        except Exception as e:
            print(f"❌ Password reset error: {str(e)}")
            # Don't reveal if email exists or not for security
            return PasswordResetResponse(
                success=True,
                message="If an account with this email exists, you will receive a 6-digit verification code."
            )
    
    async def validate_otp(self, request: ValidateOTPRequest) -> OTPValidationResponse:
        """
        Validate a password reset OTP.
        
        Args:
            request: OTP validation request
            
        Returns:
            OTPValidationResponse
        """
        try:
            print(f"🔍 Validating reset OTP for: {request.email}")
            
            result = await password_reset_service.validate_otp(
                otp=request.otp,
                email=request.email
            )
            
            return OTPValidationResponse(
                success=result["valid"],
                message=result["message"],
                valid=result["valid"],
                otp_verified=result["valid"],
                next_step="call_reset_password_endpoint" if result["valid"] else None,
                email=request.email if result["valid"] else None
            )
            
        except Exception as e:
            print(f"❌ OTP validation error: {str(e)}")
            return OTPValidationResponse(
                success=False,
                message="Unable to validate verification code",
                valid=False,
                otp_verified=False
            )
    
    async def reset_password_with_otp(self, request: ResetPasswordWithOTPRequest) -> PasswordResetResponse:
        """
        Reset password using valid OTP.
        
        Args:
            request: Reset password request
            
        Returns:
            PasswordResetResponse
        """
        try:
            print(f"🔐 Resetting password for: {request.email}")
            
            result = await password_reset_service.reset_password(
                otp=request.otp,
                email=request.email,
                new_password=request.new_password
            )
            
            return PasswordResetResponse(
                success=result["success"],
                message=result["message"]
            )
            
        except Exception as e:
            print(f"❌ Password reset error: {str(e)}")
            return PasswordResetResponse(
                success=False,
                message="Unable to reset password. Please try again or request a new verification code."
            )
    
    # ===== SIGN OUT =====
    
    async def sign_out_user(self, firebase_token: str) -> SignOutResponse:
        """
        Sign out user (revoke refresh tokens).
        
        Args:
            firebase_token: Firebase ID token
            
        Returns:
            SignOutResponse
            
        Raises:
            HTTPException: If sign-out fails
        """
        try:
            # Verify token and get user ID
            decoded_token = auth.verify_id_token(firebase_token)
            user_id = decoded_token['uid']
            
            print(f"👋 Signing out user: {user_id}")
            
            # Revoke all refresh tokens for this user
            auth.revoke_refresh_tokens(user_id)
            
            return SignOutResponse(
                success=True,
                message="User signed out successfully"
            )
            
        except auth.InvalidIdTokenError:
            raise HTTPException(status_code=401, detail="Invalid Firebase token")
        except Exception as e:
            print(f"❌ Sign-out error: {str(e)}")
            raise HTTPException(status_code=500, detail="Failed to sign out user")
    
    # ===== FIREBASE REST API HELPER METHODS =====
    
    async def _sign_in_with_email_password(
        self, 
        email: str, 
        password: str
    ) -> Tuple[str, str, str, Dict[str, Any]]:
        """
        Sign in user using Firebase REST API.
        
        Returns:
            Tuple of (firebase_token, refresh_token, expires_in, user_info)
        """
        try:
            # You'll need to get your Firebase Web API Key from Firebase Console
            # For now, we'll get it from settings (you should add this to your .env)
            api_key = getattr(settings, 'firebase_web_api_key', None)
            
            if not api_key:
                raise Exception("Firebase Web API Key not configured. Add FIREBASE_WEB_API_KEY to your .env file")
            
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
            
            payload = {
                "email": email,
                "password": password,
                "returnSecureToken": True
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                
                if response.status_code != 200:
                    error_data = response.json()
                    error_message = error_data.get('error', {}).get('message', 'Unknown error')
                    raise Exception(error_message)
                
                data = response.json()
                
                return (
                    data['idToken'],
                    data['refreshToken'], 
                    data['expiresIn'],
                    {
                        'localId': data['localId'],
                        'email': data['email'],
                        'displayName': data.get('displayName'),
                        'photoUrl': data.get('photoUrl'),
                        'emailVerified': data.get('emailVerified', False)
                    }
                )
                
        except Exception as e:
            raise e

    async def _exchange_custom_token_for_id_token(
        self, 
        custom_token: bytes
    ) -> Tuple[str, str, int]:
        """
        Exchange custom token for ID token using Firebase REST API.
        
        Returns:
            Tuple of (firebase_token, refresh_token, expires_in)
        """
        try:
            api_key = getattr(settings, 'firebase_web_api_key', None)
            
            if not api_key:
                raise Exception("Firebase Web API Key not configured")
            
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={api_key}"
            
            payload = {
                "token": custom_token.decode('utf-8'),
                "returnSecureToken": True
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload)
                
                if response.status_code != 200:
                    error_data = response.json()
                    raise Exception(error_data.get('error', {}).get('message', 'Token exchange failed'))
                
                data = response.json()
                
                return data['idToken'], data['refreshToken'], int(data['expiresIn'])
                
        except Exception as e:
            raise e

    async def _refresh_firebase_id_token(self, refresh_token: str) -> Tuple[str, str, int]:
        """
        Refresh ID token using refresh token.
        
        Returns:
            Tuple of (new_firebase_token, new_refresh_token, expires_in)
        """
        try:
            api_key = getattr(settings, 'firebase_web_api_key', None)
            
            if not api_key:
                raise Exception("Firebase Web API Key not configured")
            
            url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
            
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=payload)
                
                # Debug: log status and body when refresh fails to capture Firebase's error message
                if response.status_code != 200:
                    try:
                        body_text = response.text
                    except Exception:
                        body_text = '<unreadable response body>'
                    print(f"❌ Firebase refresh API returned status={response.status_code} body={body_text}")
                    try:
                        error_data = response.json()
                        # Firebase returns different shapes; try common locations
                        err_msg = error_data.get('error', {}).get('error_description') or error_data.get('error', {}).get('message') or error_data.get('error_description') or str(error_data)
                    except Exception:
                        err_msg = body_text
                    raise Exception(f"Token refresh failed: {err_msg}")
                
                data = response.json()
                
                return data['id_token'], data['refresh_token'], int(data['expires_in'])
                
        except Exception as e:
            raise e


class UserAuthService:
    """
    Service class for user registration and profile management.
    Handles user profile operations with Firebase and PostgreSQL.
    """
    
    def __init__(
        self, 
        user_service_firebase: UserService = None, 
        user_service_pg: UserServicePostgreSQL = None, 
        auth_service: AuthService = None
    ):
        self.user_service = user_service_firebase  # Legacy Firebase service
        self.user_service_pg = user_service_pg  # New PostgreSQL service
        self.auth_service = auth_service
    
    # ===== USER REGISTRATION =====
    
    async def register_user(self, request: UserRegistration) -> AuthResponse:
        """
        Register a new user with parent and child profiles (LEGACY - uses Firebase).
        
        Args:
            request: User registration request
            
        Returns:
            AuthResponse with user profile
            
        Raises:
            HTTPException: If registration fails
        """
        try:
            # Verify Firebase token
            user_id = await self.auth_service.verify_token(request.firebase_token)
            print(f"✅ Firebase token verified - User ID: {user_id}")
            
            # Check if user already exists
            existing_profile = await self.user_service.get_user_profile(user_id)
            if existing_profile:
                print(f"✅ User {user_id} already has profile, returning existing data")
                return AuthResponse(
                    success=True,
                    message="User profile found. Welcome back!",
                    user_id=user_id,
                    profile=existing_profile
                )
            
            # Create user profile
            profile = await self.user_service.create_user_profile(
                user_id=user_id,
                parent=request.parent,
                child=request.child,
                system_prompt=request.system_prompt,
                child_image_base64=request.child_image_base64
            )
            
            return AuthResponse(
                success=True,
                message="User profile created successfully",
                user_id=user_id,
                profile=profile
            )
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Registration error details: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    
    async def register_user_pg(
        self, 
        request: UserRegistration, 
        db: AsyncSession
    ) -> AuthResponse:
        """
        Register a new user with parent and child profiles using PostgreSQL.
        
        Args:
            request: User registration request
            db: Database session
            
        Returns:
            AuthResponse with user profile
            
        Raises:
            HTTPException: If registration fails
        """
        try:
            # Verify Firebase token to get firebase_user_id
            firebase_user_id = await self.auth_service.verify_token(request.firebase_token)
            print(f"✅ Firebase token verified - Firebase User ID: {firebase_user_id}")
            
            # Check if user already exists in PostgreSQL by firebase_user_id
            existing_user = await self.user_service_pg.get_user_by_firebase_id(db, firebase_user_id)
            if existing_user:
                print(f"✅ User {firebase_user_id} already exists in PostgreSQL (user_id={existing_user.user_id})")
                
                # Check if user has children - if not, this is first-time registration
                if existing_user.children_count == 0:
                    print(f"🔧 User has no children yet - completing registration by adding first child")
                    
                    # Update parent info if provided
                    if request.parent:
                        name_parts = (request.parent.name or "").split(maxsplit=1)
                        existing_user.first_name = name_parts[0] if len(name_parts) > 0 else existing_user.first_name
                        existing_user.last_name = name_parts[1] if len(name_parts) > 1 else existing_user.last_name
                        existing_user.email = request.parent.email or existing_user.email
                        existing_user.phone_number = request.parent.phone_number
                        existing_user.avatar_seed = getattr(request.parent, 'avatar_seed', existing_user.avatar_seed)
                        existing_user.avatar_style = getattr(request.parent, 'avatar_style', existing_user.avatar_style)
                    
                    # Create first child
                    try:
                        from src.children.service_pg import child_service_pg
                        
                        first_child = await child_service_pg.create_child(
                            db=db,
                            user_id=existing_user.user_id,
                            name=request.child.name,
                            age=request.child.age,
                            interests=request.child.interests,
                            image_base64=request.child_image_base64,
                            avatar_seed=getattr(request.child, 'avatar_seed', None),
                            avatar_style=getattr(request.child, 'avatar_style', 'adventurer'),
                            system_prompt=request.system_prompt
                        )
                        
                        existing_user.children_count = 1
                        existing_user.default_child_id = first_child.child_id
                        
                        await db.commit()
                        
                        print(f"✅ First child created: {first_child.child_id}")
                    except Exception as e:
                        await db.rollback()
                        print(f"❌ Failed to create first child: {str(e)}")
                        import traceback
                        print(f"📋 Traceback: {traceback.format_exc()}")
                        raise HTTPException(status_code=500, detail=f"Failed to create child: {str(e)}")
                
                # Get full profile
                existing_profile = await self.user_service_pg.get_user_profile(db, firebase_user_id)
                
                return AuthResponse(
                    success=True,
                    message="User profile found. Welcome back!" if existing_user.children_count > 1 else "Registration completed successfully!",
                    user_id=firebase_user_id,  # Return firebase_user_id for compatibility
                    profile=existing_profile
                )
            
            # Create user profile in PostgreSQL
            profile = await self.user_service_pg.create_user_profile(
                db=db,
                firebase_user_id=firebase_user_id,
                parent=request.parent,
                child=request.child,
                system_prompt=request.system_prompt,
                child_image_base64=request.child_image_base64,
                voice_audio_base64=getattr(request, 'voice_audio_base64', None)
            )
            
            await db.commit()  # Commit the transaction
            
            print(f"✅ User profile created in PostgreSQL: firebase_id={firebase_user_id}")
            
            return AuthResponse(
                success=True,
                message="User profile created successfully",
                user_id=firebase_user_id,  # Return firebase_user_id for compatibility
                profile=profile
            )
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            print(f"❌ PostgreSQL registration error: {str(e)}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

    # ===== USER PROFILE OPERATIONS =====

    async def get_user_profile(self, firebase_token: str) -> Dict[str, Any]:
        """
        Get user profile information.
        
        Args:
            firebase_token: Firebase ID token
            
        Returns:
            User profile data
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            # Verify Firebase token
            user_id = await self.auth_service.verify_token(firebase_token)
            
            # Get user profile
            profile = await self.user_service.get_user_profile(user_id)
            
            if not profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            return {
                "success": True,
                "user_id": user_id,
                "profile": profile
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")

    async def update_user_profile(self, request: UserProfileUpdate) -> AuthResponse:
        """
        Update user profile information.
        
        Args:
            request: User profile update request
            
        Returns:
            AuthResponse with updated profile
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            # Verify Firebase token
            user_id = await self.auth_service.verify_token(request.firebase_token)
            
            # Update user profile
            updated_profile = await self.user_service.update_user_profile(
                user_id=user_id,
                parent=request.parent,
                child=request.child,
                system_prompt=request.system_prompt,
                child_image_base64=request.child_image_base64
            )
            
            return AuthResponse(
                success=True,
                message="User profile updated successfully",
                user_id=user_id,
                profile=updated_profile
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Profile update failed: {str(e)}")

    async def verify_token_endpoint(self, firebase_token: str) -> TokenVerificationResponse:
        """
        Verify Firebase token and return user info.
        
        Args:
            firebase_token: Firebase ID token
            
        Returns:
            TokenVerificationResponse with user info and profile
        """
        try:
            # Verify Firebase token
            user_id = await self.auth_service.verify_token(firebase_token)
            
            # Get user profile if exists
            profile = await self.user_service.get_user_profile(user_id)
            
            return TokenVerificationResponse(
                success=True,
                valid=True,
                user_info={
                    "uid": user_id,
                    "email": None,  # Token verification doesn't provide email
                    "email_verified": True  # Assume verified for simplicity
                },
                has_profile=profile is not None,
                profile=profile
            )
            
        except HTTPException as e:
            return TokenVerificationResponse(
                success=False,
                valid=False,
                error=str(e.detail)
            )
        
    async def delete_user_profile(self, firebase_token: str) -> DeleteProfileResponse:
        """
        Delete user profile and associated data.
        
        Args:
            firebase_token: Firebase ID token
            
        Returns:
            DeleteProfileResponse
            
        Raises:
            HTTPException: If operation fails
        """
        try:
            # Verify Firebase token
            user_id = await self.auth_service.verify_token(firebase_token)
            
            # Delete user data
            await self.user_service.delete_user_data(user_id)
            
            return DeleteProfileResponse(
                success=True,
                message="User profile and associated data deleted successfully",
                user_id=user_id
            )
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete profile: {str(e)}")


# ===== SINGLETON INSTANCES =====

auth_service = AuthService()
user_auth_service = None  # Will be initialized after UserService is available


def get_user_auth_service() -> UserAuthService:
    """Get or create UserAuthService singleton."""
    global user_auth_service
    if user_auth_service is None:
        from src.user.service import user_service
        user_auth_service = UserAuthService(user_service, None, auth_service)
    return user_auth_service

    """Service for authentication and user token management."""
    
#     def __init__(self):
#         # Token verification cache (short TTL to balance security and performance)
#         self._token_cache: Dict[str, Dict[str, any]] = {}
#         self._token_cache_ttl = 60  # 1 minute cache for token verification
    
#     async def verify_token(self, token: str) -> str:
#         """
#         Verify Firebase ID token and return Firebase user ID (firebase_user_id).
#         WITH CACHING: 1-minute TTL to reduce Firebase Auth API calls.
        
#         Args:
#             token: Firebase ID token
            
#         Returns:
#             Firebase User ID (uid) - use this to lookup user in database by firebase_user_id
            
#         Raises:
#             HTTPException: If token is invalid
#         """
#         # Local debug bypass: only enable when both debug and explicit allow flag are set
#         if getattr(settings, 'debug', False) and getattr(settings, 'allow_local_auth_bypass', False):
#             print("⚠️ DEBUG + ALLOW_LOCAL_AUTH_BYPASS: bypassing Firebase token verification and returning debug-user")
#             return "debug-user"

#         # Check cache first
#         if token in self._token_cache:
#             cached_data = self._token_cache[token]
#             cache_age = time.time() - cached_data['timestamp']
#             if cache_age < self._token_cache_ttl:
#                 return cached_data['firebase_uid']
#             else:
#                 del self._token_cache[token]

#         try:
#             # Verify token with clock skew tolerance (allow 10 seconds)
#             decoded_token = auth.verify_id_token(token, check_revoked=False, clock_skew_seconds=10)
#             firebase_uid = decoded_token.get('uid') or decoded_token.get('user_id') or decoded_token.get('sub')
            
#             # Cache the result
#             self._token_cache[token] = {
#                 'firebase_uid': firebase_uid,
#                 'timestamp': time.time()
#             }
            
#             # Clean old cache entries (simple cleanup - keep cache size manageable)
#             if len(self._token_cache) > 1000:
#                 current_time = time.time()
#                 expired_tokens = [
#                     t for t, data in self._token_cache.items()
#                     if current_time - data['timestamp'] > self._token_cache_ttl
#                 ]
#                 for t in expired_tokens:
#                     del self._token_cache[t]
            
#             return firebase_uid
#         except Exception as e:
#             raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {str(e)}")
    
#     async def verify_token_and_get_user(self, token: str) -> User:
#         """
#         Verify Firebase token and return User object.
        
#         Args:
#             token: Firebase ID token
            
#         Returns:
#             User object with uid, email, name
            
#         Raises:
#             HTTPException: If token is invalid
#         """
#         # Local debug bypass
#         if getattr(settings, 'debug', False) and getattr(settings, 'allow_local_auth_bypass', False):
#             print("⚠️ DEBUG + ALLOW_LOCAL_AUTH_BYPASS: bypassing Firebase token verification and returning debug user")
#             return User(
#                 uid='debug-user',
#                 email='debug@example.com',
#                 name='Debug User',
#                 token={}
#             )

#         try:
#             # Verify token with clock skew tolerance (allow 10 seconds for clock drift)
#             decoded_token = auth.verify_id_token(token, check_revoked=False, clock_skew_seconds=10)
#             return User(
#                 uid=decoded_token.get('uid') or decoded_token.get('user_id') or decoded_token.get('sub'),
#                 email=decoded_token.get('email'),
#                 name=decoded_token.get('name'),
#                 token=decoded_token
#             )
#         except Exception as e:
#             raise HTTPException(status_code=401, detail=f"Invalid Firebase token: {str(e)}")

# class UserAuthService:
#     """Service for user registration and profile management."""
    
#     def __init__(self, user_service_firebase: UserService = None, user_service_pg = None, auth_service: AuthService = None):
#         self.user_service = user_service_firebase  # Legacy Firebase service
#         self.user_service_pg = user_service_pg  # New PostgreSQL service
#         self.auth_service = auth_service
    
#     async def register_user(self, request: UserRegistration) -> AuthResponse:
#         """Register a new user with parent and child profiles (LEGACY - uses Firebase)"""
#         try:
#             # Verify Firebase token
#             user_id = await self.auth_service.verify_token(request.firebase_token)
#             print(f"✅ Firebase token verified - User ID: {user_id}")
            
#             # Check if user already exists
#             existing_profile = await self.user_service.get_user_profile(user_id)
#             if existing_profile:
#                 print(f"✅ User {user_id} already has profile, returning existing data")
#                 return AuthResponse(
#                     success=True,
#                     message="User profile found. Welcome back!",
#                     user_id=user_id,
#                     profile=existing_profile
#                 )
            
#             # Create user profile
#             profile = await self.user_service.create_user_profile(
#                 user_id=user_id,
#                 parent=request.parent,
#                 child=request.child,
#                 system_prompt=request.system_prompt,
#                 child_image_base64=request.child_image_base64
#             )
            
#             return AuthResponse(
#                 success=True,
#                 message="User profile created successfully",
#                 user_id=user_id,
#                 profile=profile
#             )
            
#         except HTTPException:
#             raise
#         except Exception as e:
#             print(f"❌ Registration error details: {str(e)}")
#             import traceback
#             traceback.print_exc()
#             raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")
    
#     async def register_user_pg(self, request: UserRegistration, db) -> AuthResponse:
#         """Register a new user with parent and child profiles using PostgreSQL"""
#         try:
#             # Verify Firebase token to get firebase_user_id
#             firebase_user_id = await self.auth_service.verify_token(request.firebase_token)
#             print(f"✅ Firebase token verified - Firebase User ID: {firebase_user_id}")
            
#             # Check if user already exists in PostgreSQL by firebase_user_id
#             existing_user = await self.user_service_pg.get_user_by_firebase_id(db, firebase_user_id)
#             if existing_user:
#                 print(f"✅ User {firebase_user_id} already exists in PostgreSQL (user_id={existing_user.user_id})")
                
#                 # Check if user has children - if not, this is first-time registration
#                 if existing_user.children_count == 0:
#                     print(f"🔧 User has no children yet - completing registration by adding first child")
                    
#                     # Update parent info if provided
#                     if request.parent:
#                         name_parts = (request.parent.name or "").split(maxsplit=1)
#                         existing_user.first_name = name_parts[0] if len(name_parts) > 0 else existing_user.first_name
#                         existing_user.last_name = name_parts[1] if len(name_parts) > 1 else existing_user.last_name
#                         existing_user.email = request.parent.email or existing_user.email
#                         existing_user.phone_number = request.parent.phone_number
#                         existing_user.avatar_seed = getattr(request.parent, 'avatar_seed', existing_user.avatar_seed)
#                         existing_user.avatar_style = getattr(request.parent, 'avatar_style', existing_user.avatar_style)
                    
#                     # Create first child
#                     try:
#                         from src.children.service_pg import child_service_pg
                        
#                         first_child = await child_service_pg.create_child(
#                             db=db,
#                             user_id=existing_user.user_id,
#                             name=request.child.name,
#                             age=request.child.age,
#                             interests=request.child.interests,
#                             image_base64=request.child_image_base64,
#                             avatar_seed=getattr(request.child, 'avatar_seed', None),
#                             avatar_style=getattr(request.child, 'avatar_style', 'adventurer'),
#                             system_prompt=request.system_prompt
#                         )
                        
#                         existing_user.children_count = 1
#                         existing_user.default_child_id = first_child.child_id
                        
#                         await db.commit()
                        
#                         print(f"✅ First child created: {first_child.child_id}")
#                     except Exception as e:
#                         await db.rollback()
#                         print(f"❌ Failed to create first child: {str(e)}")
#                         import traceback
#                         print(f"📋 Traceback: {traceback.format_exc()}")
#                         raise HTTPException(status_code=500, detail=f"Failed to create child: {str(e)}")
                
#                 # Get full profile
#                 existing_profile = await self.user_service_pg.get_user_profile(db, firebase_user_id)
                
#                 return AuthResponse(
#                     success=True,
#                     message="User profile found. Welcome back!" if existing_user.children_count > 1 else "Registration completed successfully!",
#                     user_id=firebase_user_id,  # Return firebase_user_id for compatibility
#                     profile=existing_profile
#                 )
            
#             # Create user profile in PostgreSQL
#             profile = await self.user_service_pg.create_user_profile(
#                 db=db,
#                 firebase_user_id=firebase_user_id,
#                 parent=request.parent,
#                 child=request.child,
#                 system_prompt=request.system_prompt,
#                 child_image_base64=request.child_image_base64,
#                 voice_audio_base64=getattr(request, 'voice_audio_base64', None)
#             )
            
#             await db.commit()  # Commit the transaction
            
#             print(f"✅ User profile created in PostgreSQL: firebase_id={firebase_user_id}")
            
#             return AuthResponse(
#                 success=True,
#                 message="User profile created successfully",
#                 user_id=firebase_user_id,  # Return firebase_user_id for compatibility
#                 profile=profile
#             )
            
#         except HTTPException:
#             await db.rollback()
#             raise
#         except Exception as e:
#             await db.rollback()
#             print(f"❌ PostgreSQL registration error: {str(e)}")
#             import traceback
#             traceback.print_exc()
#             raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

#     # ALSO FIX: Update other methods in AuthService that use verify_firebase_token

#     async def get_user_profile(self, firebase_token: str) -> Dict[str, Any]:
#         """Get user profile information"""
#         try:
#             # Verify Firebase token
#             user_id = await self.auth_service.verify_token(firebase_token)
            
#             # Get user profile
#             profile = await self.user_service.get_user_profile(user_id)
            
#             if not profile:
#                 raise HTTPException(status_code=404, detail="User profile not found")
            
#             return {
#                 "success": True,
#                 "user_id": user_id,
#                 "profile": profile
#             }
            
#         except HTTPException:
#             raise
#         except Exception as e:
#             raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")

#     async def update_user_profile(self, request: UserProfileUpdate) -> AuthResponse:
#         """Update user profile information"""
#         try:
#             # Verify Firebase token
#             user_id = await self.auth_service.verify_token(request.firebase_token)
            
#             # Update user profile
#             updated_profile = await self.user_service.update_user_profile(
#                 user_id=user_id,
#                 parent=request.parent,
#                 child=request.child,
#                 system_prompt=request.system_prompt,
#                 child_image_base64=request.child_image_base64
#             )
            
#             return AuthResponse(
#                 success=True,
#                 message="User profile updated successfully",
#                 user_id=user_id,
#                 profile=updated_profile
#             )
            
#         except HTTPException:
#             raise
#         except Exception as e:
#             raise HTTPException(status_code=500, detail=f"Profile update failed: {str(e)}")

#     async def verify_token_endpoint(self, firebase_token: str) -> Dict[str, Any]:
#         """Verify Firebase token and return user info"""
#         try:
#             # Verify Firebase token
#             user_id = await self.auth_service.verify_token(firebase_token)
            
#             # Get user profile if exists
#             profile = await self.user_service.get_user_profile(user_id)
            
#             return {
#                 "success": True,
#                 "valid": True,
#                 "user_info": {
#                     "uid": user_id,
#                     "email": None,  # Token verification doesn't provide email
#                     "email_verified": True  # Assume verified for simplicity
#                 },
#                 "has_profile": profile is not None,
#                 "profile": profile
#             }
            
#         except HTTPException as e:
#             return {
#                 "success": False,
#                 "valid": False,
#                 "error": str(e.detail)
#             }
        
#     async def delete_user_profile(self, firebase_token: str) -> Dict[str, Any]:
#         """Delete user profile and associated data"""
#         try:
#             # Verify Firebase token
#             user_id = await self.auth_service.verify_token(firebase_token)
            
#             # Delete user data
#             await self.user_service.delete_user_data(user_id)
            
#             return {
#                 "success": True,
#                 "message": "User profile and associated data deleted successfully",
#                 "user_id": user_id
#             }
            
#         except Exception as e:
#             raise HTTPException(status_code=500, detail=f"Failed to delete profile: {str(e)}")


# # Singleton instances
# auth_service = AuthService()
# user_auth_service = None  # Will be initialized after UserService is available


# def get_user_auth_service() -> UserAuthService:
#     """Get or create UserAuthService singleton."""
#     global user_auth_service
#     if user_auth_service is None:
#         from src.user.service import user_service
#         user_auth_service = UserAuthService(user_service, auth_service)
#     return user_auth_service
