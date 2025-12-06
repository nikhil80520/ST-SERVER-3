"""
Reference Images Routes
FastAPI endpoints for managing reference images
"""
from fastapi import APIRouter, HTTPException, Header, Depends
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from src.reference_images.schema import (
    ReferenceImageListRequest,
    ReferenceImageListResponse,
    ReferenceImageResponse,
    ReferenceImageCreate,
    ReferenceImageUpdate
)
from src.reference_images.service_pg import reference_image_service_pg
from src.db import get_session
from src.dependencies import verify_firebase_token

router = APIRouter(prefix="/reference-images", tags=["reference-images"])


@router.get("/list")
async def list_reference_images(
    firebase_token: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    category: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_session)
):
    """
    Get paginated reference images for the authenticated user
    
    Query Parameters:
    - firebase_token: Firebase token (optional, can also use Authorization header)
    - limit: Number of images to return (default: 20)
    - offset: Number of images to skip (default: 0)
    - category: Filter by category (optional)
    
    Authentication (pick one):
    1. Query param: ?firebase_token=...
    2. Authorization header: Bearer <token>
    """
    try:
        # Get token from query param or Authorization header
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify Firebase token
        try:
            firebase_user_id = await verify_firebase_token(token)
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)}")
        
        print(f"📋 Fetching reference images for user: {firebase_user_id}")
        
        # Validate pagination parameters
        if limit < 1 or limit > 100:
            limit = 20
        if offset < 0:
            offset = 0
        
        # Get reference images and total count
        reference_images = await reference_image_service_pg.get_user_reference_images(
            db=db,
            firebase_user_id=firebase_user_id,
            limit=limit,
            offset=offset,
            category=category
        )
        
        total_count = await reference_image_service_pg.get_total_reference_images_count(
            db=db,
            firebase_user_id=firebase_user_id,
            category=category
        )
        
        has_more = (offset + limit) < total_count
        
        print(f"✅ Retrieved {len(reference_images)} reference images (total: {total_count})")
        
        return {
            "success": True,
            "reference_images": reference_images,
            "total_count": total_count,
            "has_more": has_more
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to fetch reference images: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch reference images: {str(e)}")


@router.get("/{reference_image_id}")
async def get_reference_image(
    reference_image_id: int,
    firebase_token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_session)
):
    """Get a specific reference image"""
    try:
        # Get token
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify token
        try:
            firebase_user_id = await verify_firebase_token(token)
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
        
        # Get image
        images = await reference_image_service_pg.get_user_reference_images(
            db=db,
            firebase_user_id=firebase_user_id,
            limit=1
        )
        
        matching_images = [img for img in images if img['reference_image_id'] == reference_image_id]
        
        if not matching_images:
            raise HTTPException(status_code=404, detail="Reference image not found")
        
        return {
            "success": True,
            "reference_image": matching_images[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to fetch reference image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch reference image: {str(e)}")


@router.post("/create")
async def create_reference_image(
    request: ReferenceImageCreate,
    db: AsyncSession = Depends(get_session)
):
    """
    Create a new reference image
    
    Request body:
    {
        "firebase_token": "...",
        "title": "Beach Scene",
        "description": "Beautiful beach for storytelling",
        "image_url": "https://...",
        "age_group": "3-5",
        "category": "nature"
    }
    """
    try:
        # Verify token
        try:
            firebase_user_id = await verify_firebase_token(request.firebase_token)
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
        
        print(f"📸 Creating reference image for user: {firebase_user_id}")
        
        # Create reference image
        ref_image = await reference_image_service_pg.create_reference_image(
            db=db,
            firebase_user_id=firebase_user_id,
            title=request.title,
            image_url=request.image_url,
            description=request.description,
            age_group=request.age_group,
            category=request.category
        )
        
        # Commit transaction
        await db.commit()
        
        return {
            "success": True,
            "message": "Reference image created successfully",
            "reference_image": ref_image
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Failed to create reference image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create reference image: {str(e)}")


@router.delete("/{reference_image_id}")
async def delete_reference_image(
    reference_image_id: int,
    firebase_token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_session)
):
    """
    Delete a reference image
    
    Authentication (pick one):
    1. Query param: ?firebase_token=...
    2. Authorization header: Bearer <token>
    """
    try:
        # Get token
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify token
        try:
            firebase_user_id = await verify_firebase_token(token)
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
        
        print(f"🗑️ Deleting reference image {reference_image_id} for user: {firebase_user_id}")
        
        # Delete image
        success = await reference_image_service_pg.delete_reference_image(
            db=db,
            reference_image_id=reference_image_id,
            firebase_user_id=firebase_user_id
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Reference image not found or unauthorized")
        
        # Commit transaction
        await db.commit()
        
        return {
            "success": True,
            "message": "Reference image deleted successfully",
            "reference_image_id": reference_image_id
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        print(f"❌ Failed to delete reference image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete reference image: {str(e)}")
