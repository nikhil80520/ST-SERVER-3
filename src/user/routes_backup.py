from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Header
from typing import Dict, Any, Optional
import base64
import json
from firebase_admin import firestore
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
    VoiceCloneUpdate
)

from src.user.service_pg import UserServicePostgreSQL
from src.db import get_session
from src.common_function.cartesia_voice import CartesiaService
from src.voice_clone.service_pg import voice_clone_service_pg
from src.dependencies import verify_firebase_token

router = APIRouter(prefix="/users", tags=["users"])
user_service = UserServicePostgreSQL()

@router.post("/register", response_model=Dict[str, Any])
async def register_user(request: UserRegistration, db: AsyncSession = Depends(get_session)):
    """Register a new user with parent and child profiles"""
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
    """Get user profile with avatar information"""
    try:
        # Verify Firebase token and get firebase_user_id
        firebase_user_id = await verify_firebase_token(firebase_token)
        
        # Get user profile (datetime fields are already converted to ISO strings in service layer)
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
    """Update user profile"""
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Update user profile with voice cloning support
        # Update user profile with voice cloning support (datetime fields already converted to ISO strings in service layer)
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
    """Delete user profile and all associated data"""
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

@router.put("/avatar", response_model=Dict[str, Any])
async def update_avatar_settings(request: AvatarUpdateRequest):
    """Update avatar settings for child or parent"""
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Update avatar settings (datetime fields already converted to ISO strings in service layer)
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
    """Get avatar settings for child or parent"""
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
    """Save user's avatar settings (style, seed, URL) for cross-device consistency"""
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
    """Retrieve user's saved avatar settings for consistent display across devices and sessions"""
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

# Additional endpoints for managing child and parent data separately

@router.put("/child", response_model=Dict[str, Any])
async def update_child_profile(firebase_token: str, child: ChildProfile):
    """Update only child profile information"""
    try:
        user_id = await verify_firebase_token(firebase_token)
        
        # Create UserProfileUpdate with only child data
        update_request = UserProfileUpdate(
            firebase_token=firebase_token,
            child=child
        )
        
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
    """Update only parent profile information"""
    try:
        user_id = await verify_firebase_token(firebase_token)
        
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
    """Get only child profile with avatar information"""
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
    """Get only parent profile with avatar information"""
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

@router.post("/voice-clone/create")
async def create_voice_clone(request: VoiceCloneCreate, db: AsyncSession = Depends(get_session)):
    """Create a new voice clone for the user using PostgreSQL (updated endpoint)"""
    try:
        # Verify Firebase token
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🎤 Creating voice clone for user {firebase_user_id}: {request.voice_name}")
        print(f"📄 Description: {request.description}")
        print(f"🎵 Audio format: {request.audio_data.format} ({request.audio_data.mime_type})")
        print(f"📊 Audio size: {request.audio_data.size_bytes} bytes")
        
        # Validate corruption check
        corruption = request.audio_data.corruption_check
        if corruption.null_bytes > 0:
            raise HTTPException(status_code=400, detail=f"Corrupted audio data detected: {corruption.null_bytes} null bytes found")
        
        if not corruption.is_valid_base64:
            raise HTTPException(status_code=400, detail="Invalid base64 audio data")
        
        # Validate audio format
        allowed_formats = ['m4a', 'wav', 'mp3']
        if request.audio_data.format not in allowed_formats:
            raise HTTPException(status_code=400, detail=f"Unsupported audio format: {request.audio_data.format}. Allowed: {allowed_formats}")
        
        # Convert base64 to bytes
        try:
            audio_bytes = base64.b64decode(request.audio_data.base64)
            print(f"✅ Successfully decoded base64 audio: {len(audio_bytes)} bytes")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode base64 audio: {str(e)}")
        
        # Validate decoded size is reasonably close to expected size (allow 0.5% tolerance for encoding variations)
        size_diff = abs(len(audio_bytes) - request.audio_data.size_bytes)
        tolerance = max(1024, int(request.audio_data.size_bytes * 0.005))  # At least 1KB or 0.5% of file size
        if size_diff > tolerance:
            raise HTTPException(status_code=400, detail=f"Size mismatch too large: expected {request.audio_data.size_bytes}, got {len(audio_bytes)} bytes (difference: {size_diff} bytes, tolerance: {tolerance} bytes)")
        elif size_diff > 0:
            print(f"⚠️ Minor size difference: expected {request.audio_data.size_bytes}, got {len(audio_bytes)} bytes (difference: {size_diff} bytes - within tolerance)")
        
        # Check file size (max 25MB)
        if len(audio_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()

        # Detect actual audio format from the audio data (don't trust client's claim)
        actual_format, content_type = cartesia_service._detect_audio_format(audio_bytes)
        print(f"🔍 Client claimed format: {request.audio_data.format}")
        print(f"🔍 Actually detected format: {actual_format}")
        
        # Validate that we can handle the detected format
        supported_formats = ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'pcm_raw']
        if actual_format not in supported_formats:
            raise HTTPException(status_code=400, detail=f"Detected audio format '{actual_format}' is not supported. Supported: {supported_formats}")
        
        # Warn if client format claim doesn't match reality
        if request.audio_data.format != actual_format:
            print(f"⚠️ Format mismatch: Client claimed '{request.audio_data.format}' but detected '{actual_format}'. Using detected format.")
        
        # Create voice clone with Cartesia API
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
        
        # Save to PostgreSQL (separate try block to avoid mixing with Firebase operations)
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
                is_target = clone['voice_clone_id'] == voice_clone_data['voice_clone_id']
                if clone['is_active'] != is_target:
                    await voice_clone_service_pg.update_voice_clone(
                        db, clone['voice_clone_id'], firebase_user_id, is_active=is_target
                    )
            
            print(f"✅ Voice clone created in PostgreSQL and set as active: {voice_clone_data['voice_clone_id']}")
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ PostgreSQL save error: {str(e)}")
            import traceback
            print(f"📋 Full traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Failed to save voice clone to database: {str(e)}")
        
        # ✅ CRITICAL: Close DB session explicitly before returning to avoid greenlet context issues
        # This prevents FastAPI's cleanup from attempting to close the session after Firebase operations
        await db.close()
        
        return {
            "success": True,
            "message": "Voice clone created successfully in PostgreSQL",
            "voice_clone": voice_clone_data,
            "user_id": firebase_user_id,
            "audio_format": request.audio_data.format,
            "audio_size_bytes": request.audio_data.size_bytes
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Voice clone creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")

@router.post("/voice-clone/create/legacy")
async def create_voice_clone_legacy(
    firebase_token: str = Form(...),
    voice_name: str = Form(...),
    description: str = Form("Custom voice clone"),
    audio_file: UploadFile = File(...)
):
    """LEGACY: Create a new voice clone using multipart form data (fallback for old clients)"""
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"🔄 LEGACY: Creating voice clone for user {user_id}: {voice_name}")
        
        # Validate audio file
        if not audio_file.content_type.startswith("audio/"):
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Read audio content
        content = await audio_file.read()
        
        # Check for corruption (excessive null bytes)
        null_count = content.count(b'\x00')
        null_percentage = (null_count / len(content)) * 100 if len(content) > 0 else 0
        
        if null_percentage > 50:  # More than 50% null bytes indicates corruption
            print(f"⚠️ LEGACY: Detected corrupted audio - {null_percentage:.1f}% null bytes ({null_count}/{len(content)})")
            raise HTTPException(
                status_code=400, 
                detail=f"Corrupted audio file detected ({null_percentage:.1f}% null bytes). Please use the new JSON API format for better reliability."
            )
        
        if len(content) < 1000:  # Suspiciously small audio file
            raise HTTPException(status_code=400, detail="Audio file too small or empty")
        
        # Check file size (max 25MB)
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Create voice clone using multiple voice clones model
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=voice_name,
            audio_data=content,
            description=description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ LEGACY: Voice clone created and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone created successfully (legacy endpoint)",
            "voice_clone": voice_clone_data,
            "voice_name": voice_name,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ LEGACY: Voice clone creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")

@router.put("/voice-clone/update/legacy")
async def update_voice_clone_legacy(
    firebase_token: str = Form(...),
    voice_name: str = Form(...),
    description: str = Form("Updated voice clone"),
    audio_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session)
):
    """LEGACY: Update voice clone using multipart form data (fallback for old clients)"""
    try:
        # Check if audio file is provided and valid
        if not audio_file or not audio_file.filename:
            raise HTTPException(status_code=400, detail="No audio file provided")
        
        if audio_file.size == 0:
            raise HTTPException(status_code=400, detail="Audio file is empty")
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"🔄 LEGACY: Starting voice clone update for user {user_id}")
        
        # Validate audio file
        if not audio_file.content_type.startswith('audio/'):
            raise HTTPException(status_code=400, detail="File must be an audio file")
        
        # Get user profile to check for existing voice clone
        user_profile = await user_service.get_user_profile(db, user_id)
        if not user_profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        existing_voice_clone_id = user_profile.get('voice_clone_id')
        
        # Read audio content
        audio_content = await audio_file.read()
        
        # Check for corruption (excessive null bytes)
        null_count = audio_content.count(b'\x00')
        null_percentage = (null_count / len(audio_content)) * 100 if len(audio_content) > 0 else 0
        
        if null_percentage > 50:  # More than 50% null bytes indicates corruption
            print(f"⚠️ LEGACY: Detected corrupted audio - {null_percentage:.1f}% null bytes ({null_count}/{len(audio_content)})")
            raise HTTPException(
                status_code=400, 
                detail=f"Corrupted audio file detected ({null_percentage:.1f}% null bytes). Please use the new JSON API format for better reliability."
            )
        
        if len(audio_content) < 1000:  # Suspiciously small audio file
            raise HTTPException(status_code=400, detail="Audio file too small or empty")
        
        # Check file size (max 25MB)
        if len(audio_content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Create voice clone using multiple voice clones model (replaces active one)
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=voice_name,
            audio_data=audio_content,
            description=description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ LEGACY: Voice clone updated and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone updated successfully (legacy endpoint)",
            "voice_clone": voice_clone_data,
            "voice_name": voice_name,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ LEGACY: Voice clone update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")

@router.delete("/voice-clone/delete")
async def delete_voice_clone(firebase_token: str):
    """Delete the user's active voice clone (Note: Use DELETE /voice-clones/delete endpoint with voice_clone_id for deleting specific clones)"""
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Get user document to find active voice clone
        db = firestore.client()
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_doc.to_dict()
        active_voice_clone_id = user_data.get('active_voice_clone_id')
        
        if not active_voice_clone_id:
            raise HTTPException(status_code=404, detail="No active voice clone found for this user")
            
        print(f"🗑️ Deleting active voice clone for user {user_id}: {active_voice_clone_id}")
        
        # Delete voice clone using new model
        success = await cartesia_service.delete_voice_clone_by_id(user_id, active_voice_clone_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete voice clone")
        
        print(f"✅ Voice clone deleted successfully: {active_voice_clone_id}")
        
        return {
            "success": True,
            "message": "Active voice clone deleted successfully",
            "deleted_voice_clone_id": active_voice_clone_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Voice clone deletion failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete voice clone: {str(e)}")

@router.put("/voice-clone/update")
async def update_voice_clone(request: VoiceCloneUpdate):
    """Update user's voice clone by deleting old one and creating a new one using clean JSON format"""
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 Starting voice clone update for user {user_id}")
        print(f"📝 New voice name: {request.voice_name}")
        print(f"📄 Description: {request.description}")
        print(f"🎵 Audio format: {request.audio_data.format} ({request.audio_data.mime_type})")
        print(f"📊 Audio size: {request.audio_data.size_bytes} bytes")
        
        # Validate corruption check
        corruption = request.audio_data.corruption_check
        if corruption.null_bytes > 0:
            raise HTTPException(status_code=400, detail=f"Corrupted audio data detected: {corruption.null_bytes} null bytes found")
        
        if not corruption.is_valid_base64:
            raise HTTPException(status_code=400, detail="Invalid base64 audio data")
        
        # Convert base64 to bytes first 
        try:
            audio_bytes = base64.b64decode(request.audio_data.base64)
            print(f"✅ Successfully decoded base64 audio: {len(audio_bytes)} bytes")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to decode base64 audio: {str(e)}")
        
        # Validate decoded size is reasonably close to expected size (allow 0.5% tolerance for encoding variations)
        size_diff = abs(len(audio_bytes) - request.audio_data.size_bytes)
        tolerance = max(1024, int(request.audio_data.size_bytes * 0.005))  # At least 1KB or 0.5% of file size
        if size_diff > tolerance:
            raise HTTPException(status_code=400, detail=f"Size mismatch too large: expected {request.audio_data.size_bytes}, got {len(audio_bytes)} bytes (difference: {size_diff} bytes, tolerance: {tolerance} bytes)")
        elif size_diff > 0:
            print(f"⚠️ Minor size difference: expected {request.audio_data.size_bytes}, got {len(audio_bytes)} bytes (difference: {size_diff} bytes - within tolerance)")
        
        # Check file size (max 25MB)
        if len(audio_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")

        # Initialize Cartesia service
        cartesia_service = CartesiaService()

        # Detect actual audio format from the audio data (don't trust client's claim)
        actual_format, content_type = cartesia_service._detect_audio_format(audio_bytes)
        print(f"🔍 Client claimed format: {request.audio_data.format}")
        print(f"🔍 Actually detected format: {actual_format}")
        
        # Validate that we can handle the detected format
        supported_formats = ['wav', 'mp3', 'flac', 'm4a', 'ogg', 'pcm_raw']
        if actual_format not in supported_formats:
            raise HTTPException(status_code=400, detail=f"Detected audio format '{actual_format}' is not supported. Supported: {supported_formats}")
        
        # Warn if client format claim doesn't match reality
        if request.audio_data.format != actual_format:
            print(f"⚠️ Format mismatch: Client claimed '{request.audio_data.format}' but detected '{actual_format}'. Using detected format.")

        # Create voice clone using multiple voice clones model (replaces active one)
        print(f"🎤 Creating new voice clone with Cartesia...")
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=request.voice_name,
            audio_data=audio_bytes,
            description=request.description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ Voice clone updated and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone updated successfully",
            "voice_clone": voice_clone_data,
            "voice_name": request.voice_name,
            "user_id": user_id,
            "audio_format": request.audio_data.format,
            "audio_size_bytes": request.audio_data.size_bytes,
            "operation": "replace"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Voice clone update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")

@router.get("/voice-clone/status")
async def get_voice_clone_status(firebase_token: str, db: AsyncSession = Depends(get_session)):
    """Get the user's voice clone status"""
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        # Get user profile
        user_profile = await user_service.get_user_profile(db, user_id)
        if not user_profile:
            raise HTTPException(status_code=404, detail="User profile not found")
        
        # Check for voice clone using the same method as create/update endpoints
        cartesia_service = CartesiaService()
        voice_clone_id = await cartesia_service.get_user_voice_id(user_id, use_cloned_voice=True)
        
        if voice_clone_id == cartesia_service.default_voice_id:
            return {
                "success": True,
                "has_voice_clone": False,
                "message": "No voice clone found",
                "user_id": user_id
            }
        
        # Check voice clone status with Cartesia
        cartesia_service = CartesiaService()
        voice_info = await cartesia_service.get_voice_info(voice_clone_id)
        
        return {
            "success": True,
            "has_voice_clone": True,
            "voice_clone_id": voice_clone_id,
            "voice_info": voice_info,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Voice clone status check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get voice clone status: {str(e)}")


# ===============================
# ROBUST VOICE CLONE ENDPOINTS
# ===============================

@router.post("/voice-clone/create-multipart")
async def create_voice_clone_multipart(
    firebase_token: str = Form(...),
    voice_name: str = Form(...),
    description: str = Form(None),
    audio_file: UploadFile = File(...),
    labels: Optional[str] = Form(None),  # JSON string: {"age": "child", "language": "english", "accent": "british"}
    remove_background_noise: Optional[str] = Form("true")  # "true" or "false" as string
):
    """
    Create voice clone using multipart form data (ROBUST FORMAT)
    
    This is the recommended format for stability - no large JSON payloads.
    
    Args:
        firebase_token: Firebase authentication token
        voice_name: Name for the voice clone
        description: Optional description for the voice clone
        audio_file: Audio file (WAV, MP3, FLAC, M4A, OGG)
        labels: Optional JSON string with labels, e.g. '{"age": "child", "language": "english", "accent": "british"}'
        remove_background_noise: "true" or "false" (default: "true")
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"🔄 Creating voice clone (multipart) for user {user_id}")
        print(f"📝 Voice name: {voice_name}")
        print(f"📄 Description: {description}")
        print(f"🎵 Audio file: {audio_file.filename} ({audio_file.content_type})")
        
        # Parse labels if provided
        labels_dict = None
        if labels:
            try:
                labels_dict = json.loads(labels)
                print(f"🏷️  Labels: {labels_dict}")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid labels format. Must be valid JSON string.")
        
        # Parse remove_background_noise
        remove_noise = remove_background_noise.lower() == "true" if remove_background_noise else True
        print(f"🔇 Remove background noise: {remove_noise}")
        
        # Validate audio file
        if not audio_file:
            raise HTTPException(status_code=400, detail="Audio file is required")
        
        # Read audio data
        audio_data = await audio_file.read()
        file_size = len(audio_data)
        
        print(f"📊 Audio size: {file_size} bytes")
        
        # Validate file size (max 25MB)
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        # Minimum size check (at least 1KB)
        if file_size < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Detect actual audio format
        detected_format, content_type = cartesia_service._detect_audio_format(audio_data)
        print(f"🔍 Detected audio format: {detected_format}")
        
        # Validate supported format
        supported_formats = ['wav', 'mp3', 'flac', 'm4a', 'ogg']
        if detected_format not in supported_formats:
            raise HTTPException(status_code=400, detail=f"Audio format '{detected_format}' not supported. Supported: {supported_formats}")
        
        # Create voice clone using new multiple voice clones model
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=voice_name,
            audio_data=audio_data,
            description=description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ Voice clone created and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone created successfully",
            "voice_clone": voice_clone_data,
            "voice_name": voice_name,
            "user_id": user_id,
            "audio_format": detected_format,
            "audio_size_bytes": file_size
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Multipart voice clone creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")


@router.put("/voice-clone/update-multipart")
async def update_voice_clone_multipart(
    firebase_token: str = Form(...),
    voice_name: str = Form(...),
    description: str = Form(None),
    audio_file: UploadFile = File(...),
    labels: Optional[str] = Form(None),  # JSON string: {"age": "child", "language": "english", "accent": "british"}
    remove_background_noise: Optional[str] = Form("true")  # "true" or "false" as string
):
    """
    Update voice clone using multipart form data (ROBUST FORMAT)
    
    This replaces the old voice clone with a new one.
    
    Args:
        firebase_token: Firebase authentication token
        voice_name: Name for the new voice clone
        description: Optional description for the voice clone
        audio_file: Audio file (WAV, MP3, FLAC, M4A, OGG)
        labels: Optional JSON string with labels, e.g. '{"age": "child", "language": "english", "accent": "british"}'
        remove_background_noise: "true" or "false" (default: "true")
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"🔄 Updating voice clone (multipart) for user {user_id}")
        print(f"📝 New voice name: {voice_name}")
        print(f"📄 Description: {description}")
        print(f"🎵 Audio file: {audio_file.filename} ({audio_file.content_type})")
        
        # Parse labels if provided
        labels_dict = None
        if labels:
            try:
                labels_dict = json.loads(labels)
                print(f"🏷️  Labels: {labels_dict}")
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid labels format. Must be valid JSON string.")
        
        # Parse remove_background_noise
        remove_noise = remove_background_noise.lower() == "true" if remove_background_noise else True
        print(f"🔇 Remove background noise: {remove_noise}")
        
        # Validate audio file
        if not audio_file:
            raise HTTPException(status_code=400, detail="Audio file is required")
        
        # Read audio data
        audio_data = await audio_file.read()
        file_size = len(audio_data)
        
        print(f"📊 Audio size: {file_size} bytes")
        
        # Validate file size (max 25MB)
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        # Minimum size check
        if file_size < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Detect audio format
        detected_format, content_type = cartesia_service._detect_audio_format(audio_data)
        print(f"🔍 Detected audio format: {detected_format}")
        
        # Validate supported format
        supported_formats = ['wav', 'mp3', 'flac', 'm4a', 'ogg']
        if detected_format not in supported_formats:
            raise HTTPException(status_code=400, detail=f"Audio format '{detected_format}' not supported. Supported: {supported_formats}")
        
        # Create new voice clone using multiple voice clones model (replaces active one)
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=voice_name,
            audio_data=audio_data,
            description=description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ Voice clone updated and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone updated successfully",
            "voice_clone": voice_clone_data,
            "voice_name": voice_name,
            "user_id": user_id,
            "audio_format": detected_format,
            "audio_size_bytes": file_size,
            "operation": "replace"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Multipart voice clone update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")


from pydantic import BaseModel

class SimpleVoiceCloneRequest(BaseModel):
    firebase_token: str
    voice_name: str
    description: Optional[str] = None
    audio_base64: str
    audio_format: str
    labels: Optional[Dict[str, str]] = None  # {"age": "child", "language": "english", "accent": "british"}
    remove_background_noise: Optional[bool] = True

@router.post("/voice-clone/create-simple")
async def create_voice_clone_simple(request: SimpleVoiceCloneRequest):
    """
    Create voice clone using simplified JSON format (FALLBACK FORMAT)
    
    Simpler than the complex AudioData format, but still uses JSON.
    
    Request body:
    {
        "firebase_token": "...",
        "voice_name": "Millie's Voice",
        "description": "Child voice for storytelling",
        "audio_base64": "base64_encoded_audio...",
        "audio_format": "wav",
        "labels": {"age": "child", "language": "english", "accent": "british"},
        "remove_background_noise": true
    }
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 Creating voice clone (simple JSON) for user {user_id}")
        print(f"📝 Voice name: {request.voice_name}")
        print(f"📄 Description: {request.description}")
        print(f"🎵 Audio format: {request.audio_format}")
        
        if request.labels:
            print(f"🏷️  Labels: {request.labels}")
        print(f"🔇 Remove background noise: {request.remove_background_noise}")
        
        # Decode base64 audio
        try:
            audio_data = base64.b64decode(request.audio_base64)
            file_size = len(audio_data)
            print(f"✅ Decoded audio: {file_size} bytes")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio data: {str(e)}")
        
        # Validate file size
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        if file_size < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Detect actual format
        detected_format, _ = cartesia_service._detect_audio_format(audio_data)
        print(f"🔍 Client format: {request.audio_format}, Detected: {detected_format}")
        
        # Create voice clone using multiple voice clones model
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=request.voice_name,
            audio_data=audio_data,
            description=request.description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ Voice clone created and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone created successfully",
            "voice_clone": voice_clone_data,
            "voice_name": request.voice_name,
            "user_id": user_id,
            "audio_format": detected_format,
            "audio_size_bytes": file_size
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Simple voice clone creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")


@router.put("/voice-clone/update-simple")
async def update_voice_clone_simple(request: SimpleVoiceCloneRequest):
    """
    Update voice clone using simplified JSON format (FALLBACK FORMAT)
    
    Request body:
    {
        "firebase_token": "...",
        "voice_name": "Millie's Voice",
        "description": "Child voice for storytelling",
        "audio_base64": "base64_encoded_audio...",
        "audio_format": "wav",
        "labels": {"age": "child", "language": "english", "accent": "british"},
        "remove_background_noise": true
    }
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 Updating voice clone (simple JSON) for user {user_id}")
        print(f"📝 Voice name: {request.voice_name}")
        print(f"📄 Description: {request.description}")
        print(f"🎵 Audio format: {request.audio_format}")
        
        if request.labels:
            print(f"🏷️  Labels: {request.labels}")
        print(f"🔇 Remove background noise: {request.remove_background_noise}")
        
        # Decode base64 audio
        try:
            audio_data = base64.b64decode(request.audio_base64)
            file_size = len(audio_data)
            print(f"✅ Decoded audio: {file_size} bytes")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 audio data: {str(e)}")
        
        # Validate file size
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        if file_size < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Initialize Cartesia service
        cartesia_service = CartesiaService()
        
        # Detect actual format
        detected_format, _ = cartesia_service._detect_audio_format(audio_data)
        print(f"🔍 Client format: {request.audio_format}, Detected: {detected_format}")
        
        # Create new voice clone using multiple voice clones model (replaces active one)
        voice_clone_data = await cartesia_service.create_voice_clone_multiple(
            user_id=user_id,
            voice_name=request.voice_name,
            audio_data=audio_data,
            description=request.description
        )
        
        if not voice_clone_data:
            raise HTTPException(status_code=500, detail="Failed to create voice clone")
        
        # Set as active voice clone automatically
        voice_clone_id = voice_clone_data.get('voice_clone_id')
        await cartesia_service.set_active_voice_clone(user_id, voice_clone_id)
        print(f"✅ Voice clone updated and set as active: {voice_clone_id}")
        
        # Convert datetime to ISO string
        if 'created_at' in voice_clone_data and hasattr(voice_clone_data['created_at'], 'isoformat'):
            voice_clone_data['created_at'] = voice_clone_data['created_at'].isoformat()
        if 'updated_at' in voice_clone_data and hasattr(voice_clone_data['updated_at'], 'isoformat'):
            voice_clone_data['updated_at'] = voice_clone_data['updated_at'].isoformat()
        
        return {
            "success": True,
            "message": "Voice clone updated successfully",
            "voice_clone": voice_clone_data,
            "voice_name": request.voice_name,
            "user_id": user_id,
            "audio_format": detected_format,
            "audio_size_bytes": file_size,
            "operation": "replace"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Simple voice clone update failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")


# ============================================================================
# MULTIPLE VOICE CLONES ENDPOINTS
# ============================================================================

from src.user.schema import (
    VoiceCloneListRequest,
    VoiceCloneSetActiveRequest,
    VoiceCloneDeleteRequest,
    VoicePreviewRequest
)

@router.post("/voice-clones/list")
async def get_user_voice_clones(
    request: VoiceCloneListRequest, 
    db: AsyncSession = Depends(get_session),
    authorization: Optional[str] = Header(None)
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


@router.post("/voice-clones/set-active")
async def set_active_voice_clone(request: VoiceCloneSetActiveRequest, db: AsyncSession = Depends(get_session)):
    """
    Set the active voice clone for a user in PostgreSQL
    
    Request body:
    {
        "firebase_token": "...",
        "voice_clone_id": "vc_abc123"  // or "default" for default voice
    }
    """
    try:
        # Verify Firebase token
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        voice_clone_id = request.voice_clone_id if request.voice_clone_id != "default" else None
        
        print(f"🎤 Setting active voice clone for user {firebase_user_id}: {voice_clone_id}")
        
        if voice_clone_id is None:
            # Deactivate all voice clones to use default
            all_clones = await voice_clone_service_pg.get_user_voice_clones(db, firebase_user_id)
            for clone in all_clones:
                if clone['is_active']:
                    await voice_clone_service_pg.update_voice_clone(
                        db, clone['voice_clone_id'], firebase_user_id, is_active=False
                    )
            voice_type = "default"
        else:
            # Convert to int
            try:
                voice_clone_id_int = int(voice_clone_id)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="Invalid voice_clone_id format")
            
            # Deactivate all other voice clones and activate the target
            all_clones = await voice_clone_service_pg.get_user_voice_clones(db, firebase_user_id)
            for clone in all_clones:
                is_target = clone['voice_clone_id'] == voice_clone_id_int
                if clone['is_active'] != is_target:
                    await voice_clone_service_pg.update_voice_clone(
                        db, clone['voice_clone_id'], firebase_user_id, is_active=is_target
                    )
            voice_type = "custom"
        
        return {
            "success": True,
            "message": f"Active voice set to {voice_type} voice in PostgreSQL",
            "active_voice_clone_id": voice_clone_id,
            "user_id": firebase_user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to set active voice: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set active voice: {str(e)}")


@router.post("/voice-clones/delete")
async def delete_voice_clone(request: VoiceCloneDeleteRequest, db: AsyncSession = Depends(get_session)):
    """
    Delete a specific voice clone from PostgreSQL and Cartesia
    
    Request body:
    {
        "firebase_token": "...",
        "voice_clone_id": "123"
    }
    """
    try:
        # Verify Firebase token
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🗑️ Deleting voice clone {request.voice_clone_id} for user {firebase_user_id}")
        
        # Convert voice_clone_id to int
        try:
            voice_clone_id = int(request.voice_clone_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid voice_clone_id format")
        
        # Get voice clone data before deleting (to get Cartesia voice ID)
        voice_clone = await voice_clone_service_pg.get_voice_clone_by_id(db, voice_clone_id, firebase_user_id)
        
        if not voice_clone:
            raise HTTPException(status_code=404, detail="Voice clone not found")
        
        # Delete from Cartesia (optional - may want to keep for backup)
        cartesia_service = CartesiaService()
        try:
            await cartesia_service.delete_voice(voice_clone['voice_id'])
            print(f"✅ Deleted from Cartesia: {voice_clone['voice_id']}")
        except Exception as e:
            print(f"⚠️ Could not delete from Cartesia: {e}")
        
        # Delete from PostgreSQL
        success = await voice_clone_service_pg.delete_voice_clone(db, voice_clone_id, firebase_user_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete voice clone from database")
        
        return {
            "success": True,
            "message": "Voice clone deleted successfully from PostgreSQL",
            "voice_clone_id": voice_clone_id,
            "user_id": firebase_user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to delete voice clone: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete voice clone: {str(e)}")


@router.post("/voice-clones/preview")
async def preview_voice(request: VoicePreviewRequest):
    """
    Generate a preview audio sample for a voice
    
    Request body:
    {
        "firebase_token": "...",
        "voice_clone_id": "vc_abc123" or "default",
        "preview_text": "Custom preview text (optional)"
    }
    
    Returns audio/mpeg binary data
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)

        voice_id = request.voice_clone_id
        text = request.preview_text or "Hello! This is a preview of my voice."

        print(f"🎙️ Generating voice preview for voice {voice_id}")

        cartesia_service = CartesiaService()

        # Resolve actual Cartesia voice ID
        actual_voice_id = voice_id
        if voice_id == "default":
            actual_voice_id = cartesia_service.default_voice_id
        elif voice_id.startswith("vc_"):
            voice_clones = await cartesia_service.get_user_voice_clones(user_id)
            for clone in voice_clones:
                if clone.get('voice_clone_id') == voice_id:
                    actual_voice_id = clone.get('voice_id')
                    break

        # Generate preview audio with boosted volume for audibility
        audio_data = await cartesia_service.generate_voice_preview(
            actual_voice_id,
            text,
            volume_gain=1.6
        )

        if not audio_data:
            raise HTTPException(status_code=500, detail="Failed to generate voice preview")

        # Return audio as binary response
        from fastapi.responses import Response
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"inline; filename=voice_preview_{voice_id[:8]}.mp3"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to generate voice preview: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate voice preview: {str(e)}")


@router.post("/voice-clones/create")
async def create_new_voice_clone(request: VoiceCloneCreate, db: AsyncSession = Depends(get_session)):
    """
    Create a new voice clone using Cartesia and save to PostgreSQL
    
    Request body:
    {
        "firebase_token": "...",
        "voice_name": "Dad's Voice",
        "description": "Father's voice for storytelling",
        "audio_data": {
            "base64": "...",
            "format": "wav",
            "mime_type": "audio/wav",
            "size_bytes": 123456,
            ...
        }
    }
    """
    try:
        # Verify Firebase token
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🎤 Creating new voice clone for user {firebase_user_id}")
        print(f"📝 Voice name: {request.voice_name}")
        print(f"📄 Description: {request.description}")
        
        # Decode audio data
        audio_bytes = base64.b64decode(request.audio_data.base64)
        print(f"✅ Decoded audio: {len(audio_bytes)} bytes")
        
        # Validate file size
        if len(audio_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        if len(audio_bytes) < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Create voice clone with Cartesia API
        cartesia_service = CartesiaService()
        
        cartesia_voice_id = await cartesia_service.clone_voice_from_audio(
            audio_data=audio_bytes,
            user_id=firebase_user_id,
            voice_name=request.voice_name,
            description=request.description
        )
        
        if not cartesia_voice_id:
            raise HTTPException(status_code=500, detail="Failed to create voice clone with Cartesia")
        
        print(f"✅ Cartesia voice created: {cartesia_voice_id}")
        
        # Save to PostgreSQL
        voice_clone_data = await voice_clone_service_pg.create_voice_clone(
            db=db,
            firebase_user_id=firebase_user_id,
            name=request.voice_name,
            cartesia_voice_id=cartesia_voice_id,
            description=request.description,
            language="en"
        )
        
        return {
            "success": True,
            "message": "Voice clone created successfully in PostgreSQL",
            "voice_clone": voice_clone_data,
            "user_id": firebase_user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to create voice clone: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")


@router.put("/voice-clones/{voice_clone_id}/update")
async def update_existing_voice_clone(
    voice_clone_id: str,
    request: VoiceCloneUpdate
):
    """
    Update an existing voice clone with new audio
    
    Request body:
    {
        "firebase_token": "...",
        "voice_clone_id": "vc_abc123",
        "voice_name": "Dad's Voice Updated",
        "description": "Updated father's voice",
        "audio_data": {
            "base64": "...",
            ...
        }
    }
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 Updating voice clone {voice_clone_id} for user {user_id}")
        
        # Decode audio data
        audio_bytes = base64.b64decode(request.audio_data.base64)
        print(f"✅ Decoded audio: {len(audio_bytes)} bytes")
        
        # Validate file size
        if len(audio_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        if len(audio_bytes) < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Update voice clone
        cartesia_service = CartesiaService()
        
        success = await cartesia_service.update_voice_clone_by_id(
            user_id=user_id,
            voice_clone_id=voice_clone_id,
            voice_name=request.voice_name,
            audio_data=audio_bytes,
            description=request.description
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Voice clone not found or update failed")
        
        return {
            "success": True,
            "message": "Voice clone updated successfully",
            "voice_clone_id": voice_clone_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to update voice clone: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")


@router.post("/voice-clones/update/{voice_clone_id}")
async def update_voice_clone_by_id(
    voice_clone_id: str,
    request: VoiceCloneUpdate
):
    """
    POST endpoint for updating an existing voice clone (client compatibility)
    Delegates to the same logic as the PUT endpoint above.
    
    This endpoint matches the path pattern that clients are using:
    POST /users/voice-clones/update/{voice_clone_id}
    """
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        print(f"🔄 POST: Updating voice clone {voice_clone_id} for user {user_id}")
        
        # Decode audio data
        audio_bytes = base64.b64decode(request.audio_data.base64)
        print(f"✅ Decoded audio: {len(audio_bytes)} bytes")
        
        # Validate file size
        if len(audio_bytes) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Audio file too large (max 25MB)")
        
        if len(audio_bytes) < 1024:
            raise HTTPException(status_code=400, detail="Audio file too small (min 1KB)")
        
        # Update voice clone
        cartesia_service = CartesiaService()
        
        success = await cartesia_service.update_voice_clone_by_id(
            user_id=user_id,
            voice_clone_id=voice_clone_id,
            voice_name=request.voice_name,
            audio_data=audio_bytes,
            description=request.description
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Voice clone not found or update failed")
        
        return {
            "success": True,
            "message": "Voice clone updated successfully",
            "voice_clone_id": voice_clone_id,
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ POST: Failed to update voice clone: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update voice clone: {str(e)}")


@router.post("/upload-image", response_model=Dict[str, Any])
async def upload_image(
    file: UploadFile = File(...),
    firebase_token: str = Form(...)
):
    """
    Upload an image to Firebase Storage
    
    This is a generic image upload endpoint that can be used for:
    - Profile images
    - Reference images
    - Any other user-related images
    
    The image will be stored in: temp_uploads/{user_id}/{filename}
    """
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Validate file is an image
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Expected image, got {file.content_type}"
            )
        
        # Read file data
        image_data = await file.read()
        
        # Validate file size (min 1KB, max 10MB)
        if len(image_data) < 1024:
            raise HTTPException(status_code=400, detail="Image file too small (min 1KB)")
        
        if len(image_data) > 10 * 1024 * 1024:  # 10MB
            raise HTTPException(status_code=400, detail="Image file too large (max 10MB)")
        
        # Upload to Firebase Storage
        from src.common_function.storage_service import StorageService
        storage_service = StorageService()
        
        # Create filename with timestamp to avoid collisions
        from datetime import datetime
        timestamp = int(datetime.utcnow().timestamp())
        file_extension = file.filename.split('.')[-1] if '.' in file.filename else 'jpg'
        filename = f"temp_uploads/{user_id}/{timestamp}.{file_extension}"
        
        image_url = await storage_service.upload_image(
            image_data=image_data,
            filename=filename,
            content_type=file.content_type
        )
        
        return {
            "success": True,
            "message": "Image uploaded successfully",
            "image_url": image_url,
            "filename": file.filename,
            "size_bytes": len(image_data),
            "content_type": file.content_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to upload image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")