"""
User Routes Module
Contains only FastAPI route definitions that delegate to UserService.
No business logic - all logic is in service_pg.py.

Note: Voice clone endpoints are kept as-is for now (they can be moved to a separate module later).
"""
from fastapi import APIRouter, HTTPException, Header, Depends, UploadFile, File, Form
from typing import Dict, Any
import base64
from sqlalchemy.ext.asyncio import AsyncSession

from src.user.schema import (
    UserRegistration,
    UserProfileUpdate,
    UserProfileResponse,
    AvatarUpdateRequest,
    UserAvatarUpdate,
    UserAvatarResponse,
    ParentProfile,
    ChildProfile,
    VoiceCloneCreate,
    VoiceCloneUpdate,
    VoiceCloneListRequest
)

from src.user.service_pg import user_service
from src.db import get_session
from src.common_function.cartesia_voice import CartesiaService
from src.voice_clone.service_pg import voice_clone_service_pg
from src.dependencies import verify_firebase_token

router = APIRouter(prefix="/users", tags=["users"])


# ===== CORE USER PROFILE ENDPOINTS =====

@router.post("/register", response_model=Dict[str, Any])
async def register_user(request: UserRegistration, db: AsyncSession = Depends(get_session)):
    """
    Register a new user with parent and child profiles.
    Delegates to UserService.create_user_profile()
    """
    try:
        # Verify Firebase token and get firebase_user_id
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        # Check if user already exists
        existing_profile = await user_service.get_user_profile(db, firebase_user_id)
        if existing_profile:
            raise HTTPException(status_code=409, detail="User profile already exists")
        
        # Create user profile with voice cloning support
        profile = await user_service.create_user_profile(
            db=db,
            firebase_user_id=firebase_user_id,
            parent=request.parent,
            child=request.child,
            system_prompt=request.system_prompt,
            child_image_base64=request.child_image_base64,
            voice_audio_base64=request.voice_audio_base64
        )
        
        return {
            "success": True,
            "message": "User profile created successfully",
            "profile": profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.get("/profile", response_model=Dict[str, Any])
async def get_user_profile(firebase_token: str, db: AsyncSession = Depends(get_session)):
    """
    Get user profile with avatar information.
    Delegates to UserService.get_user_profile()
    """
    try:
        # Verify Firebase token and get firebase_user_id
        firebase_user_id = await verify_firebase_token(firebase_token)
        
        # Get user profile
        profile = await user_service.get_user_profile(db, firebase_user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        return {
            "success": True,
            "profile": profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"❌ Error in /users/profile: {str(e)}")
        print(f"📋 Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Failed to get profile: {str(e)}")


@router.put("/profile", response_model=Dict[str, Any])
async def update_user_profile(request: UserProfileUpdate, db: AsyncSession = Depends(get_session)):
    """
    Update user profile.
    Delegates to UserService.update_user_profile()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Update user profile with voice cloning support
        updated_profile = await user_service.update_user_profile(
            db=db,
            user_id=user_id,
            parent=request.parent,
            child=request.child,
            system_prompt=request.system_prompt,
            child_image_base64=request.child_image_base64,
            voice_audio_base64=request.voice_audio_base64
        )
        
        return {
            "success": True,
            "message": "Profile updated successfully",
            "profile": updated_profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update profile: {str(e)}")


@router.delete("/profile")
async def delete_user_profile(firebase_token: str):
    """
    Delete user profile and all associated data.
    Delegates to UserService.delete_user_data()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Delete user data
        await user_service.delete_user_data(user_id)
        
        return {
            "success": True,
            "message": "User profile and data deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete profile: {str(e)}")


# ===== AVATAR MANAGEMENT ENDPOINTS =====

@router.put("/avatar", response_model=Dict[str, Any])
async def update_avatar_settings(request: AvatarUpdateRequest):
    """
    Update avatar settings for child or parent.
    Delegates to UserService.update_avatar_settings()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Update avatar settings
        updated_profile = await user_service.update_avatar_settings(
            user_id=user_id,
            target=request.target,
            avatar_seed=request.avatar_seed,
            avatar_style=request.avatar_style
        )
        
        return {
            "success": True,
            "message": f"Avatar settings updated for {request.target}",
            "profile": updated_profile
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update avatar: {str(e)}")


@router.get("/avatar/{target}", response_model=Dict[str, Any])
async def get_avatar_settings(target: str, firebase_token: str):
    """
    Get avatar settings for child or parent.
    Delegates to UserService.get_avatar_settings()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Get avatar settings
        avatar_settings = await user_service.get_avatar_settings(user_id, target)
        
        return {
            "success": True,
            "target": target,
            "avatar_settings": avatar_settings
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get avatar settings: {str(e)}")


# ===== UNIFIED AVATAR CONSISTENCY ENDPOINTS =====

@router.put("/api/user/avatar")
async def update_user_avatar(avatar_data: UserAvatarUpdate, firebase_token: str):
    """
    Save user's avatar settings (style, seed, URL) for cross-device consistency.
    Delegates to UserService.update_user_avatar()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Convert Pydantic model to dict
        avatar_dict = {
            "avatar_style": avatar_data.avatar_style,
            "avatar_seed": avatar_data.avatar_seed,
            "avatar_url": avatar_data.avatar_url
        }
        
        # Update user avatar
        result = await user_service.update_user_avatar(user_id, avatar_dict)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update avatar: {str(e)}")


@router.get("/api/user/avatar", response_model=UserAvatarResponse)
async def get_user_avatar(firebase_token: str):
    """
    Retrieve user's saved avatar settings for consistent display across devices.
    Delegates to UserService.get_user_avatar()
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Get user avatar
        result = await user_service.get_user_avatar(user_id)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get avatar: {str(e)}")


# ===== HEALTH CHECK ENDPOINT =====

@router.get("/health")
async def health_check():
    """Health check endpoint for user service"""
    try:
        # Simple health check - try to access Firestore
        from src.common_function.firebase_init import is_firebase_available
        
        return {
            "success": True,
            "service": "user_service",
            "firebase_available": is_firebase_available(),
            "status": "healthy"
        }
        
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")


# ===== CHILD/PARENT PROFILE ENDPOINTS (LEGACY) =====

@router.put("/child", response_model=Dict[str, Any])
async def update_child_profile(firebase_token: str, child: ChildProfile):
    """
    Update only child profile information (legacy endpoint).
    Delegates to UserService.update_user_profile()
    """
    try:
        user_id = await verify_firebase_token(firebase_token)
        
        # Update only child data
        updated_profile = await user_service.update_user_profile(
            user_id=user_id,
            child=child
        )
        
        return {
            "success": True,
            "message": "Child profile updated successfully",
            "child": updated_profile.get('child')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update child profile: {str(e)}")


@router.put("/parent", response_model=Dict[str, Any])
async def update_parent_profile(firebase_token: str, parent: ParentProfile):
    """
    Update only parent profile information (legacy endpoint).
    Delegates to UserService.update_user_profile()
    """
    try:
        user_id = await verify_firebase_token(firebase_token)
        
        # Update only parent data
        updated_profile = await user_service.update_user_profile(
            user_id=user_id,
            parent=parent
        )
        
        return {
            "success": True,
            "message": "Parent profile updated successfully",
            "parent": updated_profile.get('parent')
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update parent profile: {str(e)}")


@router.get("/child", response_model=Dict[str, Any])
async def get_child_profile(firebase_token: str, db: AsyncSession = Depends(get_session)):
    """
    Get only child profile with avatar information (legacy endpoint).
    Delegates to UserService.get_user_profile()
    """
    try:
        user_id = await verify_firebase_token(firebase_token)
        
        profile = await user_service.get_user_profile(db, user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        child_data = profile.get('child', {})
        
        return {
            "success": True,
            "child": child_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get child profile: {str(e)}")


@router.get("/parent", response_model=Dict[str, Any])
async def get_parent_profile(firebase_token: str, db: AsyncSession = Depends(get_session)):
    """
    Get only parent profile with avatar information (legacy endpoint).
    Delegates to UserService.get_user_profile()
    """
    try:
        user_id = await verify_firebase_token(firebase_token)
        
        profile = await user_service.get_user_profile(db, user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        parent_data = profile.get('parent', {})
        
        return {
            "success": True,
            "parent": parent_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get parent profile: {str(e)}")


# ===== VOICE CLONE MANAGEMENT ENDPOINTS =====
# Note: These endpoints contain business logic and should ideally be moved to a separate voice_clone module
# For now, they are kept as-is to maintain backward compatibility

@router.post("/voice-clone/create")
async def create_voice_clone(request: VoiceCloneCreate, db: AsyncSession = Depends(get_session)):
    """Create a new voice clone for the user using PostgreSQL (updated endpoint)"""
    try:
        # Verify Firebase token
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 Creating voice clone for user {firebase_user_id}: {request.voice_name}")
        print(f"   Audio format: {request.audio_data.format}, size: {request.audio_data.size_bytes} bytes")
        
        # Validate audio data
        if not request.audio_data.base64:
            raise HTTPException(status_code=400, detail="Audio data is required")
        
        # Decode base64 audio data
        try:
            audio_bytes = base64.b64decode(request.audio_data.base64)
            print(f"   Decoded audio size: {len(audio_bytes)} bytes")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio data: {str(e)}")
        
        # Validate audio size matches
        if len(audio_bytes) != request.audio_data.size_bytes:
            print(f"⚠️ Size mismatch: claimed {request.audio_data.size_bytes}, actual {len(audio_bytes)}")
        
        # Check for corruption (null bytes check)
        null_count = audio_bytes.count(b'\x00')
        null_percentage = (null_count / len(audio_bytes)) * 100 if len(audio_bytes) > 0 else 0
        
        if null_percentage > 50:  # More than 50% null bytes indicates corruption
            print(f"⚠️ Detected corrupted audio - {null_percentage:.1f}% null bytes ({null_count}/{len(audio_bytes)})")
            raise HTTPException(
                status_code=400, 
                detail=f"Corrupted audio file detected ({null_percentage:.1f}% null bytes)"
            )
        
        # Log corruption check
        print(f"   Corruption check: {null_percentage:.1f}% null bytes")
        
        # Detect actual format from audio bytes (magic numbers)
        actual_format = "unknown"
        if audio_bytes[:4] == b'ftyp' or audio_bytes[4:8] == b'ftyp':
            actual_format = "m4a"
        elif audio_bytes[:4] == b'RIFF':
            actual_format = "wav"
        elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb' or audio_bytes[:2] == b'\xff\xf3':
            actual_format = "mp3"
        
        print(f"   Detected format: {actual_format}")
        
        # Warn if client format claim doesn't match reality
        if request.audio_data.format != actual_format:
            print(f"⚠️ Format mismatch: Client claimed '{request.audio_data.format}' but detected '{actual_format}'. Using detected format.")
        
        # Create voice clone with Cartesia API
        cartesia_service = CartesiaService()
        
        try:
            print(f"🎤 Creating voice clone with Cartesia API...")
            cartesia_voice_id = await cartesia_service.clone_voice_from_audio(
                audio_data=audio_bytes,
                user_id=firebase_user_id,
                voice_name=request.voice_name,
                description=request.description
            )
            
            if not cartesia_voice_id:
                raise HTTPException(status_code=500, detail="Failed to create voice clone with Cartesia")
            
            print(f"✅ Cartesia voice created: {cartesia_voice_id}")
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Cartesia API error: {str(e)}")
            import traceback
            print(f"📋 Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=f"Voice clone creation failed: {str(e)}")
        
        # Save to PostgreSQL
        voice_clone_data = None
        try:
            voice_clone_data = await voice_clone_service_pg.create_voice_clone(
                db=db,
                firebase_user_id=firebase_user_id,
                name=request.voice_name,
                cartesia_voice_id=cartesia_voice_id,
                description=request.description,
                language="en"
            )
            
            # Set as active voice clone automatically
            all_clones = await voice_clone_service_pg.get_user_voice_clones(db, firebase_user_id)
            for clone in all_clones:
                is_target = clone.get('voice_clone_id') == voice_clone_data.get('voice_clone_id')
                if clone.get('is_active') != is_target:
                    await voice_clone_service_pg.update_voice_clone(
                        db, clone.get('voice_clone_id'), firebase_user_id, is_active=is_target
                    )
            
            print(f"✅ Voice clone created in PostgreSQL and set as active: {voice_clone_data.get('voice_clone_id')}")
            
            # Commit all database changes
            await db.commit()
            
            # Build response AFTER successful commit
            response = {
                "success": True,
                "message": "Voice clone created successfully in PostgreSQL",
                "voice_clone": voice_clone_data,
                "user_id": firebase_user_id,
                "audio_format": request.audio_data.format,
                "audio_size_bytes": request.audio_data.size_bytes
            }
            
            return response
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            print(f"❌ PostgreSQL save error: {str(e)}")
            import traceback
            print(f"📋 Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to save voice clone to database: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Voice clone creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")


# ===== VOICE CLONES LIST ENDPOINT =====

@router.post("/voice-clones/list")
async def get_user_voice_clones(
    request: VoiceCloneListRequest,
    db: AsyncSession = Depends(get_session),
    authorization: str = Header(None)
):
    """
    Get all voice clones for a user from PostgreSQL
    
    Authentication (pick one):
    1. Request body: {"firebase_token": "..."}
    2. Authorization header: Bearer <token>
    
    Returns:
    {
        "user_id": "...",
        "voice_clones": [...],
        "default_voice": {...},
        "total_count": 2
    }
    """
    try:
        # Get token from request body or Authorization header
        token = request.firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        # Validate token is provided
        if not token:
            print("❌ Missing firebase_token in request body and Authorization header")
            raise HTTPException(status_code=401, detail="Firebase token is required (in request body or Authorization header)")
        
        # Verify Firebase token
        try:
            firebase_user_id = await verify_firebase_token(token)
        except Exception as e:
            print(f"❌ Token verification failed: {str(e)}")
            raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")
        
        print(f"📋 Fetching voice clones from PostgreSQL for user: {firebase_user_id}")
        
        # Get all voice clones from PostgreSQL
        voice_clones = await voice_clone_service_pg.get_user_voice_clones(db, firebase_user_id)
        print(f"✅ Retrieved {len(voice_clones)} voice clones from PostgreSQL")
        
        # Get default voice info
        try:
            cartesia_service = CartesiaService()
            default_voice = cartesia_service.get_default_voice_info()
        except Exception as e:
            print(f"⚠️ Could not get default voice info: {e}")
            default_voice = {
                "voice_id": "79a125e8-cd45-4c13-8a67-188112f4dd22",
                "voice_name": "British Lady (Default)",
                "description": "Professional female narrator voice",
                "is_default": True
            }
        
        return {
            "user_id": firebase_user_id,
            "voice_clones": voice_clones,
            "default_voice": default_voice,
            "total_count": len(voice_clones)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to fetch voice clones: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch voice clones: {str(e)}")


# Additional voice clone endpoints would go here...
# They are intentionally kept with business logic for now to maintain backward compatibility
# TODO: Move to separate voice_clone module in future refactoring
