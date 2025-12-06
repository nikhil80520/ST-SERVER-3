"""
Reference Images Service (PostgreSQL)
Handles reference image CRUD operations with PostgreSQL database
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from src.db.models import UserReferenceImage, User


class ReferenceImageServicePostgreSQL:
    """Reference image service using PostgreSQL"""
    
    async def _get_user_id_from_firebase_id(self, db: AsyncSession, firebase_user_id: str) -> Optional[int]:
        """Helper to convert firebase_user_id (string) to integer user_id"""
        try:
            stmt = select(User.user_id).where(User.firebase_user_id == firebase_user_id)
            result = await db.execute(stmt)
            user_id = result.scalar_one_or_none()
            
            if user_id:
                return user_id
            
            # User doesn't exist - auto-create minimal user
            from src.user.service_pg import UserServicePostgreSQL
            user_service = UserServicePostgreSQL()
            user = await user_service.get_or_create_minimal_user(db, firebase_user_id)
            return user.user_id
            
        except Exception as e:
            print(f"❌ Error getting user_id from firebase_user_id: {str(e)}")
            return None
    
    async def get_user_reference_images(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        limit: int = 20,
        offset: int = 0,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get paginated reference images for a user
        
        Args:
            db: Database session
            firebase_user_id: Firebase user ID (string)
            limit: Number of images to return
            offset: Number of images to skip
            category: Optional category filter
            
        Returns:
            List of reference image dictionaries
        """
        try:
            # Convert firebase_user_id to integer user_id
            user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not user_id:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Build query
            stmt = select(UserReferenceImage).where(UserReferenceImage.user_id == user_id)
            
            if category:
                stmt = stmt.where(UserReferenceImage.category == category)
            
            stmt = stmt.order_by(UserReferenceImage.created_at.desc()).offset(offset).limit(limit)
            
            result = await db.execute(stmt)
            images = result.scalars().all()
            
            return [
                {
                    "reference_image_id": img.user_reference_image_id,
                    "user_id": img.user_id,
                    "title": img.title,
                    "description": img.description,
                    "image_url": img.image_url,
                    "age_group": img.age_group,
                    "category": img.category,
                    "created_at": img.created_at,
                    "updated_at": img.updated_at
                }
                for img in images
            ]
            
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Error fetching reference images: {str(e)}")
            return []
    
    async def get_total_reference_images_count(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        category: Optional[str] = None
    ) -> int:
        """Get total count of reference images for a user"""
        try:
            user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not user_id:
                return 0
            
            stmt = select(func.count(UserReferenceImage.user_reference_image_id)).where(
                UserReferenceImage.user_id == user_id
            )
            
            if category:
                stmt = stmt.where(UserReferenceImage.category == category)
            
            result = await db.execute(stmt)
            return result.scalar() or 0
            
        except Exception as e:
            print(f"❌ Error getting reference images count: {str(e)}")
            return 0
    
    async def create_reference_image(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        title: str,
        image_url: str,
        description: Optional[str] = None,
        age_group: Optional[str] = None,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new reference image for a user
        
        Args:
            db: Database session
            firebase_user_id: Firebase user ID (string)
            title: Image title
            image_url: URL to the image
            description: Optional description
            age_group: Optional age group
            category: Optional category
            
        Returns:
            Reference image data dictionary
        """
        try:
            # Convert firebase_user_id to integer user_id
            user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not user_id:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Create reference image record
            ref_image = UserReferenceImage(
                user_id=user_id,
                title=title,
                description=description,
                image_url=image_url,
                age_group=age_group,
                category=category
            )
            
            db.add(ref_image)
            await db.flush()
            await db.refresh(ref_image)
            
            print(f"✅ Reference image created: {ref_image.user_reference_image_id} for user {firebase_user_id}")
            
            return {
                "reference_image_id": ref_image.user_reference_image_id,
                "user_id": user_id,
                "title": title,
                "description": description,
                "image_url": image_url,
                "age_group": age_group,
                "category": category,
                "created_at": ref_image.created_at,
                "updated_at": ref_image.updated_at
            }
            
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            print(f"❌ Error creating reference image: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create reference image: {str(e)}")
    
    async def delete_reference_image(
        self,
        db: AsyncSession,
        reference_image_id: int,
        firebase_user_id: str
    ) -> bool:
        """
        Delete a reference image
        
        Args:
            db: Database session
            reference_image_id: Reference image ID to delete
            firebase_user_id: Firebase user ID (for ownership verification)
            
        Returns:
            True if deleted successfully
        """
        try:
            # Convert firebase_user_id to integer user_id
            user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not user_id:
                return False
            
            # Verify ownership and delete
            stmt = select(UserReferenceImage).where(
                (UserReferenceImage.user_reference_image_id == reference_image_id) &
                (UserReferenceImage.user_id == user_id)
            )
            
            result = await db.execute(stmt)
            ref_image = result.scalar_one_or_none()
            
            if not ref_image:
                return False
            
            await db.delete(ref_image)
            await db.flush()
            
            print(f"✅ Reference image deleted: {reference_image_id}")
            return True
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error deleting reference image: {str(e)}")
            return False


# Create service instance
reference_image_service_pg = ReferenceImageServicePostgreSQL()
