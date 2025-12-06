"""
Children Routes Module
Contains only FastAPI route definitions that delegate to ChildrenService.
No business logic - all logic is in service_pg.py.
"""
from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from src.children.schema import (
    ChildCreate,
    ChildUpdate,
    ChildResponse,
    ChildrenListResponse,
    ChildSelectRequest,
    ChildSystemPromptUpdate,
    ChildVoiceCloneSelectRequest,
    ChildReferenceImageLinkRequest,
    ChildProfilePictureResponse,
    ChildStatsResponse,
    ChildStoriesResponse,
    ChildOperationResponse,
    HealthCheckResponse,
)
from src.children.service_pg import children_service
from src.db import get_session
from src.dependencies import verify_firebase_token

router = APIRouter(prefix="/children", tags=["children"])


# ===== HELPER FUNCTIONS =====

def extract_token(firebase_token: str = None, authorization: str = None) -> str:
    """Extract Firebase token from query param or Authorization header"""
    token = firebase_token
    if not token and authorization:
        if authorization.startswith('Bearer '):
            token = authorization[7:]
        else:
            token = authorization
    
    if not token:
        raise HTTPException(status_code=401, detail="Firebase token required")
    
    return token


# ===== CHILDREN ENDPOINTS =====

@router.post("", response_model=ChildOperationResponse)
async def create_child(
    request: ChildCreate, 
    db: AsyncSession = Depends(get_session)
):
    """
    Create a new child profile for the authenticated parent.
    
    This endpoint:
    - Verifies Firebase authentication
    - Creates child profile in PostgreSQL
    - Uploads profile image to S3 if provided
    - Generates personalized system prompt
    - Sets as default child if first child
    - Returns child profile with statistics
    """
    try:
        # Verify Firebase token and get parent user ID (Firebase ID is a string)
        firebase_user_id = await verify_firebase_token(request.firebase_token)
        
        # Convert Firebase user ID to integer user_id for database
        from src.user.service_pg import user_service
        integer_user_id = await user_service._get_user_id_from_firebase_id(db, firebase_user_id)
        if not integer_user_id:
            raise HTTPException(status_code=404, detail="User not found in database")
        
        # Create child profile
        child = await children_service.create_child(
            db=db,
            user_id=integer_user_id,
            name=request.name,
            age=request.age,
            interests=request.interests,
            image_base64=request.image_base64,
            avatar_seed=request.avatar_seed,
            avatar_style=request.avatar_style,
            system_prompt=request.system_prompt
        )
        
        # Get child with stats
        child_response = await children_service.get_child_with_stats(
            db, firebase_user_id, child.child_id
        )
        
        return ChildOperationResponse(
            success=True,
            message="Child profile created successfully",
            child=child_response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create child: {str(e)}")


@router.get("", response_model=ChildrenListResponse)
async def get_children(
    db: AsyncSession = Depends(get_session),
    firebase_token: str = None,
    authorization: str = Header(None)
):
    """
    Get all children for the authenticated parent.
    
    This endpoint:
    - Verifies Firebase authentication
    - Retrieves all active children
    - Loads statistics for each child
    - Returns default child ID
    - Returns list of children with counts
    
    Authentication:
    - Query param: ?firebase_token=...
    - Header: Authorization: Bearer <token>
    """
    try:
        # Extract and verify token
        token = extract_token(firebase_token, authorization)
        firebase_user_id = await verify_firebase_token(token)
        
        # Get all active children
        children = await children_service.get_all_children(
            db, firebase_user_id, include_inactive=False
        )
        
        # Get default child ID from user
        from src.db.models import User
        from sqlalchemy import select
        stmt = select(User.default_child_id).where(User.firebase_user_id == firebase_user_id)
        result = await db.execute(stmt)
        default_child_id = result.scalar()
        
        # Get detailed info for each child
        children_responses = []
        for child in children:
            child_with_stats = await children_service.get_child_with_stats(
                db, firebase_user_id, child.child_id
            )
            if child_with_stats:
                children_responses.append(child_with_stats)
        
        return ChildrenListResponse(
            success=True,
            children=children_responses,
            default_child_id=default_child_id,
            total_count=len(children_responses)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get children: {str(e)}")


@router.get("/stats", response_model=ChildStatsResponse)
async def get_children_stats(
    db: AsyncSession = Depends(get_session),
    firebase_token: str = None, 
    authorization: str = Header(None)
):
    """
    Get aggregated statistics across all active children for the authenticated parent.
    
    This endpoint:
    - Verifies Firebase authentication
    - Aggregates story counts across all children
    - Aggregates voice clone counts
    - Aggregates reference image counts
    - Returns total children count
    
    NOTE: Defined before dynamic /{child_id} route to avoid path shadowing.
    """
    try:
        # Extract and verify token
        token = extract_token(firebase_token, authorization)
        user_id = await verify_firebase_token(token)
        
        # Get aggregated stats from service
        stats = await children_service.get_children_stats(db, user_id)
        
        return stats
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get children stats: {str(e)}")


@router.get("/{child_id}", response_model=ChildOperationResponse)
async def get_child(
    child_id: int, 
    firebase_token: str, 
    db: AsyncSession = Depends(get_session)
):
    """
    Get a specific child profile with statistics.
    
    This endpoint:
    - Verifies Firebase authentication
    - Retrieves child profile
    - Includes story count
    - Includes voice clone count
    - Includes reference image count
    
    Path params:
    - child_id: The child's unique identifier
    
    Query params:
    - firebase_token: Firebase authentication token
    """
    try:
        # Verify Firebase token and get parent user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Get child with stats
        child = await children_service.get_child_with_stats(db, user_id, child_id)
        
        if not child:
            raise HTTPException(status_code=404, detail="Child profile not found")
        
        return ChildOperationResponse(
            success=True,
            message="Child profile retrieved successfully",
            child=child
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get child: {str(e)}")


@router.put("/{child_id}", response_model=ChildOperationResponse)
async def update_child(
    child_id: int, 
    request: ChildUpdate, 
    db: AsyncSession = Depends(get_session)
):
    """
    Update a child profile.
    
    This endpoint:
    - Verifies Firebase authentication
    - Updates child name, age, or interests
    - Updates profile image if provided
    - Regenerates system prompt if child info changed
    - Returns updated child profile with statistics
    
    Path params:
    - child_id: The child's unique identifier
    
    Request body can include:
    - name, age, interests (child details)
    - image_base64 (new profile picture)
    - avatar_seed, avatar_style (avatar settings)
    - system_prompt (custom prompt)
    """
    try:
        # Verify Firebase token and get parent user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Update child profile
        updated_child = await children_service.update_child(
            db=db,
            user_id=user_id,
            child_id=child_id,
            name=request.name,
            age=request.age,
            interests=request.interests,
            image_base64=request.image_base64,
            avatar_seed=request.avatar_seed,
            avatar_style=request.avatar_style,
            system_prompt=request.system_prompt
        )
        
        if not updated_child:
            raise HTTPException(status_code=404, detail="Child profile not found")
        
        # Get updated child with stats
        child_response = await children_service.get_child_with_stats(db, user_id, child_id)
        
        return ChildOperationResponse(
            success=True,
            message="Child profile updated successfully",
            child=child_response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update child: {str(e)}")


@router.patch("/{child_id}/system-prompt", response_model=ChildOperationResponse)
async def update_child_system_prompt(
    child_id: int, 
    request: ChildSystemPromptUpdate, 
    db: AsyncSession = Depends(get_session)
):
    """
    Update only the child's system prompt.
    
    This endpoint:
    - Verifies Firebase authentication
    - Updates child's system prompt
    - Returns updated child profile
    """
    try:
        user_id = await verify_firebase_token(request.firebase_token)
        
        await children_service.set_child_system_prompt(
            db, user_id, child_id, request.system_prompt
        )
        
        child = await children_service.get_child_with_stats(db, user_id, child_id)
        
        return ChildOperationResponse(
            success=True,
            message="System prompt updated",
            child=child
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update system prompt: {str(e)}")


@router.post("/{child_id}/voice-clone/select", response_model=ChildOperationResponse)
async def select_child_voice_clone(
    child_id: int, 
    request: ChildVoiceCloneSelectRequest, 
    db: AsyncSession = Depends(get_session)
):
    """
    Select/assign a voice clone for the child.
    
    This endpoint:
    - Verifies Firebase authentication
    - Assigns voice clone ID to child
    - Returns updated child profile
    """
    try:
        user_id = await verify_firebase_token(request.firebase_token)
        
        await children_service.set_child_voice_clone(
            db, user_id, child_id, request.voice_clone_id
        )
        
        child = await children_service.get_child_with_stats(db, user_id, child_id)
        
        return ChildOperationResponse(
            success=True,
            message="Voice clone selected",
            child=child
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to select voice clone: {str(e)}")


@router.delete("/{child_id}", response_model=ChildOperationResponse)
async def delete_child(
    child_id: int, 
    firebase_token: str, 
    db: AsyncSession = Depends(get_session)
):
    """
    Soft delete a child profile.
    
    This endpoint:
    - Verifies Firebase authentication
    - Marks child as inactive (soft delete)
    - Updates parent's children count
    - Reassigns default child if needed
    
    Path params:
    - child_id: The child's unique identifier
    
    Query params:
    - firebase_token: Firebase authentication token
    """
    try:
        # Verify Firebase token and get parent user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Delete child profile (soft delete)
        success = await children_service.delete_child(db, user_id, child_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Child profile not found")
        
        return ChildOperationResponse(
            success=True,
            message="Child profile deleted successfully",
            child_id=child_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete child: {str(e)}")


@router.post("/{child_id}/select", response_model=ChildOperationResponse)
async def select_child(
    child_id: int, 
    request: ChildSelectRequest, 
    db: AsyncSession = Depends(get_session)
):
    """
    Set a child as the default/selected child for the parent.
    
    This endpoint:
    - Verifies Firebase authentication
    - Sets child as default in user record
    - Returns confirmation with child ID
    
    Path params:
    - child_id: The child's unique identifier
    
    Request body:
    - firebase_token: Firebase authentication token
    """
    try:
        # Verify Firebase token and get parent user ID
        user_id = await verify_firebase_token(request.firebase_token)
        
        # Set as default child
        success = await children_service.set_default_child(db, user_id, child_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Child profile not found")
        
        return ChildOperationResponse(
            success=True,
            message="Child selected successfully",
            default_child_id=child_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to select child: {str(e)}")


@router.get("/{child_id}/stories", response_model=ChildStoriesResponse)
async def get_child_stories(
    child_id: int, 
    firebase_token: str, 
    db: AsyncSession = Depends(get_session), 
    limit: int = 20, 
    offset: int = 0
):
    """
    Get all stories for a specific child.
    
    This endpoint:
    - Verifies Firebase authentication
    - Verifies child belongs to parent
    - Retrieves stories for child
    - Returns paginated results
    
    Path params:
    - child_id: The child's unique identifier
    
    Query params:
    - firebase_token: Firebase authentication token
    - limit: Maximum number of stories to return (default: 20)
    - offset: Number of stories to skip (default: 0)
    """
    try:
        # Verify Firebase token and get parent user ID
        user_id = await verify_firebase_token(firebase_token)
        
        # Get stories from service
        stories_data = await children_service.get_child_stories(
            db=db,
            user_id=user_id,
            child_id=child_id,
            limit=limit,
            offset=offset
        )
        
        return stories_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get child stories: {str(e)}")


@router.get("/{child_id}/profile-picture", response_model=ChildProfilePictureResponse)
async def get_child_profile_picture(
    child_id: int, 
    db: AsyncSession = Depends(get_session),
    firebase_token: str = None, 
    authorization: str = Header(None)
):
    """
    Get a child's profile picture information.
    
    This endpoint:
    - Verifies Firebase authentication
    - Retrieves child profile picture URL
    - Returns picture availability status
    
    Path params:
    - child_id: The child's unique identifier
    
    Query params or Headers:
    - firebase_token: Firebase authentication token (query param)
    - Authorization: Bearer token (header)
    """
    try:
        # Extract and verify token
        token = extract_token(firebase_token, authorization)
        user_id = await verify_firebase_token(token)
        
        # Get profile picture info from service
        picture_info = await children_service.get_child_profile_picture(
            db=db,
            user_id=user_id,
            child_id=child_id
        )
        
        return picture_info
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get profile picture: {str(e)}")


@router.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """
    Health check endpoint for children service.
    
    This endpoint:
    - Checks if Firebase is available
    - Returns service health status
    """
    try:
        from src.common_function.firebase_init import is_firebase_available
        
        return HealthCheckResponse(
            success=True,
            service="children_service",
            firebase_available=is_firebase_available(),
            status="healthy"
        )
        
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")
