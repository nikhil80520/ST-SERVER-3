from fastapi import APIRouter, Depends, HTTPException, Response, Body, Query
from typing import List, Optional
from datetime import datetime
import io
from sqlalchemy.ext.asyncio import AsyncSession

from src.dependencies import get_storage_service, get_optional_current_user, get_current_user_from_header as get_current_user
from src.common_function.storage_service import StorageService
from src.user.schema import User
from src.share.schema import (
    ShareStoryRequest,
    SharedStoryResponse,
    ShareSettings,
    CopyStoryRequest,
    ShareUpdate,
    StoryAnalytics,
    SharingDashboard,
    BatchUpdateRequest,
    BatchUpdateResponse,
    RenewRequest,
    RenewLinkResponse
)
from src.core.config import settings
from src.common_function.qr_generator import create_qr_code
from src.share.service_pg import share_service_pg
from src.db import get_session
router = APIRouter(
    prefix="/stories/share",
    tags=["sharing"],
)

storage_service: StorageService = Depends(get_storage_service)
#----using in frontend app----
@router.post("/enable/{story_id}", response_model=SharedStoryResponse)
async def enable_story_sharing(
    story_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    storage_service: StorageService = Depends(get_storage_service),
    settings_param: Optional[ShareSettings] = Body(None),
    expires_at: Optional[datetime] = Body(None)
):
    """
    Enable sharing for a story and get a shareable deep link.
    
    The share link will use the app's custom scheme (storymagic://) so it opens
    directly in the app. When opened:
    1. App prompts user to sign in if not logged in
    2. Once authenticated, story is copied to their "Shared with me" collection
    3. They can view it like any other story in their library
    
    The request body is optional. If not provided, default sharing settings will be used.
    Body parameters:
    - settings: Optional sharing settings (allow_copy, show_creator, track_analytics). Defaults to all enabled.
    - expires_at: Optional expiration datetime for the share link. If None (default), the link never expires.
    
    Example requests:
    1. No body (uses all defaults, never expires):
       POST /stories/share/enable/{story_id}
       
    2. With custom expiration:
       POST /stories/share/enable/{story_id}
       Body: {"expires_at": "2025-12-31T23:59:59Z"}
    """
    print(f"📤 [SHARING] Enable sharing called for story_id: {story_id}", flush=True)
    print(f"📤 [SHARING] Settings: {settings_param.model_dump() if settings_param else 'Default'}", flush=True)
    print(f"📤 [SHARING] Expires at: {expires_at if expires_at else 'Never (permanent link)'}", flush=True)
    print(f"📤 [SHARING] User ID: {current_user.uid}", flush=True)
    
    # Use default settings if not provided
    if settings_param is None:
        settings_param = ShareSettings()
    
    share_url, qr_code_url = await share_service_pg.enable_story_sharing(
        db=db,
        story_id=story_id,
        user_id=current_user.uid,
        share_settings=settings_param,
        expires_at=expires_at
    )
    
    print(f"✅ [SHARING] Generated share link: {share_url}", flush=True)
    
    return SharedStoryResponse(
        share_url=share_url,
        qr_code_url=qr_code_url,
        share_token=share_url.split("/")[-1],
        expires_at=expires_at
    )
#---using in frontend app----
@router.post("/disable/{story_id}", status_code=204)
async def disable_story_sharing(
    story_id: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    storage_service: StorageService = Depends(get_storage_service)
):
    """Disable sharing for a story."""
    success = await share_service_pg.disable_story_sharing(db, story_id, current_user.uid)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to disable sharing.")
    return Response(status_code=204)
#---using in frontend app----
@router.get("/view/{share_token}")
async def view_shared_story(
    share_token: str,
    db: AsyncSession = Depends(get_session),
    current_user: Optional[User] = Depends(get_optional_current_user)
):
    """
    View shared story by token (authentication optional)
    
    Returns story data if share is valid and not expired.
    Tracks view count if analytics enabled.
    """
    print(f"👀 [SHARING] Viewing shared story with token: {share_token}", flush=True)
    
    story_data = await share_service_pg.get_shared_story(
        db=db,
        share_token=share_token,
        viewer_user_id=current_user.uid if current_user else None
    )
    
    if not story_data:
        raise HTTPException(status_code=404, detail="Shared story not found or expired")
    
    print(f"✅ [SHARING] Returning story {story_data['story_id']}", flush=True)
    return {"success": True, **story_data}

#---using in frontend app----
@router.post("/accept/{share_token}")
async def accept_shared_story(
    share_token: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Accept a shared story - adds it to the current user's "Shared with me" collection.
    
    **Authentication Required** - User must be logged in to receive shared stories.
    
    What this endpoint does:
    1. Validates the share_token (checks if valid, not expired, etc.)
    2. Verifies user is authenticated
    3. Copies the story to user's library with S3 references
    4. Tracks analytics (copy count)
    5. Returns success message
    
    The actual story data is NOT returned here. Instead, a new copy is created
    in the user's account, and the frontend should:
    - Navigate to their "Shared with me" section
    - Fetch the story using the regular /stories/{story_id} endpoint
    - Display it like any other story
    
    Flow:
    1. User A shares story → Gets deep link: storymagic://share/view/{token}
    2. User B clicks link → App opens, prompts login if needed
    3. Once logged in, app calls this endpoint
    4. Story appears in User B's "Shared with me" library
    5. App navigates to story viewer
    
    Returns:
    {
      "success": true,
      "message": "Story added to your library",
      "story_id": "story_123",
      "shared_by": {
        "user_id": "user_abc",
        "name": "John Doe"
      },
      "action": "navigate_to_story"  // Tell app what to do next
    }
    """
    print(f"📥 [SHARING] Accepting shared story with token: {share_token}", flush=True)
    print(f"📥 [SHARING] Receiving user: {current_user.uid}", flush=True)
    
    try:
        # Copy story to user's library
        new_story_id = await share_service_pg.copy_shared_story(
            db=db,
            share_token=share_token,
            recipient_user_id=current_user.uid,
            recipient_child_id=None  # Can be extended to accept child_id parameter
        )
        
        if not new_story_id:
            raise HTTPException(status_code=404, detail="Shared story not found, expired, or copy not allowed")
        
        print(f"✅ [SHARING] Story copied with new ID {new_story_id} to user {current_user.uid}'s library", flush=True)
        
        return {
            "success": True,
            "message": "Story added to your library! Check 'Shared with me' section.",
            "story_id": new_story_id,
            "action": "navigate_to_story",
            "share_info": {
                "received_at": datetime.utcnow().isoformat(),
                "share_token": share_token
            }
        }
        
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"❌ [SHARING] Error accepting shared story: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Failed to add story: {str(e)}")
#---using in frontend app----
@router.get("/received")
async def get_received_shared_stories(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    Get all stories that were shared with the current user.
    
    Returns stories that were copied to user's library from shares (metadata shows 'copied_from')
    - Story details (title, scenes, images, audio)
    - Who shared it (from metadata)
    - When it was received
    
    Usage in app:
    - "Shared with me" tab/section
    - Shows stories others have shared with this user
    
    Response includes pagination for large lists.
    """
    print(f"📚 [SHARING] Fetching received stories for user {current_user.uid}", flush=True)
    
    try:
        from src.story.service_pg import story_service_pg
        from sqlalchemy import and_
        
        # Get stories where metadata contains 'copied_from' (indicating shared stories)
        stories_result = await story_service_pg.get_user_stories(
            db=db,
            user_id=current_user.uid,
            limit=limit,
            offset=offset
        )
        
        # Filter to only shared stories
        shared_stories = [
            s for s in stories_result['stories'] 
            if s.get('metadata', {}).get('copied_from')
        ]
        
        print(f"✅ [SHARING] Found {len(shared_stories)} received stories", flush=True)
        
        return {
            "success": True,
            "stories": shared_stories,
            "total_count": len(shared_stories),
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": False  # Simple implementation
            }
        }
        
    except Exception as e:
        print(f"❌ [SHARING] Error fetching received stories: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch received stories: {str(e)}")

#---using in frontend app----
@router.post("/track/{story_id}")
async def track_shared_story_access(
    story_id: str,
    user: User = Depends(get_current_user),
    storage_service: StorageService = Depends(get_storage_service)
):
    """
    Track when a user accesses a shared story via deep link.
    This adds the story to their "shared_stories_received" array for the "Shared with Me" section.
    
    This endpoint is called by the frontend when a user opens a share link:
    storymagic://share/{story_id}
    
    Returns:
        - success: Whether tracking was successful
        - message: Status message
        - already_had: Whether user already had this story in their collection
    """
    try:
        # Check if story exists and is shared
        story = await storage_service.get_story_by_id(story_id)
        if not story:
            raise HTTPException(status_code=404, detail="Story not found")
        
        # Don't track if user is viewing their own story
        if story.get('user_id') == user.uid:
            return {
                "success": True,
                "message": "This is your own story",
                "already_had": True
            }
        
        # Check if story has sharing enabled
        if not story.get('sharing_enabled', False):
            raise HTTPException(status_code=403, detail="This story is not shared")
        
        # Check if share has expired
        expires_at = story.get('share_expires_at')
        if expires_at:
            expiry_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if datetime.now(expiry_date.tzinfo) > expiry_date:
                raise HTTPException(status_code=410, detail="This share link has expired")
        
        # Track the share reception
        result = await storage_service.track_story_share_reception(story_id, user.uid)
        
        return {
            "success": True,
            "message": "Story access tracked successfully",
            "already_had": result.get("already_had", False),
            "shared_by": result.get("shared_by", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [SHARING] Error tracking story access: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Failed to track story access: {str(e)}")


@router.get("/qr/{share_token}", response_class=Response)
async def get_sharing_qr_code(share_token: str):
    """Generate and return a QR code for a share link."""
    share_url = f"{settings.app_base_url}/share/{share_token}"
    try:
        img_bytes = create_qr_code(share_url)
        return Response(content=img_bytes, media_type="image/png")
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate QR code: {str(e)}")

# =======================================================================
# Phase 3: Analytics & Dashboard
# =======================================================================

@router.get("/{story_id}/analytics", response_model=StoryAnalytics, tags=["Sharing Analytics"])
async def get_story_analytics(
    story_id: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Get detailed analytics for a shared story. Only the story owner can access this.
    """
    try:
        analytics_data = await share_service_pg.get_story_analytics(db, story_id, user.uid)
        if not analytics_data:
            raise HTTPException(status_code=404, detail="Story not found or not shared")
        return analytics_data
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve story analytics: {str(e)}")

@router.get("/dashboard", response_model=SharingDashboard, tags=["Sharing Analytics"])
async def get_sharing_dashboard(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Get a dashboard of the user's sharing activities, including stats and top stories.
    """
    try:
        dashboard_data = await share_service_pg.get_sharing_dashboard(db, user.uid)
        return dashboard_data
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve sharing dashboard: {str(e)}")

# =======================================================================
# Phase 4: Advanced Sharing Controls (Batch & Renewal)
# =======================================================================

@router.post("/batch-update", response_model=BatchUpdateResponse, tags=["Advanced Sharing"])
async def batch_update_sharing_status(
    update_request: BatchUpdateRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Batch enable or disable sharing for a list of stories.
    """
    try:
        updated_count = await share_service_pg.batch_update_shares(
            db=db,
            user_id=user.uid,
            story_ids=update_request.story_ids,
            is_active=update_request.enable,
            expires_at=None
        )
        return BatchUpdateResponse(
            success=True,
            updated_count=updated_count,
            story_ids=update_request.story_ids
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch update failed: {str(e)}")

@router.post("/{story_id}/renew", response_model=RenewLinkResponse, tags=["Advanced Sharing"])
async def renew_share_link(
    story_id: str,
    renew_request: RenewRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """
    Renew or update the expiration date of a shareable link.
    """
    try:
        new_share_url, new_expires_at = await share_service_pg.renew_share_link(
            db=db,
            story_id=story_id,
            user_id=user.uid,
            new_expires_at=renew_request.new_expires_at
        )
        
        return RenewLinkResponse(
            story_id=story_id,
            message="Share link renewed successfully.",
            new_expires_at=new_expires_at,
            new_share_url=new_share_url
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to renew share link: {str(e)}")
