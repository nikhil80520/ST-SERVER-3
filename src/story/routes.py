# ===== STORY ROUTES MODULE =====
# This module serves as an ORCHESTRATION LAYER for story generation
# 
# Architecture:
#   routes.py (THIS FILE) - Orchestrates multiple services, handles HTTP requests/responses
#       ↓
#   service_pg.py (StoryService) - Database operations for story metadata (PostgreSQL + S3)
#   service.py (StoryService) - Story generation logic (OpenAI integration)
#   ParallelStoryService - Parallel media processing (images + audio)
#   MediaService - Image and audio generation
#   SQSQueueService - AWS SQS/Lambda job submission
#   WebSocketManager - Real-time notifications
#
# Note: Story generation is complex multi-service orchestration.
# Heavy business logic is in dedicated service classes, not in routes.
# Routes coordinate services and handle HTTP layer concerns.

import asyncio
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import APIRouter, HTTPException, Depends, Response, Query, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.story.schema import StoryPromptRequest, SystemPromptUpdate
from src.user.schema import User
from src.story.service import StoryService
from src.story.service_pg import story_service  # PostgreSQL story metadata service
from src.story.story_persistence_service import story_persistence_service  # Story persistence
from src.common_function.media_service import MediaService
from src.common_function.storage_s3_service import S3StorageService as StorageService
from src.user.service_pg import user_service
from src.db import get_session  # PostgreSQL session dependency
from src.auth.service import AuthService
from src.common_function.parallel_story_service import ParallelStoryService
from src.dependencies import (
    verify_firebase_token,
    verify_firebase_token_from_header,
    optional_security,
    require_story_creation_access,  # Account status validation
    require_active_account,
    get_user_with_status
)
from src.common_function.helpers import calculate_audio_duration
from src.common_function.async_utils import get_or_create_event_loop
from openai import OpenAI
from src.core.config import settings
from src.auth.schema import TokenVerificationRequest
router = APIRouter(prefix="/stories", tags=["stories"])

MAX_STORY_REFERENCE_IMAGES = 2

# Initialize services with OpenAI client
def get_user_service():
    from src.user.service_pg import UserService
    return UserService()

def get_auth_service():
    return AuthService()

def get_openai_client():
    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0  # 60 second timeout for all OpenAI API calls
    )

def get_story_service(
    openai_client: OpenAI = Depends(get_openai_client),
    user_service_dep = Depends(get_user_service),
    db: AsyncSession = Depends(get_session)
):
    return StoryService(openai_client, user_service_dep, db)

def get_media_service(openai_client: OpenAI = Depends(get_openai_client)):
    return MediaService(openai_client)

def get_storage_service():
    return StorageService()

def get_parallel_story_service(
    story_service: StoryService = Depends(get_story_service),
    media_service: MediaService = Depends(get_media_service),
    storage_service: StorageService = Depends(get_storage_service)
):
    return ParallelStoryService(story_service, media_service, storage_service)

def add_cors_headers(response: Response):
    """Add CORS headers to response"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"

# ===== STORY GENERATION (Orchestration of multiple services) =====

async def process_scenes_parallel_optimized(
    scenes,
    story_id,
    media_service,
    storage_service,
    user_profile=None,
    isfemale=True,
    target_dimensions=(1024, 1024),
    user_id=None,
    use_cloned_voice=True,
    language="english",
    art_style: str = None,
    reference_image_urls: Optional[List[str]] = None,
    voice_clone_id: str = None,
    reference_image_id_to_url_map: Optional[Dict[str, str]] = None  # NEW: Map ref_id -> URL
):
    """Process all scenes in parallel with batch audio AND batch image generation"""
    width, height = target_dimensions
    print(f"🎛️ Processing {len(scenes)} scenes at {width}x{height} in {language}")
    
    # Extract child information
    child_info = user_profile.get('child', {}) if user_profile else {}
    child_name = child_info.get('name', 'the child')
    child_image_url = child_info.get('image_url')
    
    # Prepare batch data
    scene_texts = [{"text": scene.text, "scene_number": scene.scene_number} for scene in scenes]
    # Include art_style explicitly so media_service can apply style-specific instructions
    # NEW: Resolve per-scene reference image URLs from scene.reference_image_ids
    visual_prompts = []
    for scene in scenes:
        per_scene_ref_urls = []
        if reference_image_id_to_url_map and scene.reference_image_ids:
            # Map scene's reference IDs to URLs
            per_scene_ref_urls = [
                reference_image_id_to_url_map[ref_id]
                for ref_id in scene.reference_image_ids
                if ref_id in reference_image_id_to_url_map
            ]
            # Minimal per-scene ref image note
            if per_scene_ref_urls:
                print(f"🖼️ Scene {scene.scene_number}: {len(per_scene_ref_urls)} reference image(s)")
        
        visual_prompts.append({
            "visual_prompt": scene.visual_prompt,
            "scene_number": scene.scene_number,
            "includes_child": scene.includes_child,
            "child_name": child_name,
            "child_image_url": child_image_url,
            "art_style": art_style,
            "reference_image_urls": per_scene_ref_urls  # Per-scene URLs only!
        })
    
    # Generate media in parallel
    print(f"⚡ Generating audio and images in parallel...")
    audio_batch, image_batch = await asyncio.gather(
        media_service.generate_audio_batch(scene_texts, isfemale=isfemale, user_id=user_id, use_cloned_voice=use_cloned_voice, prefer_voice_consistency=True, language=language, voice_clone_id=voice_clone_id),
        media_service.generate_image_batch(visual_prompts, child_image_url, target_dimensions)  # visual_prompts now contain per-scene reference_image_urls
    )
    
    # Upload all files in parallel
    print(f"☁️ Uploading {len(audio_batch)} audio + {len(image_batch)} images...")
    upload_tasks = []
    for i, scene in enumerate(scenes):
        upload_tasks.extend([
            storage_service.upload_audio(audio_batch[i], story_id, scene.scene_number),
            storage_service.upload_scene_image(image_batch[i], story_id, scene.scene_number)
        ])
    
    upload_results = await asyncio.gather(*upload_tasks)
    
    # Process results
    processed_scenes = []
    for i, scene in enumerate(scenes):
        audio_url = upload_results[i * 2]
        image_url = upload_results[i * 2 + 1]
        audio_duration = calculate_audio_duration(scene.text)
        
        scene.audio_url = audio_url
        scene.image_url = image_url
        scene.start_time = 0
        
        processed_scenes.append((scene, audio_duration))
    
    print(f"✅ {len(processed_scenes)} scenes processed in parallel")
    return processed_scenes
#--using in frontend app----
@router.post("/generate")
async def generate_story_async(
    request: StoryPromptRequest,
    response: Response,
    db: AsyncSession = Depends(get_session),
    story_service: StoryService = Depends(get_story_service),
    media_service: MediaService = Depends(get_media_service),
    storage_service: StorageService = Depends(get_storage_service),
    user_service_dep = Depends(get_user_service)
):
    """
    Start story generation asynchronously and return story_id immediately
    
    Requires: Active subscription or trial (returns 402 if trial expired/suspended)
    """
    add_cors_headers(response)
    
    try:
        # Verify token from request body (not header)
        if not request.firebase_token:
            raise HTTPException(status_code=401, detail="Firebase token is required")
        
        user_id = await verify_firebase_token(request.firebase_token)
        print(f"👤 Verified user from request body token: {user_id}")
        
        # Check account status for story creation access
        from src.user.account_status_service import account_status_service
        account_status = await account_status_service.get_account_status(user_id)
        error = account_status_service.get_http_error_for_status(account_status, "create_story")
        if error:
            print(f"❌ Account status check failed for user {user_id}: {error.detail}")
            raise error
        
        print(f"✅ Account status validated for user {user_id}")
        
        # Minimal request context (avoid dumping full payload)
        prompt_len = len(request.prompt) if request.prompt else 0
        print(f"📥 Request received: prompt_len={prompt_len}, refs={len(request.reference_image_ids or [])}, child={request.child_name or 'auto'}")
        
        # Fetch user profile to auto-populate missing fields
        user_profile = await user_service.get_user_profile(db, user_id)
        child_data = user_profile.get('child', {}) if user_profile else {}

        # Resolve parent-centric child selection: request.child_id overrides default child
        child_id = request.child_id if getattr(request, 'child_id', None) else user_profile.get('default_child_id') if user_profile else None
        child_snapshot = None
        if child_id:
            # If explicit child_id was provided and invalid, surface an error
            from src.children.service_pg import child_service_pg
            # Convert firebase_user_id to integer user_id for ORM query
            integer_user_id = await user_service._get_user_id_from_firebase_id(db, user_id)
            
            if integer_user_id:
                child_obj = await child_service_pg.get_child(db, user_id, child_id)
                if not child_obj:
                    # If the request explicitly asked for a child that doesn't belong to the user, fail
                    if getattr(request, 'child_id', None):
                        raise HTTPException(status_code=404, detail=f"Child profile not found: {request.child_id}")
                    # Otherwise continue without child snapshot
                else:
                    child_snapshot = child_obj.dict()

        # Legacy fallback: if no child snapshot found use the old single-child profile if available
        if not child_snapshot and user_profile and user_profile.get('child'):
            child_snapshot = user_profile.get('child')

        print(f"👶 Resolved child data: id={child_id}, snapshot_present={bool(child_snapshot)}")
        
        # Resolve reference images requested for this story
        reference_image_ids = request.reference_image_ids or []
        reference_image_urls: List[str] = []
        reference_images_metadata: List[Dict] = []  # NEW: Full metadata for OpenAI prompt
        if reference_image_ids:
            print(f"📸 Reference images requested: {len(reference_image_ids)} image(s)")
            if len(reference_image_ids) > MAX_STORY_REFERENCE_IMAGES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Maximum {MAX_STORY_REFERENCE_IMAGES} reference images allowed per story"
                )
            available_refs = {}
            if user_profile and user_profile.get('reference_images'):
                available_refs = {
                    ref.get('reference_image_id'): ref
                    for ref in user_profile['reference_images']
                    if ref.get('reference_image_id')
                }
            missing_ids = []
            for ref_id in reference_image_ids:
                ref_entry = available_refs.get(ref_id)
                image_url = ref_entry.get('image_url') if ref_entry else None
                if image_url:
                    if image_url not in reference_image_urls:
                        reference_image_urls.append(image_url)
                        reference_images_metadata.append(ref_entry)  # NEW: Store full metadata
                        # Reference image captured (details suppressed for brevity)
                else:
                    missing_ids.append(ref_id)
            if missing_ids:
                missing_str = ", ".join(missing_ids)
                raise HTTPException(
                    status_code=404,
                    detail=f"Reference image(s) not found for ID(s): {missing_str}"
                )
            print(f"📸 Using {len(reference_image_urls)} reference image(s) for story generation")
            print(f"🎨 These images will guide character appearance in all story scenes")

        # Import background services here to avoid circular imports
        from src.common_function.story_websocket_manager import story_websocket_manager
        from src.background_process.sqs_queue_service import sqs_queue_service
        from src.core.config import settings
        
        # Determine which processing method to use
        use_sqs = settings.aws.use_sqs_lambda if hasattr(settings, 'aws') else False
        print(f"🔧 Processing method: {'AWS SQS + Lambda' if use_sqs else 'ERROR: SQS not configured'}")
        
        # Auto-populate child_name and child_age from profile if not provided
        child_name = request.child_name or child_data.get('name')
        child_age = request.child_age or child_data.get('age')
        
        # Handle different input formats
        if request.prompt:
            # Legacy/simple format - user provides the prompt directly
            user_prompt = request.prompt
            print(f"🎬 Starting ASYNC story generation with user prompt: {user_prompt}")
            
            # Even with user_prompt, try to get child info from profile if not provided
            if not child_name:
                print(f"⚠️  No child_name in request, using profile data: {child_data.get('name', 'Child')}")
                child_name = child_data.get('name', 'Child')
            if not child_age:
                print(f"⚠️  No child_age in request, using profile data: {child_data.get('age', 6)}")
                child_age = child_data.get('age', 6)
            
            print(f"   Child: {child_name}, Age: {child_age}")
        else:
            # New structured format - generate prompt from structured data
            if not child_name:
                raise HTTPException(
                    status_code=400, 
                    detail="child_name is required. Please provide it in the request or set up your child's profile first."
                )
            
            morals_text = ", ".join(request.morals) if request.morals else "kindness, friendship"
            user_prompt = f"Create a {request.story_length or 'medium'} story for {child_name} (age {child_age or 6}) about {morals_text} in {request.art_style or 'magical'} style"
            print(f"🎬 Starting ASYNC story generation for new format: {user_prompt}")
            print(f"   Child: {child_name}, Age: {child_age}")
        
        # Extract new format fields with backward compatibility
        morals_val = request.morals if request.morals else ["friendship", "kindness"]
        story_length = request.story_length if request.story_length else "medium"
        art_style_val = request.art_style if request.art_style else "magical"
        language_val = request.language if request.language else "english"
        
        # Backward compatibility for old format
        genre_val = request.genre if request.genre else ["Adventure"]
        illustration_style_val = request.illustration_style if request.illustration_style else art_style_val
        
        # ===== CREATE INITIAL STORY RECORD IN POSTGRESQL FIRST =====
        # This generates the auto-increment integer story_id that we'll use throughout
        
        # Convert firebase_user_id to integer user_id for foreign key
        integer_user_id = await user_service._get_user_id_from_firebase_id(db, user_id)
        
        if not integer_user_id:
            raise HTTPException(status_code=404, detail="User not found in database")
        
        if not child_id:
            raise HTTPException(status_code=400, detail="child_id is required for story generation")
        
        # Create initial story record in PostgreSQL
        from src.db.models.story import Story
        initial_story = Story(
            user_id=integer_user_id,
            child_id=child_id,
            title="Generating...",
            genre=genre_val[0] if isinstance(genre_val, list) else genre_val,
            story_length=story_length,
            target_scenes=request.scene_count,
            age_group=request.age_group,
            child_name=child_name,
            child_age=child_age,
            story_theme=user_prompt,
            moral_lesson=request.moral_lesson,
            morals=', '.join(morals_val) if isinstance(morals_val, list) else morals_val,
            target_emotion=request.emotion,
            art_style=art_style_val
        )
        
        db.add(initial_story)
        await db.commit()
        await db.refresh(initial_story)
        
        # Capture the auto-generated story_id from PostgreSQL (this is an INTEGER)
        story_id = initial_story.story_id
        print(f"📖 Created initial story record in PostgreSQL: story_id={story_id} (integer)")

        # Create job parameters
        job_params = {
            "user_prompt": user_prompt,
            "user_id": user_id,
            "user_id_int": integer_user_id,  # PostgreSQL integer ID
            "child_id_int": child_id,  # PostgreSQL integer ID
            # Parent-centric child selection
            "child_id": None,  # Don't pass PostgreSQL ID to Lambda - use child_snapshot instead
            "child_snapshot": child_snapshot,  # Pass full child data to avoid Firestore lookup
            "child_name": child_name,
            "child_age": child_age,
            "morals": morals_val,
            "story_length": story_length,
            "art_style": art_style_val,
            "language": language_val,
            "target_scenes": request.scene_count,
            "voice_option": "female" if request.is_female_voice else "male",
            "dimensions": request.dimensions,
            "use_cloned_voice": request.should_use_voice_clone,
            "voice_clone_id": request.voice_clone_id,
            "reference_image_ids": reference_image_ids,
            "reference_image_urls": reference_image_urls,
            "reference_images_metadata": reference_images_metadata,  # NEW: Full metadata for OpenAI
            # NOTE: ambient_keywords will be generated dynamically by LLM per scene
            # Legacy parameters for backward compatibility
            "genre": genre_val,
            "age_group": request.age_group,
            "moral_lesson": request.moral_lesson,
            "emotion": request.emotion,
            "is_female_voice": request.is_female_voice
        }
        
        # If a specific voice_clone_id wasn't provided in the request, inherit from the child's profile when available
        if not job_params.get("voice_clone_id") and child_snapshot and isinstance(child_snapshot, dict):
            inherited_voice_clone_id = child_snapshot.get("voice_clone_id")
            if inherited_voice_clone_id:
                print(f"🎤 Inheriting child's voice_clone_id: {inherited_voice_clone_id}")
                job_params["voice_clone_id"] = inherited_voice_clone_id

        # Log job_params to verify reference images are included
        print(f"📦 Job params prepared for background service:")
        print(f"   - story_id: {story_id} (PostgreSQL auto-increment integer)")
        print(f"   - reference_image_ids: {job_params.get('reference_image_ids')}")
        print(f"   - reference_image_urls: {job_params.get('reference_image_urls')}")
        if reference_image_urls:
            print(f"   ✅ {len(reference_image_urls)} reference image URL(s) will be passed to image generation")

        # Create story generation job with callback for WebSocket notifications
        async def on_progress(job_data):
            """Callback for progress updates"""
            await story_websocket_manager.broadcast_to_user(user_id, {
                "event": "story_progress",
                "story_id": story_id,
                "status": job_data.get("status", "processing"),
                "progress": job_data.get("progress", 0),
                "message": job_data.get("message", "Processing story..."),
                "timestamp": datetime.utcnow().isoformat()
            })

        async def on_completion(job_data):
            """Callback for completion"""
            if job_data.get("status") == "completed":
                await story_websocket_manager.broadcast_to_user(user_id, {
                    "event": "story_completed",
                    "story_id": story_id,
                    "title": job_data.get("title", "Untitled Story"),
                    "message": f"Your story '{job_data.get('title', 'Untitled Story')}' is ready!",
                    "manifest": job_data.get("manifest"),
                    "timestamp": datetime.utcnow().isoformat()
                })
            else:
                await story_websocket_manager.broadcast_to_user(user_id, {
                    "event": "story_failed", 
                    "story_id": story_id,
                    "message": f"Story generation failed: {job_data.get('error', 'Unknown error')}",
                    "error": job_data.get("error"),
                    "timestamp": datetime.utcnow().isoformat()
                })

        # ===== SUBMIT JOB: AWS SQS + Lambda ONLY (No Local Fallback) =====
        # Enforce SQS-only mode for production reliability and scalability
        
        # Validate SQS configuration
        if not use_sqs or not sqs_queue_service.enabled:
            error_msg = (
                "❌ Story generation requires AWS SQS Lambda. Please configure:\n"
                "   - Set AWS_USE_SQS_LAMBDA=true\n"
                "   - Set AWS_REGION=us-east-1 (or your region)\n"
                "   - Set AWS_ACCESS_KEY_ID=<your-key>\n"
                "   - Set AWS_SECRET_ACCESS_KEY=<your-secret>\n"
                "   - Set AWS_SQS_QUEUE_URL=https://sqs.REGION.amazonaws.com/ACCOUNT/queue-name"
            )
            print(error_msg)
            raise HTTPException(
                status_code=503,
                detail="Story generation service unavailable. AWS SQS Lambda integration required. Check server logs for configuration details."
            )
        
        # Submit job to AWS SQS (cloud processing)
        print(f"📤 Submitting job to AWS SQS for Lambda processing...")
        try:
            # Add firebase_user_id to parameters for Lambda to identify user
            job_params["firebase_user_id"] = user_id
            
            job_id = await sqs_queue_service.submit_story_job(
                story_id=story_id,  # This is now an integer from PostgreSQL
                parameters=job_params,
                priority=0  # Default priority
            )
            tracking_method = "aws_sqs_lambda"
            print(f"✅ Job submitted to SQS: {job_id}")
        except Exception as e:
            print(f"❌ Failed to submit job to SQS: {str(e)}")
            raise HTTPException(
                status_code=503,
                detail=f"Failed to submit story generation job to SQS: {str(e)}"
            )
        
        # ===== COMMENTED OUT: Old SQS-only enforcement (removed to support local fallback) =====
        # # Validate SQS configuration
        # if not use_sqs or not sqs_queue_service.enabled:
        #     error_msg = (
        #         "Story generation service not available. "
        #         "AWS SQS Lambda integration is required. "
        #         "Configuration missing: Set AWS_USE_SQS_LAMBDA=true and configure "
        #         "AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SQS_QUEUE_URL"
        #     )
        #     print(f"❌ {error_msg}")
        #     raise HTTPException(
        #         status_code=503,
        #         detail=error_msg
        #     )
        # 
        # # Submit job to AWS SQS (cloud processing)
        # print(f"📤 Submitting job to AWS SQS for Lambda processing...")
        # try:
        #     # Add firebase_user_id to parameters for Lambda to identify user
        #     job_params["firebase_user_id"] = user_id
        #     
        #     job_id = await sqs_queue_service.submit_story_job(
        #         story_id=story_id,  # This is now an integer from PostgreSQL
        #         parameters=job_params,
        #         priority=0  # Default priority
        #     )
        #     tracking_method = "aws_sqs_lambda"
        #     print(f"✅ Job submitted to SQS: {job_id}")
        # except Exception as e:
        #     print(f"❌ Failed to submit job to SQS: {str(e)}")
        #     raise HTTPException(
        #         status_code=503,
        #         detail=f"Failed to submit story generation job to SQS: {str(e)}"
        #     )
        
        # ===== COMMENTED OUT: Local background workers approach =====
        # if use_sqs:
        #     # ===== NEW: AWS SQS + Lambda approach =====
        #     print(f"📤 Submitting job to AWS SQS for Lambda processing...")
        #     job_id = await sqs_queue_service.submit_story_job(
        #         story_id=story_id,
        #         parameters=job_params,
        #         priority=0  # Default priority
        #     )
        #     tracking_method = "aws_sqs_lambda"
        #     print(f"✅ Job submitted to SQS: {job_id}")
        # else:
        #     # ===== CURRENT: Local background workers approach =====
        #     print(f"📤 Submitting job to local background service...")
        #     job_id = await enhanced_background_service.submit_story_job(
        #         story_id=story_id,
        #         parameters=job_params,
        #         services={
        #             "story_service": story_service,
        #             "media_service": media_service,
        #             "storage_service": storage_service
        #         },
        #         callbacks={
        #             "on_progress": on_progress,
        #             "on_completion": on_completion
        #         }
        #     )
        #     tracking_method = "background_service_with_websocket_notifications"
        #     print(f"✅ Job submitted to background service: {job_id}")

        # ===== COMMENTED OUT: Original synchronous code (for reference) =====
        # job_id = await enhanced_background_service.submit_story_job(
        #     story_id=story_id,
        #     parameters=job_params,
        #     services={
        #         "story_service": story_service,
        #         "media_service": media_service,
        #         "storage_service": storage_service
        #     },
        #     callbacks={
        #         "on_progress": on_progress,
        #         "on_completion": on_completion
        #     }
        # )

        print(f"✅ Story generation job submitted: {job_id}")
        print(f"📋 Story ID added to user {user_id}'s story_ids array")

        return {
            "success": True,
            "message": f"Story generation started! Connect via WebSocket to receive real-time updates.",
            "story_id": story_id,
            "job_id": job_id,
            "status": "processing",
            "estimated_completion_time": "30-60 seconds",
            "websocket_endpoint": f"/ws/stories/{request.firebase_token}",
            "tracking_method": tracking_method,
            "processing_engine": "AWS Lambda + SQS" if use_sqs else "Local Background Workers"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to start story generation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start story generation: {str(e)}")

def parse_dimensions(dimensions_str: str) -> tuple:
    """Parse dimension string like '1024x1024' into tuple (1024, 1024) - FORCED TO 1024x1024"""
    # Always return 1024x1024 to ensure square images
    return (1024, 1024)

async def generate_story_background_parallel(
    story_id: str,
    user_prompt: str,
    user_id: str,
    story_service: StoryService,
    media_service: MediaService,
    storage_service: StorageService,
    isfemale: bool = True,
    dimensions: str = "1024x1024",
    child_name: str = None,
    child_age: int = None,
    morals: str = "sharing, kindness, friendship",
    story_length: str = "medium",
    art_style: str = "magical",
    target_scenes: int = 7,
    voice_option: str = "female",
    language: str = "english",
    # Legacy parameters for backward compatibility
    genre: str = "Adventure",
    age_group: str = "6-8",
    moral_lesson: str = "friendship",
    emotion: str = "happiness",
    use_cloned_voice: bool = True
):
    """Background task using the new parallel story service"""
    try:
        print(f"🚀 Starting PARALLEL story generation for story: {story_id}")
        
        # Create parallel story service
        parallel_service = ParallelStoryService(story_service, media_service, storage_service)
        
        # Generate story with parallel processing
        manifest = await parallel_service.generate_story_parallel(
            story_id=story_id,
            user_prompt=user_prompt,
            user_id=user_id,
            target_scenes=target_scenes,
            child_name=child_name,
            child_age=child_age,
            morals=morals if isinstance(morals, list) else [morals] if morals else ["kindness", "friendship"],
            story_length=story_length,
            art_style=art_style,
            voice_option=voice_option,
            dimensions=dimensions,
            use_cloned_voice=use_cloned_voice,
            language=language,
            # Legacy parameters
            genre=genre,
            age_group=age_group,
            moral_lesson=moral_lesson,
            emotion=emotion
        )
        
        print(f"✅ PARALLEL story generation completed: {story_id}")
        print(f"📊 Performance metrics: {manifest.get('performance_metrics', {})}")
        
    except Exception as e:
        print(f"❌ PARALLEL story generation failed for {story_id}: {str(e)}")
        # The parallel service handles error reporting internally
        raise

async def generate_story_background(
    story_id: str,
    prompt: str,
    user_id: str,
    db: AsyncSession,  # Database session for user profile queries
    story_service: StoryService,
    media_service: MediaService,
    storage_service: StorageService,
    isfemale: bool = True,
    dimensions: str = "1024x1024",
    child_name: str = None,
    child_age: int = None,
    morals: str = "sharing, kindness, friendship",
    story_length: str = "medium",
    art_style: str = "magical",
    language: str = "english",
    target_scenes: int = 7,
    # Legacy parameters for backward compatibility
    genre: str = "Adventure",
    age_group: str = "6-8",
    moral_lesson: str = "friendship",
    emotion: str = "happiness",
    use_cloned_voice: bool = True,
    voice_clone_id: str = None,
    # NEW: Reference images metadata for character consistency
    reference_images_metadata: List[Dict] = None
    ):
    """Background task to generate the complete story with story ID array tracking"""
    try:
        print(f"🔄 Background generation started for story: {story_id}")
        print(f"🖼️ Using custom dimensions: {dimensions}")
        
        # Parse dimensions
        target_dimensions = parse_dimensions(dimensions)
        width, height = target_dimensions
        print(f"📐 Parsed dimensions: {width}x{height}")
        
        # Get user profile for child information
        user_profile = await user_service.get_user_profile(db, user_id)

        # Resolve child context for final manifest persistence (background job may have passed child_id in parameters)
        child_id = None
        child_snapshot = None
        try:
            # Prefer default_child_id on the parent profile
            child_id = user_profile.get('default_child_id') if user_profile else None
            if child_id:
                from src.children.service import child_service
                child_obj = await child_service.get_child(user_id, child_id)
                if child_obj:
                    child_snapshot = child_obj.dict()
        except Exception as e:
            print(f"⚠️ Could not resolve child snapshot in background: {e}")

        # Legacy fallback
        if not child_snapshot and user_profile and user_profile.get('child'):
            child_snapshot = user_profile.get('child')
        
        # Generate story scenes using OpenAI with enhanced parameters
        print("🤖 Generating story scenes with OpenAI...")
        print(f"📊 Target scenes: {target_scenes} (story length: {story_length})")
        print(f"🎨 Art style: {art_style}")
        print(f"💭 Morals: {morals}")
        
        # Extract reference_images_metadata from function parameter
        if reference_images_metadata:
            print(f"📸 Passing {len(reference_images_metadata)} reference image metadata entries to OpenAI")
        
        # Handle genre list - convert to string if it's a list
        genre_str = genre[0] if isinstance(genre, list) and len(genre) > 0 else str(genre) if genre else "Adventure"
        
        scenes, title, thumbnail_prompt = await story_service.generate_story_scenes(
            prompt, user_id, 
            target_scenes=target_scenes,
            child_id=child_id,
            child_name=child_name,
            child_age=child_age,
            morals=morals,
            story_length=story_length,
            art_style=art_style,
            language=language,
            reference_images_metadata=reference_images_metadata,  # NEW: Pass metadata to OpenAI
            # Legacy parameters for backward compatibility
            genre=genre_str, 
            age_group=age_group, 
            moral_lesson=moral_lesson, 
            emotion=emotion
        )
        print(f"✅ Generated {len(scenes)} scenes for story: {title} in {language}")
        print(f"🖼️ Generated thumbnail prompt: {thumbnail_prompt[:100]}...")
        
        # Build reference_image_id_to_url_map for per-scene URL resolution
        ref_id_to_url_map = {}
        if reference_images_metadata:
            ref_id_to_url_map = {
                ref.get('reference_image_id'): ref.get('image_url')
                for ref in reference_images_metadata
                if ref.get('reference_image_id') and ref.get('image_url')
            }
            print(f"🗺️ Built reference ID-to-URL map with {len(ref_id_to_url_map)} entries")
        
        # Update story with title and "generating_media" status
        await storage_service.update_story_status_and_title(story_id, "generating_media", title)
        
        # Process all scenes with FULLY optimized parallel processing
        processed_scenes_with_duration = await process_scenes_parallel_optimized(
            scenes, story_id, media_service, storage_service, user_profile, isfemale=isfemale, 
            target_dimensions=target_dimensions, user_id=user_id, use_cloned_voice=use_cloned_voice, 
            language=language, voice_clone_id=voice_clone_id,
            reference_image_id_to_url_map=ref_id_to_url_map  # NEW: Pass map for per-scene URL resolution
        )
        
        # Extract scenes and calculate timings
        processed_scenes = []
        current_time = 0
        
        for scene_result in processed_scenes_with_duration:
            if isinstance(scene_result, tuple):
                scene, duration = scene_result
            else:
                use_cloned_voice=use_cloned_voice
                scene = scene_result
                duration = calculate_audio_duration(scene.text)
            
            # Set start time
            scene.start_time = current_time
            processed_scenes.append(scene)
            current_time += duration
        
        # Generate and upload story thumbnail with robust error handling
        print("🖼️ Generating story thumbnail...")
        thumbnail_url = None
        try:
            # Get child info for thumbnail personalization
            child_info = user_profile.get('child', {}) if user_profile else {}
            child_image_url = child_info.get('image_url')
            
            # Generate thumbnail image
            thumbnail_data = await media_service.generate_story_thumbnail(
                thumbnail_prompt, story_id, child_image_url
            )
            
            # Upload thumbnail with validation
            if thumbnail_data and len(thumbnail_data) > 1000:  # Ensure valid data
                thumbnail_url = await storage_service.upload_story_thumbnail(thumbnail_data, story_id)
                print(f"✅ Story thumbnail uploaded: {thumbnail_url}")
            else:
                print(f"⚠️ Invalid thumbnail data, skipping thumbnail")
                
        except Exception as e:
            print(f"⚠️ Thumbnail generation failed, continuing without thumbnail: {str(e)}")
            # If thumbnail generation fails, use first scene image as fallback
            if processed_scenes and processed_scenes[0].image_url:
                thumbnail_url = processed_scenes[0].image_url
                print(f"📸 Using first scene image as thumbnail fallback: {thumbnail_url}")
        
        # Build comprehensive manifest with scene-wise data
        scenes_data = []
        for scene in processed_scenes:
            scene_data = {
                "scene_number": scene.scene_number,
                "text": scene.text,
                "visual_prompt": scene.visual_prompt,
                "audio_url": scene.audio_url,
                "image_url": scene.image_url,  # Main colored image
                "start_time": scene.start_time,
                "duration": calculate_audio_duration(scene.text),
                "includes_child": scene.includes_child  # Whether this scene includes the child
            }
            scenes_data.append(scene_data)
        
        # Create final manifest
        manifest = {
            "story_id": story_id,
            "title": title,
            "user_prompt": prompt,
            "genre": genre,
            "age_group": age_group,
            "moral_lesson": moral_lesson,
            "target_emotion": emotion,
            "art_style": art_style,
            "voice_option": "Eve" if isfemale else "Adam",
            "dimensions": dimensions,
            "total_scenes": len(processed_scenes),
            "total_duration": current_time,
            "thumbnail_url": thumbnail_url,  # 16:9 landscape thumbnail
            "scenes": scenes_data,
            "generated_at": "now",
            "status": "completed",
            "generation_method": "enhanced_child_safe_story_generation_with_parameters",
            "optimizations": [
                "parallel_scene_processing",
                "enhanced_child_safety",
                "genre_specific_generation", 
                "age_appropriate_content",
                "moral_lesson_integration",
                "emotion_targeted_narrative",
                "custom_art_style_support",
                "voice_option_selection",
                "batch_media_generation",
                "parallel_firebase_uploads",
                "story_id_array_tracking",
                "full_parallelization",
                "dual_image_storage_colored_and_grayscale",
                "story_thumbnail_generation"  # New optimization
            ]
        }
        
        print(f"💾 Saving completed story metadata to Firebase with ID array update...")
        # Save final story metadata (this will update the story in user's story_ids array)
        await storage_service.save_story_metadata(
            story_id, user_id, title, prompt, manifest,
            child_id=child_id, child_snapshot=child_snapshot
        )
        print(f"✅ Background story generation completed successfully: {story_id}")
        print(f"📋 Story {story_id} is now tracked in user {user_id}'s story_ids array")
        
    except Exception as e:
        print(f"❌ Background story generation failed for {story_id}: {str(e)}")
        # Update story with error status
        error_manifest = {
            "story_id": story_id,
            "title": "Generation Failed",
            "user_prompt": prompt,
            "status": "failed",
            "error": str(e),
            "generated_at": "now"
        }
        await storage_service.save_story_metadata(
            story_id, user_id, "Generation Failed", prompt, error_manifest,
            child_id=child_id, child_snapshot=child_snapshot
        )

async def cleanup_duplicate_story_ids(self, user_id: str = None):
    """Clean up duplicate story IDs in user documents"""
    try:
        if not self.db:
            return
        
        loop = get_or_create_event_loop()
        
        def cleanup():
            if user_id:
                # Clean up specific user
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    story_ids = user_data.get('story_ids', [])
                    
                    # Remove duplicates while preserving order
                    unique_story_ids = list(dict.fromkeys(story_ids))
                    
                    if len(unique_story_ids) != len(story_ids):
                        print(f"🧹 Cleaning up duplicates for user {user_id}: {len(story_ids)} -> {len(unique_story_ids)}")
                        
                        user_ref.update({
                            'story_ids': unique_story_ids,
                            'story_count': len(unique_story_ids),
                            'updated_at': datetime.utcnow()
                        })
            else:
                # Clean up all users
                users_ref = self.db.collection('users')
                users = users_ref.stream()
                
                for user_doc in users:
                    user_data = user_doc.to_dict()
                    story_ids = user_data.get('story_ids', [])
                    
                    # Remove duplicates while preserving order
                    unique_story_ids = list(dict.fromkeys(story_ids))
                    
                    if len(unique_story_ids) != len(story_ids):
                        print(f"🧹 Cleaning up duplicates for user {user_doc.id}: {len(story_ids)} -> {len(unique_story_ids)}")
                        
                        user_doc.reference.update({
                            'story_ids': unique_story_ids,
                            'story_count': len(unique_story_ids),
                            'updated_at': datetime.utcnow()
                        })
        
        await loop.run_in_executor(None, cleanup)
        print("✅ Duplicate story IDs cleanup completed")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {str(e)}")

# Add an endpoint to trigger cleanup
@router.post("/cleanup-duplicates")
async def cleanup_duplicate_story_ids_endpoint(
    request: TokenVerificationRequest,
    response: Response,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Clean up duplicate story IDs for the current user"""
    add_cors_headers(response)
    
    try:
        # Verify Firebase token
        user_id = await verify_firebase_token(request.firebase_token)
        
        await storage_service.cleanup_duplicate_story_ids(user_id)
        
        return {
            "success": True,
            "message": "Duplicate story IDs cleaned up successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@router.post("/complete/{story_id}")
async def complete_story_generation(
    story_id: str,
    story_data: Dict,
    response: Response,
    db: AsyncSession = Depends(get_session),
    user_service_dep = Depends(get_user_service)
):
    """
    Complete story generation by saving all scenes, images, and audio to PostgreSQL.
    Called by Lambda function after story generation completes.
    
    Expected story_data format:
    {
        "firebase_user_id": "...",
        "child_id": 123,
        "title": "Story Title",
        "genre": "adventure",
        "story_length": "medium",
        ... (see Story model for full schema)
        "scenes": [
            {
                "scene_number": 1,
                "text": "...",
                "visual_prompt": "...",
                "image_url": "https://...",
                "audio_url": "https://...",
                "includes_child": true,
                "emotion": "happy",
                "reference_image_ids": ["ref1", "ref2"],
                "duration": 10
            },
            ...
        ],
        "thumbnail_url": "https://..."
    }
    """
    add_cors_headers(response)
    
    try:
        print(f"📥 Received story completion for story_id: {story_id}")
        
        # Get user_id from story_data
        firebase_user_id = story_data.get("firebase_user_id")
        if not firebase_user_id:
            raise HTTPException(status_code=400, detail="firebase_user_id is required")
        
        # Convert to integer user_id
        integer_user_id = await user_service._get_user_id_from_firebase_id(db, firebase_user_id)
        if not integer_user_id:
            raise HTTPException(status_code=404, detail="User not found")
        
        child_id = story_data.get("child_id")
        if not child_id:
            raise HTTPException(status_code=400, detail="child_id is required")
        
        # Save complete story to PostgreSQL
        story = await story_persistence_service.save_complete_story(
            db=db,
            user_id=integer_user_id,
            child_id=child_id,
            story_data=story_data
        )
        
        print(f"✅ Story {story_id} completed and saved to PostgreSQL: {story.story_id}")
        
        return {
            "success": True,
            "story_id": story.story_id,
            "postgres_story_id": story.story_id,
            "title": story.title,
            "message": "Story saved successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error completing story: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to save story: {str(e)}")

@router.get("/{story_id}")
async def get_story_status(
    story_id: str,
    response: Response,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Get story status - for test scripts and general status checking"""
    add_cors_headers(response)
    
    try:
        print(f"📊 Getting story status for: {story_id}")
        
        # Get story details from Firestore
        story_details = None
        try:
            story_details = await storage_service.get_story_details(story_id)
        except HTTPException as he:
            # Convert 404 into a graceful not_found payload instead of exception bubbling that prints empty error
            if he.status_code == 404:
                print(f"🔍 Story {story_id} not found (404) – returning not_found status")
                return {"status": "not_found", "message": "Story not found"}
            raise
        
        if not story_details:
            return {
                "status": "not_found",
                "message": "Story not found"
            }
        
        story_status = story_details.get('status', 'unknown')
        
        if story_status == "completed":
            # Return the complete story data
            manifest = story_details.get('manifest', story_details)
            return {
                "status": "completed",
                "message": f"Story '{manifest.get('title', 'Unknown')}' completed successfully!",
                "manifest": manifest
            }
        else:
            return {
                "status": story_status,
                "message": f"Story status: {story_status}"
            }
            
    except Exception as e:
        # Ensure error message is never empty
        err_msg = str(e) or "Unknown error"
        print(f"❌ Error getting story status: {err_msg}")
        return {"status": "error", "message": f"Error getting story status: {err_msg}"}
#---using in frontend---
@router.get("/fetch/{story_id}")
async def fetch_story_status(
    story_id: str,
    response: Response,
    db: AsyncSession = Depends(get_session),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Fetch story status and data - for ESP32 polling. Queries PostgreSQL first."""
    add_cors_headers(response)
    
    try:
        print(f"📡 Fetching story status for: {story_id}")
        
        # Try to convert story_id to integer for PostgreSQL query
        try:
            pg_story_id = int(story_id)
        except ValueError:
            print(f"⚠️ Invalid story_id format: {story_id}, falling back to Firestore")
            pg_story_id = None
        
        # Query PostgreSQL first if story_id is numeric
        if pg_story_id:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from src.db.models.story import Story, StoryScene, StorySceneImage, StorySceneAudio
            
            try:
                # Query Story with all relationships loaded
                query = (
                    select(Story)
                    .where(Story.story_id == pg_story_id)
                    .options(
                        selectinload(Story.scenes).selectinload(StoryScene.images),
                        selectinload(Story.scenes).selectinload(StoryScene.audio)
                    )
                )
                
                result = await db.execute(query)
                story_row = result.scalars().first()
                
                if story_row:
                    print(f"✅ Story found in PostgreSQL: {pg_story_id}")
                    
                    # Build scenes data from database
                    scenes_data = []
                    total_duration = 0
                    
                    for scene in story_row.scenes:
                        # Get image data (typically one image per scene, but handle multiple)
                        image_url = None
                        visual_prompt = None
                        text = None
                        
                        if scene.images:
                            first_image = scene.images[0]
                            image_url = first_image.image_url
                            visual_prompt = first_image.visual_prompt
                            text = first_image.text
                        
                        # Get audio data (typically one audio per scene)
                        audio_url = None
                        audio_duration = 0
                        audio_text = None
                        
                        if scene.audio:
                            first_audio = scene.audio[0]
                            audio_url = first_audio.audio_url
                            audio_duration = first_audio.duration or 0
                            audio_text = first_audio.text
                        
                        scene_data = {
                            "scene_number": scene.scene_number,
                            "text": text or audio_text or "",
                            "visual_prompt": visual_prompt or "",
                            "image_url": image_url,
                            "audio_url": audio_url,
                            "includes_child": scene.includes_child,
                            "emotion": scene.emotion,
                            "reference_image_ids": scene.reference_image_ids or [],
                            "start_time": total_duration,
                            "duration": audio_duration
                        }
                        scenes_data.append(scene_data)
                        total_duration += audio_duration
                    
                    # Build complete manifest from database
                    manifest = {
                        "story_id": story_row.story_id,
                        "title": story_row.title,
                        "genre": story_row.genre,
                        "story_length": story_row.story_length,
                        "age_group": story_row.age_group,
                        "art_style": story_row.art_style,
                        "target_emotion": story_row.target_emotion,
                        "moral_lesson": story_row.moral_lesson,
                        "thumbnail_url": story_row.thumbnail_url,
                        "total_scenes": len(scenes_data),
                        "total_duration": total_duration,
                        "scenes": scenes_data,
                        "status": "completed",
                        "generated_at": story_row.created_at.isoformat() if story_row.created_at else "unknown"
                    }
                    
                    return {
                        "success": True,
                        "status": "completed",
                        "message": f"Story '{manifest.get('title', 'Unknown')}' generated successfully!",
                        "story": manifest,
                        "performance_info": {
                            "optimizations_used": ["database_optimized_retrieval"],
                            "total_scenes": manifest.get("total_scenes", 0),
                            "generation_method": "parallel_processing_with_id_arrays",
                            "tracking_method": "postgresql_native",
                            "source": "postgresql"
                        }
                    }
                    
            except Exception as pg_error:
                print(f"⚠️ PostgreSQL query error, falling back to Firestore: {str(pg_error)}")
        
        # Fallback: Get story details from Firestore
        story_details = await storage_service.get_story_details(story_id)
        
        if not story_details:
            return {
                "success": False,
                "status": "not_found",
                "message": "Story not found in PostgreSQL or Firestore"
            }
        
        story_status = story_details.get('status', 'unknown')
        
        if story_status == "completed":
            # Return the complete story in the same format as the original generate endpoint
            manifest = story_details.get('manifest', story_details)
            
            # Ensure thumbnail_url is included from the story_details if not in manifest
            if not manifest.get('thumbnail_url') and story_details.get('thumbnail_url'):
                manifest['thumbnail_url'] = story_details.get('thumbnail_url')
            
            return {
                "success": True,
                "status": "completed",
                "message": f"Story '{manifest.get('title', 'Unknown')}' generated successfully!",
                "story": manifest,
                "performance_info": {
                    "optimizations_used": manifest.get("optimizations", []),
                    "total_scenes": manifest.get("total_scenes", 0),
                    "generation_method": "parallel_processing_with_id_arrays",
                    "tracking_method": "story_id_array",
                    "source": "firestore"
                }
            }
            
        elif story_status == "failed":
            return {
                "success": False,
                "status": "failed",
                "message": f"Story generation failed: {story_details.get('error', 'Unknown error')}",
                "story_id": story_id
            }
            
        else:
            # Still processing
            return {
                "success": False,
                "status": story_status,
                "message": f"Story is still generating... Status: {story_status}",
                "story_id": story_id,
                "title": story_details.get('title', 'Generating...'),
                "estimated_completion": "Check again in 5-10 seconds"
            }
        
    except Exception as e:
        print(f"❌ Error fetching story {story_id}: {str(e)}")
        return {
            "success": False,
            "status": "error", 
            "message": f"Error fetching story: {str(e)}",
            "story_id": story_id
        }

# ===== ENHANCED USER STORY MANAGEMENT ENDPOINTS WITH STORY ID ARRAYS =====
#----using in frontend----
@router.get("/user/stories")
async def get_user_stories_secure(
    response: Response,
    db: AsyncSession = Depends(get_session),
    limit: int = Query(20, ge=1, le=100, description="Number of stories to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of stories to skip"),
    filter: str = Query("owned", description="Filter stories by type: owned, shared, copied, all"),
    firebase_token: Optional[str] = Query(None, description="Fallback Firebase token if Authorization header is unavailable"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Get all stories for a user using Authorization header (RECOMMENDED)
    
    Usage:
    - GET /stories/user/stories?filter=owned
    - Headers: Authorization: Bearer {firebase_token}
    - Query params: ?limit=10&offset=0
    """
    add_cors_headers(response)
    
    try:
        print(f"🔍 [stories/user/stories] request: auth_header={bool(credentials and credentials.credentials)}, query_token={bool(firebase_token)}, limit={limit}, offset={offset}, filter={filter}")
        firebase_user_id: Optional[str] = None

        if credentials and credentials.credentials:
            # Primary path: Bearer token in Authorization header
            user_obj = await verify_firebase_token_from_header(credentials)
            firebase_user_id = user_obj.uid
        elif firebase_token:
            # Fallback path: explicit firebase_token query parameter (legacy support)
            firebase_user_id = await verify_firebase_token(firebase_token)
        else:
            raise HTTPException(
                status_code=401,
                detail="Missing credentials. Provide Authorization: Bearer <token> header or firebase_token query parameter."
            )

        if not firebase_user_id:
            raise HTTPException(status_code=401, detail="Unable to determine user from provided credentials")
        
        print(f"✅ [stories/user/stories] authenticated user {firebase_user_id} | filter={filter} | limit={limit} offset={offset}")
        
        # Convert firebase_user_id to integer user_id
        integer_user_id = await user_service._get_user_id_from_firebase_id(db, firebase_user_id)
        
        if not integer_user_id:
            print(f"❌ User not found in PostgreSQL: {firebase_user_id}")
            return {
                "success": True,
                "firebase_user_id": firebase_user_id,
                "filter": filter,
                "stories": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "method": "postgresql_no_user"
            }
        
        # Get user stories from PostgreSQL Story table (run query here to ensure same DB/context)
        from sqlalchemy import select, func
        from sqlalchemy.orm import selectinload
        from src.db.models.story import Story

        query = (
            select(Story).options(selectinload(Story.scenes))
            .where(Story.user_id == integer_user_id)
            .order_by(Story.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await db.execute(query)
        story_rows = result.scalars().all()

        # Map SQLAlchemy Story objects to serializable dicts (same shape as story_persistence_service)
        stories = []
        for story in story_rows:
            stories.append({
                'story_id': story.story_id,
                'title': story.title,
                'genre': story.genre,
                'story_length': story.story_length,
                'thumbnail_url': story.thumbnail_url,
                'duration': story.duration,
                'target_scenes': story.target_scenes,
                'child_name': story.child_name,
                'child_age': story.child_age,
                'art_style': story.art_style,
                'created_at': story.created_at.isoformat() if story.created_at else None,
                'total_scenes': len(story.scenes) if getattr(story, 'scenes', None) else 0
            })

        # Count total stories (for pagination)
        count_query = select(func.count()).select_from(Story).where(Story.user_id == integer_user_id)
        result = await db.execute(count_query)
        total_count = result.scalar()
        
        print(f"📚 [stories/user/stories] user={firebase_user_id} total={total_count} method=postgresql_query_with_join")
        
        # Build response
        response_data = {
            "success": True,
            "firebase_user_id": firebase_user_id,
            "filter": filter,
            "stories": stories,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(stories)) < total_count
            },
            "summary": {
                "total_stories_in_filter": total_count,
                "newest_story": stories[0] if stories else None,
                "stories_this_page": len(stories),
                "method_used": "postgresql_query_with_join"
            }
        }
        
        print(f"📚 [stories/user/stories] user={firebase_user_id} total={total_count} method=postgresql_query_with_join")
        
        return response_data
        
    except HTTPException:
        print("❌ [stories/user/stories] HTTPException raised")
        raise
    except Exception as e:
        print(f"❌ Error fetching user stories with filter: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stories: {str(e)}")

@router.get("/user/{firebase_token}/summary")
async def get_user_stories_summary(
    firebase_token: str,
    response: Response,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Get a quick summary of user's story creation activity using story ID arrays"""
    add_cors_headers(response)
    
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Get basic story count and latest stories using ID array method
        result = await storage_service.get_user_stories_using_id_array(user_id, limit=5, offset=0)
        
        summary = {
            "success": True,
            "user_id": user_id,
            "total_stories": result["total_count"],
            "latest_stories": result["stories"][:3],  # Just the 3 most recent
            "user_info": result["user_info"],
            "activity": {
                "has_stories": result["total_count"] > 0,
                "recent_activity": result["stories"][:5] if result["stories"] else []
            },
            "tracking_method": {
                "uses_story_id_array": True,
                "method": result.get("method_used", "story_id_array"),
                "story_ids_count": result.get("user_info", {}).get("story_ids_array_length", 0)
            }
        }
        
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch summary: {str(e)}")
#----using in frontend----
@router.get("/user/{firebase_token}/story-ids")
async def get_user_story_ids(
    firebase_token: str,
    response: Response,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Get just the story IDs array for a user (useful for quick checks)"""
    add_cors_headers(response)
    
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"📋 Fetching story IDs array for user {user_id}")
        
        # Get story IDs array
        story_ids = await storage_service.get_user_story_ids(user_id)
        
        return {
            "success": True,
            "user_id": user_id,
            "story_ids": story_ids,
            "total_count": len(story_ids),
            "newest_first": list(reversed(story_ids)),  # Newest first
            "oldest_first": story_ids,  # As stored (oldest first)
            "summary": {
                "has_stories": len(story_ids) > 0,
                "latest_story_id": story_ids[-1] if story_ids else None,
                "oldest_story_id": story_ids[0] if story_ids else None
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch story IDs: {str(e)}")

@router.delete("/user/{firebase_token}/story/{story_id}")
async def delete_user_story(
    firebase_token: str,
    story_id: str,
    response: Response,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Delete a specific story for a user and remove from story_ids array"""
    add_cors_headers(response)
    
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        
        print(f"🗑️ Deleting story {story_id} for user {user_id}")
        print(f"📋 Will also remove from user's story_ids array")
        
        # Delete the story (this also updates the story_ids array)
        success = await storage_service.delete_user_story(story_id, user_id)
        
        if success:
            return {
                "success": True,
                "message": f"Story {story_id} deleted successfully and removed from your story collection",
                "story_id": story_id,
                "tracking_info": {
                    "removed_from_story_ids_array": True,
                    "story_count_decremented": True
                }
            }
        else:
            raise HTTPException(status_code=404, detail="Story not found or access denied")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete story: {str(e)}")

# Path parameter route MUST come after all specific routes to avoid conflicts
@router.get("/user/{firebase_token}")
async def get_user_stories_endpoint(
    firebase_token: str,
    response: Response,
    limit: int = Query(20, ge=1, le=100, description="Number of stories to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of stories to skip"),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Get all stories for a user using story ID arrays with full metadata
    
    This endpoint now uses the story_ids array from the user document for optimal performance.
    
    Usage examples:
    - GET /stories/user/{token} - Get first 20 stories using ID array
    - GET /stories/user/{token}?limit=10 - Get first 10 stories  
    - GET /stories/user/{token}?limit=10&offset=10 - Get stories 11-20
    """
    add_cors_headers(response)
    
    try:
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"🔍 [stories/user/{{token}}] request: user={user_id} limit={limit} offset={offset}")
        
        # Get user stories using the enhanced story ID array method
        result = await storage_service.get_user_stories_using_id_array(user_id, limit=limit, offset=offset)
        
        # Safely extract user_info (handle None case)
        user_info = result.get("user_info") or {}
        
        # Enhance response with summary statistics
        response_data = {
            "success": True,
            "user_id": user_id,
            "stories": result["stories"],
            "pagination": result.get("pagination", {}),
            "user_info": user_info,
            "summary": {
                "total_stories_created": result["total_count"],
                "newest_story": result["stories"][0] if result["stories"] else None,
                "stories_this_page": len(result["stories"]),
                "method_used": result.get("method_used", "story_id_array"),
                "performance_info": result.get("performance_info", {})
            },
            "tracking_info": {
                "uses_story_id_array": True,
                "story_ids_array_length": user_info.get("story_ids_array_length", 0),
                "batch_fetched": True,
                "optimized_for_user_queries": True
            }
        }
        
        print(f"📚 [stories/user/{{token}}] user={user_id} total={result['total_count']} method={result.get('method_used', 'story_id_array')}")
        
        return response_data
        
    except HTTPException:
        print("❌ [stories/user/{token}] HTTPException raised")
        raise
    except Exception as e:
        print(f"❌ Error fetching user stories: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stories: {str(e)}")

# ===== LEGACY ENDPOINTS (KEEP FOR COMPATIBILITY) =====
#----using in frontend----
@router.post("/system-prompt")
async def update_system_prompt(
    request: SystemPromptUpdate,
    response: Response,
    user_service_dep = Depends(get_user_service)
):
    """Update system prompt for a user"""
    add_cors_headers(response)
    
    try:
        user_id = await verify_firebase_token(request.firebase_token)
        
        
        # Update system prompt
        user_service.update_system_prompt(user_id, request.system_prompt)
        
        return {
            "success": True,
            "message": "System prompt updated successfully",
            "user_id": user_id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list/{user_token}")
async def get_user_stories_legacy(
    user_token: str,
    response: Response,
    db: AsyncSession = Depends(get_session)
):
    """Get all stories for a user (legacy endpoint - now uses PostgreSQL)"""
    add_cors_headers(response)
    
    try:
        user_id = await verify_firebase_token(user_token)
        
        # Get stories from PostgreSQL
        stories = await story_service.get_user_stories(db, user_id, limit=50, offset=0)
        total_count = await story_service.get_story_count(db, user_id)
        
        return {
            "stories": stories,
            "total_count": total_count,
            "user_id": user_id,
            "legacy_endpoint_notice": "This endpoint now uses PostgreSQL"
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
#----using in frontend----
@router.get("/details/{story_id}")
async def get_story_details(
    story_id: str,
    response: Response,
    firebase_token: Optional[str] = Query(None, description="Firebase token for authentication"),
    db: AsyncSession = Depends(get_session)
):
    """Get complete story details including all scenes data from PostgreSQL"""
    add_cors_headers(response)
    
    try:
        # Verify user if token provided
        firebase_user_id = None
        if firebase_token:
            firebase_user_id = await verify_firebase_token(firebase_token)
        
        # Convert story_id to integer
        try:
            story_id_int = int(story_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid story_id format. Must be an integer.")
        
        # Get user_id if authenticated
        integer_user_id = None
        if firebase_user_id:
            integer_user_id = await user_service._get_user_id_from_firebase_id(db, firebase_user_id)
        
        # Fetch story with all scenes from PostgreSQL
        if integer_user_id:
            story_data = await story_persistence_service.get_story_with_scenes(
                db, story_id_int, integer_user_id
            )
        else:
            # If no auth, just try to fetch (will fail for private stories)
            from sqlalchemy import select
            from src.db.models.story import Story
            query = select(Story).where(Story.story_id == story_id_int)
            result = await db.execute(query)
            story_obj = result.scalar_one_or_none()
            
            if not story_obj:
                raise HTTPException(status_code=404, detail="Story not found")
            
            story_data = await story_persistence_service.get_story_with_scenes(
                db, story_id_int, story_obj.user_id
            )
        
        if not story_data:
            raise HTTPException(status_code=404, detail="Story not found")
        
        return {
            "success": True,
            "story": story_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error fetching story details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch story: {str(e)}")

# ===== DEMO ENDPOINT =====

@router.post("/demo")
async def add_demo_story(
    request: TokenVerificationRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Demo endpoint: Add Fiona the Fox story to user's collection with 5-second delay
    
    This demo story features:
    - ESP32-compatible audio (sourced from 1.5x volume-boosted WAV files)
    - Opus OGG web-optimized delivery (22x compression)
    - Trump voice narration for all 5 scenes
    - Perfect for testing cross-platform audio playback
    """
    add_cors_headers(response)
    
    try:
        print(f"🔍 Demo endpoint: Verifying token: {request.firebase_token[:50]}...")
        
        # Verify Firebase token - returns user_id string directly
        user_id = await auth_service.verify_token(request.firebase_token)
        
        print(f"✅ Token verified successfully. User ID: {user_id}")
        
        if not user_id:
            print("❌ No user ID found in verified token")
            raise HTTPException(status_code=401, detail="Invalid Firebase token - no user ID")
        
        # Hard-coded Fiona story ID from the upload script
        fiona_story_id = "story_9dd2fdf0"
        
        print(f"⏰ Adding 5-second delay...")
        # Add 5-second delay as requested
        await asyncio.sleep(5)
        
        print(f"📝 Adding story {fiona_story_id} to user {user_id} collection...")
        # Add story to user's story_ids array (simplified version of save_story_metadata)
        success = await storage_service.add_story_to_user_collection(user_id, fiona_story_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to add story to user collection")
        
        return {
            "success": True,
            "message": "Demo story added to your collection!",
            "story_id": fiona_story_id,
            "story_title": "Fiona the Fox Who Shared Her Snack",
            "user_id": user_id,
            "delay_seconds": 5,
            "audio_features": {
                "format": "Opus OGG (web optimized)",
                "source": "ESP32 WAV with 1.5x volume boost",
                "compression": "22x smaller than original",
                "esp32_compatible": True,
                "narrator": "Trump voice"
            }
        }
        
    except HTTPException as http_exc:
        print(f"❌ HTTP Exception: {http_exc.detail}")
        raise http_exc
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ===== STORY DELETION ENDPOINT =====
#----using in frontend----
@router.delete("/delete/{story_id}")
async def delete_story(
    story_id: str,
    request: TokenVerificationRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Delete a story from user's collection and remove from storage"""
    add_cors_headers(response)
    
    try:
        print(f"🗑️ Story deletion request for story: {story_id}")
        
        # Verify Firebase token (returns user_id string)
        user_id = await auth_service.verify_token(request.firebase_token)
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid Firebase token - no user ID")
        
        print(f"👤 User {user_id} requesting deletion of story {story_id}")
        
        # Verify the user owns this story
        try:
            story_details = await storage_service.get_story_details(story_id, user_id)
            if not story_details:
                raise HTTPException(status_code=404, detail="Story not found or access denied")
        except HTTPException as e:
            if e.status_code == 404:
                raise HTTPException(status_code=404, detail="Story not found or you don't have permission to delete it")
            raise
        
        # Delete the story
        success = await storage_service.delete_user_story(user_id, story_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete story")
        
        print(f"✅ Story {story_id} successfully deleted for user {user_id}")
        
        return {
            "success": True,
            "message": f"Story '{story_details.get('title', story_id)}' has been deleted",
            "story_id": story_id,
            "deleted_at": "now"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Unexpected error during story deletion: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete story: {str(e)}")

# ===== FALLBACK HANDLER FOR VERY LONG JWT TOKENS =====

@router.get("/user/{firebase_token:path}")
async def get_user_stories_fallback(
    firebase_token: str,
    response: Response,
    limit: int = Query(20, ge=1, le=100, description="Number of stories to return (1-100)"),
    offset: int = Query(0, ge=0, description="Number of stories to skip"),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Fallback handler for very long JWT tokens that exceed URL length limits
    
    This catches requests that would otherwise return 405 Method Not Allowed
    due to URL length restrictions when JWT tokens are very long (1000+ chars).
    """
    add_cors_headers(response)
    
    try:
        print(f"🔄 Fallback handler triggered for long JWT token | token_len={len(firebase_token)}")
        
        # Check if this looks like a JWT token (starts with eyJ)
        if not firebase_token.startswith('eyJ'):
            raise HTTPException(status_code=400, detail="Invalid token format - must be a JWT token")
        
        # Verify Firebase token and get user ID
        user_id = await verify_firebase_token(firebase_token)
        
        print(f"📚 [FALLBACK] Fetching stories for user {user_id} | limit={limit} offset={offset}")
        
        # Get user stories using the enhanced story ID array method
        result = await storage_service.get_user_stories_using_id_array(user_id, limit=limit, offset=offset)
        
        # Safely extract user_info (handle None case)
        user_info = result.get("user_info") or {}
        
        # Enhance response with summary statistics
        response_data = {
            "success": True,
            "user_id": user_id,
            "stories": result["stories"],
            "pagination": result.get("pagination", {}),
            "user_info": user_info,
            "summary": {
                "total_stories_created": result["total_count"],
                "newest_story": result["stories"][0] if result["stories"] else None,
                "stories_this_page": len(result["stories"]),
                "method_used": result.get("method_used", "story_id_array"),
                "performance_info": result.get("performance_info", {})
            },
            "tracking_info": {
                "uses_story_id_array": True,
                "story_ids_array_length": user_info.get("story_ids_array_length", 0),
                "batch_fetched": True,
                "optimized_for_user_queries": True,
                "fallback_handler_used": True,  # Indicate this was handled by fallback
                "token_length": len(firebase_token)
            }
        }
        
        print(f"📚 [FALLBACK] user={user_id} total={result['total_count']} method={result.get('method_used', 'story_id_array')}")
        
        return response_data
        
    except HTTPException:
        print("❌ [stories/user/{firebase_token:path}] HTTPException raised")
        raise
    except Exception as e:
        print(f"❌ [FALLBACK] Error fetching user stories: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch stories: {str(e)}")

# ===== OPTIONS HANDLERS =====

@router.options("/generate")
@router.options("/fetch/{story_id}")
@router.options("/system-prompt")
@router.options("/list/{user_token}")
@router.options("/details/{story_id}")
@router.options("/user/stories")  # New secure endpoint
@router.options("/user/{firebase_token}")
@router.options("/user/{firebase_token}/summary") 
@router.options("/user/{firebase_token}/story/{story_id}")
@router.options("/user/{firebase_token}/story-ids")
@router.options("/demo")
@router.options("/delete/{story_id}")
async def stories_options(response: Response):
    """Handle preflight OPTIONS requests for all story endpoints"""
    add_cors_headers(response)
    return {"message": "OK"}