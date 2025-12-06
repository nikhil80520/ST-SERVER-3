"""Lullaby generation endpoints"""
from fastapi import APIRouter, HTTPException, status, Header
from typing import Dict, Any, Optional
from pydantic import BaseModel
from src.dependencies import verify_firebase_token
from src.common_function.firebase_init import get_firestore_client
router = APIRouter(prefix="/lullabies", tags=["Lullabies"])


class LullabyGenerateRequest(BaseModel):
    description: str
    firebase_token: str

#---using in frontend app----
@router.get("/", response_model=Dict[str, Any])
async def get_user_lullabies(
    firebase_token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Get all lullabies for the current user
    
    Authentication:
    - Query param: ?firebase_token=...
    - Header: Authorization: Bearer <token>
    
    Returns:
        List of all lullabies owned by the user, sorted by creation date (newest first)
    """
    try:
        # Extract token from header or query param
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify Firebase token
        user_id = await verify_firebase_token(token)
        
        # Get lullabies from Firestore
        db = get_firestore_client()
        if not db:
            raise HTTPException(status_code=503, detail="Database service unavailable")
        
        # Query without order_by to avoid composite index requirement
        # We'll sort in Python instead
        lullabies_ref = db.collection('lullabies').where('user_id', '==', user_id)
        lullabies_docs = lullabies_ref.stream()
        
        lullabies = []
        for doc in lullabies_docs:
            lullaby_data = doc.to_dict()
            lullaby_data['lullaby_id'] = doc.id
            lullabies.append(lullaby_data)
        
        # Sort by created_at in Python (descending - newest first)
        from datetime import datetime
        lullabies.sort(
            key=lambda x: x.get('created_at') or datetime.min, 
            reverse=True
        )
        
        return {
            "success": True,
            "lullabies": lullabies,
            "total_count": len(lullabies),
            "message": f"Retrieved {len(lullabies)} lullabies"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to fetch lullabies: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch lullabies: {str(e)}"
        )

#---using in frontend app----
@router.get("/{lullaby_id}", response_model=Dict[str, Any])
async def get_lullaby(
    lullaby_id: str,
    firebase_token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Get a specific lullaby by ID
    
    Authentication:
    - Query param: ?firebase_token=...
    - Header: Authorization: Bearer <token>
    
    Args:
        lullaby_id: The unique ID of the lullaby
        
    Returns:
        Lullaby metadata with audio URL
        
    Raises:
        HTTPException: If lullaby not found or access denied
    """
    try:
        # Extract token from header or query param
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify Firebase token
        user_id = await verify_firebase_token(token)
        
        # Get lullaby from Firestore
        db = get_firestore_client()
        if not db:
            raise HTTPException(status_code=503, detail="Database service unavailable")
        
        lullaby_doc = db.collection('lullabies').document(lullaby_id).get()
        
        if not lullaby_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lullaby not found"
            )
        
        lullaby_data = lullaby_doc.to_dict()
        
        # Verify ownership
        if lullaby_data.get('user_id') != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        lullaby_data['lullaby_id'] = lullaby_id
        
        return {
            "success": True,
            "lullaby": lullaby_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to fetch lullaby: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch lullaby: {str(e)}"
        )

#---using in frontend app----
@router.post("/generate", response_model=Dict[str, Any])
async def generate_lullaby(request: LullabyGenerateRequest):
    """Generate a new lullaby with AI-generated lyrics and music
    
    Process:
    1. Generates lyrics using OpenAI based on your description
    2. Creates music using Replicate's MiniMax Music-1.5 model
    3. Stores the audio file in Firebase Storage
    4. Returns metadata with audio URL
    
    Args:
        request: Description of what the lullaby should be about (10-500 chars)
        
    Returns:
        Generated lullaby metadata with audio URL
        
    Raises:
        HTTPException: If generation fails
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Lullaby generation is temporarily disabled. Use existing lullabies."
    )

#---using in frontend app----
@router.delete("/{lullaby_id}", response_model=Dict[str, Any])
async def delete_lullaby(
    lullaby_id: str,
    firebase_token: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    """Delete a lullaby
    
    Args:
        lullaby_id: The unique ID of the lullaby to delete
        
    Returns:
        Success message
        
    Raises:
        HTTPException: If lullaby not found or access denied
    """
    try:
        # Extract token from header or query param
        token = firebase_token
        if not token and authorization:
            if authorization.startswith('Bearer '):
                token = authorization[7:]
            else:
                token = authorization
        
        if not token:
            raise HTTPException(status_code=401, detail="Firebase token required")
        
        # Verify Firebase token
        user_id = await verify_firebase_token(token)
        
        # Get lullaby from Firestore
        db = get_firestore_client()
        if not db:
            raise HTTPException(status_code=503, detail="Database service unavailable")
        
        lullaby_doc = db.collection('lullabies').document(lullaby_id).get()
        
        if not lullaby_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Lullaby not found"
            )
        
        lullaby_data = lullaby_doc.to_dict()
        
        # Verify ownership
        if lullaby_data.get('user_id') != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
        
        # Delete lullaby
        db.collection('lullabies').document(lullaby_id).delete()
        
        return {
            "success": True,
            "message": "Lullaby deleted successfully",
            "lullaby_id": lullaby_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Failed to delete lullaby: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete lullaby: {str(e)}"
        )
