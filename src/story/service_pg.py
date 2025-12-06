"""
Story Service Module
Contains all business logic for story management using PostgreSQL.
Handles story metadata storage, retrieval, and deletion with S3 for media files.
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import HTTPException
from sqlalchemy import select, update, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Story, User, Child
from src.common_function.storage_s3_service import S3StorageService
import uuid


class StoryService:
    """
    Story service using PostgreSQL with S3 for media storage.
    All methods use SQLAlchemy ORM for database operations.
    Handles story creation, retrieval, deletion, and sharing.
    """
    
    def __init__(self):
        self._storage_service = None
    
    @property
    def storage_service(self):
        """Lazy initialization of S3 storage service"""
        if self._storage_service is None:
            self._storage_service = S3StorageService()
        return self._storage_service
    
    async def _get_user_id_from_firebase_id(self, db: AsyncSession, firebase_user_id: str) -> Optional[int]:
        """Helper to convert firebase_user_id (string) to integer user_id, auto-creating if needed"""
        try:
            # Try to get existing user
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
            print(f"❌ Error getting/creating user_id from firebase_user_id: {str(e)}")
            return None
    
    async def save_story_metadata(
        self,
        db: AsyncSession,
        story_id: int,  # PostgreSQL auto-increment integer
        user_id: str,  # firebase_user_id (string)
        title: str,
        prompt: str,
        manifest: Dict,
        child_id: int = None,  # Also integer now
        child_snapshot: Dict = None
    ):
        """
        Save story metadata to PostgreSQL with S3 storage info.
        Updates user's story count automatically via database triggers or manual update.
        
        Args:
            story_id: PostgreSQL auto-increment integer ID
            user_id: Firebase user ID (string)
            child_id: PostgreSQL integer child_id
        """
        try:
            # Convert firebase_user_id to integer user_id
            firebase_user_id = user_id
            integer_user_id = await self._get_user_id_from_firebase_id(db, firebase_user_id)
            if not integer_user_id:
                raise HTTPException(status_code=404, detail="User not found in database")
            # Extract scene data and audio URLs from manifest
            scenes_data = manifest.get('scenes', [])
            audio_urls = []
            
            for i, scene in enumerate(scenes_data):
                if 'audio_url' in scene:
                    audio_urls.append(scene['audio_url'])
            
            # Determine thumbnail URL
            thumbnail_url = manifest.get('thumbnail_url')
            if not thumbnail_url and scenes_data and len(scenes_data) > 0:
                thumbnail_url = scenes_data[0].get('image_url')
            
            # Create story record with INTEGER IDs
            story = Story(
                story_id=story_id,  # Integer from PostgreSQL autoincrement
                user_id=integer_user_id,  # Use integer user_id
                child_id=child_id,
                title=title,
                user_prompt=prompt,
                status=manifest.get('status', 'completed'),
                child_snapshot=child_snapshot,
                manifest=manifest,
                scenes_data=scenes_data,
                audio_urls=audio_urls,
                thumbnail_url=thumbnail_url,
                is_shareable=False,
                view_count=0
            )
            
            db.add(story)
            await db.flush()
            
            # Update user's story count
            stmt = (
                update(User)
                .where(User.user_id == integer_user_id)  # Use integer user_id
                .values(
                    story_count=User.story_count + 1,
                    last_active=datetime.utcnow()
                )
            )
            await db.execute(stmt)
            
            await db.commit()
            
            print(f"✅ Story metadata saved to PostgreSQL: {story_id} for user {firebase_user_id} (user_id={integer_user_id})")
            return True
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Failed to save story metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to save story: {str(e)}")
    
    async def get_story(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get story by ID. If user_id provided, verify ownership.
        """
        try:
            stmt = select(Story).where(Story.story_id == story_id)
            
            if user_id:
                stmt = stmt.where(Story.user_id == user_id)
            
            result = await db.execute(stmt)
            story = result.scalar_one_or_none()
            
            if not story:
                return None
            
            return {
                'story_id': story.story_id,
                'user_id': story.user_id,
                'child_id': story.child_id,
                'title': story.title,
                'user_prompt': story.user_prompt,
                'status': story.status,
                'child_snapshot': story.child_snapshot,
                'manifest': story.manifest,
                'scenes_data': story.scenes_data,
                'audio_urls': story.audio_urls,
                'thumbnail_url': story.thumbnail_url,
                'is_shareable': story.is_shareable,
                'share_token': story.share_token,
                'view_count': story.view_count,
                'created_at': story.created_at.isoformat(),
                'updated_at': story.updated_at.isoformat()
            }
            
        except Exception as e:
            print(f"❌ Error getting story: {str(e)}")
            return None
    
    async def get_user_stories(
        self,
        db: AsyncSession,
        firebase_user_id: str,  # firebase_user_id (string)
        limit: int = 50,
        offset: int = 0,
        child_id: str = None,
        status_filter: str = None
    ) -> List[Dict[str, Any]]:
        """
        Get all stories for a user with optional filtering.
        Uses JOIN to efficiently convert firebase_user_id to user_id and fetch stories.
        """
        try:
            # Use JOIN to get stories directly from firebase_user_id
            stmt = (
                select(Story)
                .join(User, Story.user_id == User.user_id)
                .where(User.firebase_user_id == firebase_user_id)
                .order_by(Story.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            
            # Apply filters
            if child_id:
                stmt = stmt.where(Story.child_id == child_id)
            
            if status_filter:
                stmt = stmt.where(Story.status == status_filter)
            
            result = await db.execute(stmt)
            stories = result.scalars().all()
            
            return [
                {
                    'story_id': story.story_id,
                    'user_id': story.user_id,
                    'child_id': story.child_id,
                    'title': story.title,
                    'genre': story.genre,
                    'story_length': story.story_length,
                    'thumbnail_url': story.thumbnail_url,
                    'age_group': story.age_group,
                    'art_style': story.art_style,
                    'moral_lesson': story.moral_lesson,
                    'target_emotion': story.target_emotion,
                    'created_at': story.created_at.isoformat() if story.created_at else None,
                    'updated_at': story.updated_at.isoformat() if story.updated_at else None
                }
                for story in stories
            ]
            
        except Exception as e:
            print(f"❌ Error getting user stories: {str(e)}")
            return []
    
    async def delete_story(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str
    ) -> bool:
        """
        Delete a story and its associated media from S3.
        """
        try:
            # Get story first to retrieve S3 keys
            story_data = await self.get_story(db, story_id, user_id)
            if not story_data:
                raise HTTPException(status_code=404, detail="Story not found")
            
            # Delete from database
            stmt = delete(Story).where(
                Story.story_id == story_id,
                Story.user_id == user_id
            )
            result = await db.execute(stmt)
            
            if result.rowcount == 0:
                return False
            
            # Update user's story count
            stmt = (
                update(User)
                .where(User.user_id == user_id)
                .values(
                    story_count=User.story_count - 1,
                    last_active=datetime.utcnow()
                )
            )
            await db.execute(stmt)
            
            await db.commit()
            
            # Delete media files from S3 asynchronously
            try:
                # Delete audio files
                for audio_url in story_data.get('audio_urls', []):
                    if 's3.amazonaws.com' in audio_url:
                        key = audio_url.split('.com/')[-1]
                        await self.storage_service.delete_file(key)
                
                # Delete images from scenes
                scenes = story_data.get('scenes_data', [])
                for scene in scenes:
                    if 'image_url' in scene and 's3.amazonaws.com' in scene['image_url']:
                        key = scene['image_url'].split('.com/')[-1]
                        await self.storage_service.delete_file(key)
                
                # Delete thumbnail
                if story_data.get('thumbnail_url') and 's3.amazonaws.com' in story_data['thumbnail_url']:
                    key = story_data['thumbnail_url'].split('.com/')[-1]
                    await self.storage_service.delete_file(key)
                
                print(f"✅ Deleted story media from S3: {story_id}")
            except Exception as e:
                print(f"⚠️ Failed to delete some media files: {str(e)}")
            
            print(f"✅ Deleted story from PostgreSQL: {story_id}")
            return True
            
        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            print(f"❌ Error deleting story: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to delete story: {str(e)}")
    
    async def update_story_shareability(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str,
        is_shareable: bool,
        share_token: str = None
    ) -> bool:
        """
        Update story sharing settings.
        """
        try:
            update_data = {
                'is_shareable': is_shareable,
                'updated_at': datetime.utcnow()
            }
            
            if share_token:
                update_data['share_token'] = share_token
            
            stmt = (
                update(Story)
                .where(
                    Story.story_id == story_id,
                    Story.user_id == user_id
                )
                .values(**update_data)
            )
            
            result = await db.execute(stmt)
            await db.commit()
            
            return result.rowcount > 0
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error updating story shareability: {str(e)}")
            return False
    
    async def increment_story_views(
        self,
        db: AsyncSession,
        story_id: str
    ) -> bool:
        """
        Increment story view count.
        """
        try:
            stmt = (
                update(Story)
                .where(Story.story_id == story_id)
                .values(view_count=Story.view_count + 1)
            )
            
            await db.execute(stmt)
            await db.commit()
            return True
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error incrementing views: {str(e)}")
            return False
    
    async def get_story_count(
        self,
        db: AsyncSession,
        firebase_user_id: str  # firebase_user_id (string)
    ) -> int:
        """
        Get total story count for a user.
        Uses JOIN to efficiently convert firebase_user_id to user_id.
        """
        try:
            # Use JOIN to count stories directly from firebase_user_id
            stmt = (
                select(func.count(Story.story_id))
                .join(User, Story.user_id == User.user_id)
                .where(User.firebase_user_id == firebase_user_id)
            )
            result = await db.execute(stmt)
            return result.scalar() or 0
            
        except Exception as e:
            print(f"❌ Error getting story count: {str(e)}")
            return 0


# Global singleton instance
story_service = StoryService()

# Backward compatibility alias
story_service_pg = story_service
StoryServicePostgreSQL = StoryService
