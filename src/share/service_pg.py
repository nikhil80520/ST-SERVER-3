"""
Story Sharing Service - PostgreSQL Implementation

Handles:
- Enabling/disabling story sharing
- Generating share tokens and deep links
- Managing share settings (expiration, copy permissions, analytics)
- Copying shared stories to user's library
- Share analytics and dashboard data
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, update, delete
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import secrets
import uuid

from src.db.models import  Story, Child, User
from src.share.schema import ShareSettings, StoryAnalytics, SharingDashboard
from src.common_function.storage_s3_service import S3StorageService
from src.common_function.qr_generator import create_qr_code
from src.core.config import settings


class ShareServicePostgreSQL:
    """Service for managing story sharing with PostgreSQL"""
    
    def __init__(self):
        self.s3_service = S3StorageService()
        self.base_share_url = settings.app_deep_link_base  # e.g., "storymagic://share/"
    
    def _generate_share_token(self) -> str:
        """Generate a secure share token"""
        return secrets.token_urlsafe(32)
    
    async def enable_story_sharing(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str,
        share_settings: ShareSettings,
        expires_at: Optional[datetime] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Enable sharing for a story and return share URL and QR code
        
        Args:
            db: Database session
            story_id: Story to share
            user_id: Owner user ID
            share_settings: Sharing configuration
            expires_at: Optional expiration datetime
            
        Returns:
            Tuple of (share_url, qr_code_url)
        """
        # Verify story belongs to user
        stmt = select(Story).where(
            and_(
                Story.story_id == story_id,
                Story.user_id == user_id
            )
        )
        result = await db.execute(stmt)
        story = result.scalar_one_or_none()
        
        if not story:
            raise ValueError(f"Story {story_id} not found or does not belong to user {user_id}")
        
        # Check if share already exists
        stmt = select(StoryShare).where(StoryShare.story_id == story_id)
        result = await db.execute(stmt)
        existing_share = result.scalar_one_or_none()
        
        if existing_share:
            # Update existing share
            existing_share.is_active = True
            existing_share.expires_at = expires_at
            existing_share.allow_copy = share_settings.allow_copy
            existing_share.show_creator = share_settings.show_creator
            existing_share.track_analytics = share_settings.track_analytics
            existing_share.updated_at = datetime.utcnow()
            share_token = existing_share.share_token
        else:
            # Create new share
            share_token = self._generate_share_token()
            new_share = StoryShare(
                share_id=f"share_{uuid.uuid4().hex[:16]}",
                story_id=story_id,
                owner_id=user_id,
                share_token=share_token,
                is_active=True,
                expires_at=expires_at,
                allow_copy=share_settings.allow_copy,
                show_creator=share_settings.show_creator,
                track_analytics=share_settings.track_analytics,
                view_count=0,
                copy_count=0
            )
            db.add(new_share)
        
        await db.commit()
        
        # Generate share URL
        share_url = f"{self.base_share_url}{share_token}"
        
        # Generate QR code and upload to S3
        qr_code_url = None
        try:
            qr_code_bytes = create_qr_code(share_url)
            qr_code_path = f"qr_codes/{user_id}/{story_id}.png"
            qr_code_url = await self.s3_service.upload_file(
                file_data=qr_code_bytes,
                file_path=qr_code_path,
                content_type="image/png"
            )
        except Exception as e:
            print(f"Warning: Failed to generate QR code: {e}")
        
        return share_url, qr_code_url
    
    async def disable_story_sharing(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str
    ) -> bool:
        """
        Disable sharing for a story
        
        Args:
            db: Database session
            story_id: Story to disable sharing
            user_id: Owner user ID
            
        Returns:
            True if successful
        """
        stmt = (
            update(StoryShare)
            .where(
                and_(
                    StoryShare.story_id == story_id,
                    StoryShare.owner_id == user_id
                )
            )
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        result = await db.execute(stmt)
        await db.commit()
        
        return result.rowcount > 0
    
    async def get_shared_story(
        self,
        db: AsyncSession,
        share_token: str,
        viewer_user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get shared story details by share token
        
        Args:
            db: Database session
            share_token: Share token from URL
            viewer_user_id: Optional user viewing the story
            
        Returns:
            Story data if share is valid, None otherwise
        """
        # Get share record with story data
        stmt = (
            select(StoryShare, Story, User)
            .join(Story, StoryShare.story_id == Story.story_id)
            .join(User, Story.user_id == User.user_id)
            .where(
                and_(
                    StoryShare.share_token == share_token,
                    StoryShare.is_active == True
                )
            )
        )
        result = await db.execute(stmt)
        row = result.first()
        
        if not row:
            return None
        
        share, story, owner = row
        
        # Check expiration
        if share.expires_at and share.expires_at < datetime.utcnow():
            return None
        
        # Track view if analytics enabled
        if share.track_analytics:
            share.view_count += 1
            await db.commit()
        
        # Build response
        story_data = {
            "story_id": story.story_id,
            "title": story.title,
            "audio_url": story.audio_url,
            "image_url": story.image_url,
            "duration": story.duration,
            "created_at": story.created_at,
            "child_name": story.child_name,
            "sharing_settings": {
                "allow_copy": share.allow_copy,
                "show_creator": share.show_creator,
                "track_analytics": share.track_analytics
            }
        }
        
        if share.show_creator:
            story_data["creator"] = {
                "user_id": owner.user_id,
                "username": owner.username or owner.email.split("@")[0]
            }
        
        return story_data
    
    async def copy_shared_story(
        self,
        db: AsyncSession,
        share_token: str,
        recipient_user_id: str,
        recipient_child_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Copy a shared story to recipient's library
        
        Args:
            db: Database session
            share_token: Share token from URL
            recipient_user_id: User copying the story
            recipient_child_id: Optional child to associate with
            
        Returns:
            New story ID if successful, None otherwise
        """
        # Get share record
        stmt = (
            select(StoryShare, Story)
            .join(Story, StoryShare.story_id == Story.story_id)
            .where(
                and_(
                    StoryShare.share_token == share_token,
                    StoryShare.is_active == True,
                    StoryShare.allow_copy == True
                )
            )
        )
        result = await db.execute(stmt)
        row = result.first()
        
        if not row:
            return None
        
        share, original_story = row
        
        # Check expiration
        if share.expires_at and share.expires_at < datetime.utcnow():
            return None
        
        # Create copy of story
        new_story_id = f"story_{uuid.uuid4().hex[:16]}"
        new_story = Story(
            story_id=new_story_id,
            user_id=recipient_user_id,
            child_id=recipient_child_id,
            title=f"{original_story.title} (Shared)",
            audio_url=original_story.audio_url,  # Reuse S3 URLs
            image_url=original_story.image_url,
            duration=original_story.duration,
            child_name=original_story.child_name,
            age=original_story.age,
            story_theme=original_story.story_theme,
            moral_lesson=original_story.moral_lesson,
            parent_context=original_story.parent_context,
            is_favorite=False,
            metadata={
                **original_story.metadata,
                "copied_from": original_story.story_id,
                "shared_by": share.owner_id
            }
        )
        db.add(new_story)
        
        # Track copy if analytics enabled
        if share.track_analytics:
            share.copy_count += 1
        
        await db.commit()
        
        return new_story_id
    
    async def get_story_analytics(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str
    ) -> Optional[StoryAnalytics]:
        """
        Get analytics for a shared story
        
        Args:
            db: Database session
            story_id: Story to get analytics for
            user_id: Owner user ID
            
        Returns:
            Analytics data or None if not shared
        """
        stmt = select(StoryShare).where(
            and_(
                StoryShare.story_id == story_id,
                StoryShare.owner_id == user_id
            )
        )
        result = await db.execute(stmt)
        share = result.scalar_one_or_none()
        
        if not share:
            return None
        
        return StoryAnalytics(
            story_id=story_id,
            view_count=share.view_count,
            copy_count=share.copy_count,
            is_active=share.is_active,
            created_at=share.created_at,
            expires_at=share.expires_at
        )
    
    async def get_sharing_dashboard(
        self,
        db: AsyncSession,
        user_id: str
    ) -> SharingDashboard:
        """
        Get dashboard of all shares for a user
        
        Args:
            db: Database session
            user_id: User ID
            
        Returns:
            Dashboard with share statistics
        """
        # Get all shares by user
        stmt = (
            select(StoryShare, Story)
            .join(Story, StoryShare.story_id == Story.story_id)
            .where(StoryShare.owner_id == user_id)
            .order_by(StoryShare.created_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        
        total_shares = len(rows)
        active_shares = sum(1 for share, _ in rows if share.is_active)
        total_views = sum(share.view_count for share, _ in rows)
        total_copies = sum(share.copy_count for share, _ in rows)
        
        shared_stories = []
        for share, story in rows:
            shared_stories.append({
                "story_id": story.story_id,
                "title": story.title,
                "share_token": share.share_token,
                "is_active": share.is_active,
                "view_count": share.view_count,
                "copy_count": share.copy_count,
                "created_at": share.created_at,
                "expires_at": share.expires_at
            })
        
        return SharingDashboard(
            total_shares=total_shares,
            active_shares=active_shares,
            total_views=total_views,
            total_copies=total_copies,
            shared_stories=shared_stories
        )
    
    async def renew_share_link(
        self,
        db: AsyncSession,
        story_id: str,
        user_id: str,
        new_expires_at: Optional[datetime] = None
    ) -> Tuple[str, Optional[datetime]]:
        """
        Renew share link with new expiration or new token
        
        Args:
            db: Database session
            story_id: Story to renew
            user_id: Owner user ID
            new_expires_at: New expiration time
            
        Returns:
            Tuple of (new_share_url, expires_at)
        """
        stmt = select(StoryShare).where(
            and_(
                StoryShare.story_id == story_id,
                StoryShare.owner_id == user_id
            )
        )
        result = await db.execute(stmt)
        share = result.scalar_one_or_none()
        
        if not share:
            raise ValueError(f"No share found for story {story_id}")
        
        # Generate new token
        new_token = self._generate_share_token()
        share.share_token = new_token
        share.expires_at = new_expires_at
        share.is_active = True
        share.updated_at = datetime.utcnow()
        
        await db.commit()
        
        new_share_url = f"{self.base_share_url}{new_token}"
        return new_share_url, new_expires_at
    
    async def batch_update_shares(
        self,
        db: AsyncSession,
        user_id: str,
        story_ids: List[str],
        is_active: Optional[bool] = None,
        expires_at: Optional[datetime] = None
    ) -> int:
        """
        Batch update multiple story shares
        
        Args:
            db: Database session
            user_id: Owner user ID
            story_ids: List of story IDs to update
            is_active: Optional active status
            expires_at: Optional expiration time
            
        Returns:
            Number of shares updated
        """
        update_values = {"updated_at": datetime.utcnow()}
        if is_active is not None:
            update_values["is_active"] = is_active
        if expires_at is not None:
            update_values["expires_at"] = expires_at
        
        stmt = (
            update(StoryShare)
            .where(
                and_(
                    StoryShare.owner_id == user_id,
                    StoryShare.story_id.in_(story_ids)
                )
            )
            .values(**update_values)
        )
        result = await db.execute(stmt)
        await db.commit()
        
        return result.rowcount
    
    async def delete_expired_shares(
        self,
        db: AsyncSession
    ) -> int:
        """
        Delete expired shares (maintenance task)
        
        Args:
            db: Database session
            
        Returns:
            Number of shares deleted
        """
        stmt = (
            update(StoryShare)
            .where(
                and_(
                    StoryShare.expires_at.isnot(None),
                    StoryShare.expires_at < datetime.utcnow()
                )
            )
            .values(is_active=False, updated_at=datetime.utcnow())
        )
        result = await db.execute(stmt)
        await db.commit()
        
        return result.rowcount


# Create singleton instance
share_service_pg = ShareServicePostgreSQL()
