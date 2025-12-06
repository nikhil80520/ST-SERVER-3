"""
Voice Clone Service using PostgreSQL
Handles voice clone CRUD operations with PostgreSQL database
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from src.db.models import UserVoiceClone, User


class VoiceCloneServicePostgreSQL:
    """Voice clone service using PostgreSQL"""
    
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
    
    async def create_voice_clone(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        name: str,
        cartesia_voice_id: str,
        description: Optional[str] = None,
        language: str = "en",
        sample_audio_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new voice clone for a user
        
        Args:
            db: Database session
            firebase_user_id: Firebase user ID (string)
            name: Voice clone name
            cartesia_voice_id: Cartesia API voice ID
            description: Optional description
            language: Language code (default: "en")
            sample_audio_url: Optional sample audio URL
            
        Returns:
            Voice clone data dictionary
        """
        try:
            # Convert firebase_user_id to integer user_id
            user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not user_id:
                raise HTTPException(status_code=404, detail="User not found")
            
            # Create voice clone record
            voice_clone = UserVoiceClone(
                user_id=user_id,
                name=name,
                cartesia_voice_id=cartesia_voice_id,
                description=description,
                language=language,
                sample_audio_url=sample_audio_url,
                is_active=True
            )
            
            db.add(voice_clone)
            await db.flush()
            
            # Get the created voice clone with ID
            await db.refresh(voice_clone)
            
            print(f"✅ Voice clone created: {voice_clone.user_voice_clone_id} for user {firebase_user_id}")
            
            # Return dictionary with all attributes BEFORE any additional operations
            result = {
                "voice_clone_id": voice_clone.user_voice_clone_id,
                "user_id": user_id,
                "name": name,
                "cartesia_voice_id": cartesia_voice_id,
                "description": description,
                "language": language,
                "sample_audio_url": sample_audio_url,
                "is_active": voice_clone.is_active,
                "created_at": voice_clone.created_at.isoformat() if voice_clone.created_at else None,
                "updated_at": voice_clone.updated_at.isoformat() if voice_clone.updated_at else None
            }
            
            return result
            
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            print(f"❌ Error creating voice clone: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create voice clone: {str(e)}")
    
    async def get_user_voice_clones(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        active_only: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get all voice clones for a user
        
        Args:
            db: Database session
            firebase_user_id: Firebase user ID (string)
            active_only: If True, only return active voice clones
            
        Returns:
            List of voice clone dictionaries
        """
        try:
            # Use JOIN to get voice clones
            stmt = (
                select(UserVoiceClone)
                .join(User, UserVoiceClone.user_id == User.user_id)
                .where(User.firebase_user_id == firebase_user_id)
                .order_by(UserVoiceClone.created_at.desc())
            )
            
            if active_only:
                stmt = stmt.where(UserVoiceClone.is_active == True)
            
            result = await db.execute(stmt)
            voice_clones = result.scalars().all()
            
            return [
                {
                    "voice_clone_id": vc.user_voice_clone_id,
                    "voice_id": vc.cartesia_voice_id,
                    "voice_name": vc.name,
                    "description": vc.description,
                    "language": vc.language,
                    "sample_audio_url": vc.sample_audio_url,
                    "is_active": vc.is_active,
                    "created_at": vc.created_at.isoformat(),
                    "updated_at": vc.updated_at.isoformat()
                }
                for vc in voice_clones
            ]
            
        except Exception as e:
            print(f"❌ Error getting voice clones: {str(e)}")
            return []
    
    async def get_voice_clone_by_id(
        self,
        db: AsyncSession,
        voice_clone_id: int,
        firebase_user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a specific voice clone by ID (with ownership verification)"""
        try:
            stmt = (
                select(UserVoiceClone)
                .join(User, UserVoiceClone.user_id == User.user_id)
                .where(
                    UserVoiceClone.user_voice_clone_id == voice_clone_id,
                    User.firebase_user_id == firebase_user_id
                )
            )
            
            result = await db.execute(stmt)
            vc = result.scalar_one_or_none()
            
            if not vc:
                return None
            
            return {
                "voice_clone_id": vc.user_voice_clone_id,
                "voice_id": vc.cartesia_voice_id,
                "voice_name": vc.name,
                "description": vc.description,
                "language": vc.language,
                "sample_audio_url": vc.sample_audio_url,
                "is_active": vc.is_active,
                "created_at": vc.created_at.isoformat(),
                "updated_at": vc.updated_at.isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error getting voice clone: {str(e)}")
            return None
    
    async def update_voice_clone(
        self,
        db: AsyncSession,
        voice_clone_id: int,
        firebase_user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> bool:
        """Update voice clone metadata"""
        try:
            # Build update data
            update_data = {"updated_at": datetime.utcnow()}
            
            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description
            if is_active is not None:
                update_data["is_active"] = is_active
            
            # Update with ownership verification using subquery
            stmt = (
                update(UserVoiceClone)
                .where(
                    UserVoiceClone.user_voice_clone_id == voice_clone_id,
                    UserVoiceClone.user_id.in_(
                        select(User.user_id).where(User.firebase_user_id == firebase_user_id)
                    )
                )
                .values(**update_data)
            )
            
            result = await db.execute(stmt)
            await db.commit()
            
            return result.rowcount > 0
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error updating voice clone: {str(e)}")
            return False
    
    async def delete_voice_clone(
        self,
        db: AsyncSession,
        voice_clone_id: int,
        firebase_user_id: str
    ) -> bool:
        """Delete a voice clone"""
        try:
            stmt = (
                delete(UserVoiceClone)
                .where(
                    UserVoiceClone.user_voice_clone_id == voice_clone_id,
                    UserVoiceClone.user_id.in_(
                        select(User.user_id).where(User.firebase_user_id == firebase_user_id)
                    )
                )
            )
            
            result = await db.execute(stmt)
            await db.commit()
            
            return result.rowcount > 0
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error deleting voice clone: {str(e)}")
            return False


# Global singleton instance
voice_clone_service_pg = VoiceCloneServicePostgreSQL()
