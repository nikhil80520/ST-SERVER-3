"""
Story Persistence Service - PostgreSQL + S3
Handles complete story-generation saving pipeline with S3 media uploads
All generated content (story metadata, scenes, images, audio) stored in database
All media files uploaded to S3 bucket 'june_story'
"""
import uuid
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.models.story import Story, StoryScene, StorySceneImage, StorySceneAudio
from src.common_function.s3_client import get_s3_client, get_s3_bucket_name
from src.core.config import settings


class StoryPersistenceService:
    """Service for persisting complete story data to PostgreSQL with S3 media storage"""
    
    def __init__(self):
        self.s3_client = get_s3_client()
        self.bucket_name = get_s3_bucket_name() or "june_story"
        
        if self.s3_client:
            print(f"✅ Story Persistence Service initialized with S3 bucket: {self.bucket_name}")
        else:
            print("⚠️ S3 client not available - media uploads will fail")
    
    async def upload_to_s3(
        self,
        file_data: bytes,
        key: str,
        content_type: str,
        acl: str = 'public-read'
    ) -> str:
        """
        Upload file to S3 bucket and return public URL
        
        Args:
            file_data: Raw bytes of the file
            key: S3 object key (path)
            content_type: MIME type (e.g., 'image/png', 'audio/mpeg')
            acl: Access control (default: public-read)
            
        Returns:
            str: Public S3 URL
        """
        if not self.s3_client:
            raise Exception("S3 client not initialized - cannot upload media")
        
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_data,
                ContentType=content_type,
                ACL=acl,
                CacheControl='max-age=31536000'  # 1 year cache
            )
            
            # Construct public URL
            url = f"https://{self.bucket_name}.s3.{settings.aws.region}.amazonaws.com/{key}"
            return url
            
        except Exception as e:
            print(f"❌ S3 upload failed for {key}: {str(e)}")
            raise
    
    async def save_complete_story(
        self,
        db: AsyncSession,
        user_id: int,
        child_id: int,
        story_data: Dict,
        thumbnail_data: Optional[bytes] = None,
        scene_images_data: Optional[List[bytes]] = None,
        scene_audio_data: Optional[List[bytes]] = None
    ) -> Story:
        """
        Save complete story with all scenes, images, and audio to PostgreSQL + S3
        
        PIPELINE:
        1. Create Story record with metadata
        2. Upload thumbnail to S3 (if provided) and update Story.thumbnail_url
        3. For each scene:
           - Create StoryScene with metadata (no image/audio URLs)
           - Upload scene image to S3
           - Create StorySceneImage with S3 URL
           - Upload scene audio to S3  
           - Create StorySceneAudio with S3 URL
        4. Commit transaction
        
        Args:
            db: Database session
            user_id: Integer user ID (from User table)
            child_id: Integer child ID (from Child table)
            story_data: Complete story manifest with scenes metadata
            thumbnail_data: Raw bytes of thumbnail image (optional)
            scene_images_data: List of raw image bytes for each scene (optional)
            scene_audio_data: List of raw audio bytes for each scene (optional)
            
        Returns:
            Story: Created story object with all relationships
        """
        try:
            # Generate unique story ID for S3 paths
            story_uuid = str(uuid.uuid4())
            
            # Extract morals handling (can be list or string)
            morals_value = story_data.get('morals')
            if isinstance(morals_value, list):
                morals_str = ', '.join(morals_value)
            elif morals_value:
                morals_str = str(morals_value)
            else:
                morals_str = None
            
            # Create Story record
            story = Story(
                user_id=user_id,
                child_id=child_id,
                title=story_data.get('title', 'Untitled Story'),
                genre=story_data.get('genre'),
                story_length=story_data.get('story_length'),
                thumbnail_url=None,  # Will be updated after S3 upload
                duration=story_data.get('total_duration'),
                target_scenes=story_data.get('target_scenes'),
                age_group=story_data.get('age_group'),
                child_name=story_data.get('child_name'),
                child_age=story_data.get('child_age'),
                story_theme=story_data.get('user_prompt'),
                moral_lesson=story_data.get('moral_lesson'),
                morals=morals_str,
                target_emotion=story_data.get('target_emotion'),
                art_style=story_data.get('art_style'),
                ambient_sound=story_data.get('ambient_sound'),
                thumbnail_prompt=story_data.get('thumbnail_prompt'),
                parent_context=story_data.get('parent_context')
            )
            
            db.add(story)
            await db.flush()  # Get story_id without committing
            
            story_id_int = story.story_id
            print(f"📝 Created story record: story_id={story_id_int}, title={story.title}")
            
            # Upload thumbnail to S3 if provided
            if thumbnail_data:
                try:
                    thumbnail_key = f"stories/{story_uuid}/thumbnail.png"
                    thumbnail_url = await self.upload_to_s3(
                        file_data=thumbnail_data,
                        key=thumbnail_key,
                        content_type='image/png'
                    )
                    story.thumbnail_url = thumbnail_url
                    print(f"📸 Thumbnail uploaded: {thumbnail_url}")
                except Exception as e:
                    print(f"⚠️ Thumbnail upload failed: {str(e)}")
            
            # Process scenes
            scenes_data = story_data.get('scenes', [])
            print(f"📚 Processing {len(scenes_data)} scenes...")
            
            for idx, scene_data in enumerate(scenes_data):
                scene_number = scene_data.get('scene_number', idx + 1)
                
                # Create StoryScene (metadata only, no image/audio URLs)
                story_scene = StoryScene(
                    story_id=story_id_int,
                    scene_number=scene_number,
                    includes_child=scene_data.get('includes_child', False),
                    emotion=scene_data.get('emotion'),
                    reference_image_ids=scene_data.get('reference_image_ids', [])
                )
                
                db.add(story_scene)
                await db.flush()  # Get story_scene_id
                
                scene_id = story_scene.story_scene_id
                print(f"  Scene {scene_number}: story_scene_id={scene_id}")
                
                # Upload scene image to S3 and create StorySceneImage
                if scene_images_data and idx < len(scene_images_data):
                    try:
                        image_key = f"stories/{story_uuid}/scenes/scene_{scene_number:03d}.png"
                        image_url = await self.upload_to_s3(
                            file_data=scene_images_data[idx],
                            key=image_key,
                            content_type='image/png'
                        )
                        
                        scene_image = StorySceneImage(
                            story_scene_id=scene_id,
                            text=scene_data.get('text'),
                            visual_prompt=scene_data.get('visual_prompt'),
                            image_url=image_url,
                            image_type='scene'
                        )
                        db.add(scene_image)
                        print(f"    🖼️  Image uploaded: {image_url}")
                        
                    except Exception as e:
                        print(f"⚠️ Scene {scene_number} image upload failed: {str(e)}")
                
                # Upload scene audio to S3 and create StorySceneAudio
                if scene_audio_data and idx < len(scene_audio_data):
                    try:
                        audio_key = f"stories/{story_uuid}/audio/scene_{scene_number:03d}.mp3"
                        audio_url = await self.upload_to_s3(
                            file_data=scene_audio_data[idx],
                            key=audio_key,
                            content_type='audio/mpeg'
                        )
                        
                        scene_audio = StorySceneAudio(
                            story_scene_id=scene_id,
                            text=scene_data.get('text'),
                            audio_url=audio_url,
                            audio_type='narration',
                            duration=scene_data.get('duration')
                        )
                        db.add(scene_audio)
                        print(f"    🔊 Audio uploaded: {audio_url}")
                        
                    except Exception as e:
                        print(f"⚠️ Scene {scene_number} audio upload failed: {str(e)}")
            
            # Commit all changes
            await db.commit()
            await db.refresh(story)
            
            print(f"✅ Successfully saved complete story to PostgreSQL + S3: {story_id_int}")
            print(f"   - Story: {story.title}")
            print(f"   - Scenes: {len(scenes_data)}")
            print(f"   - Thumbnail: {'✓' if story.thumbnail_url else '✗'}")
            
            return story
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error saving story: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    async def save_story_from_urls(
        self,
        db: AsyncSession,
        user_id: int,
        child_id: int,
        story_data: Dict
    ) -> Story:
        """
        Save complete story when media is already uploaded (URLs provided)
        
        Use this method when:
        - Images/audio are already uploaded to S3
        - story_data contains image_url and audio_url for each scene
        - thumbnail_url is already in story_data
        
        Args:
            db: Database session
            user_id: Integer user ID
            child_id: Integer child ID  
            story_data: Story manifest with scenes containing image_url/audio_url
            
        Returns:
            Story: Created story object
        """
        try:
            # Extract morals handling
            morals_value = story_data.get('morals')
            if isinstance(morals_value, list):
                morals_str = ', '.join(morals_value)
            elif morals_value:
                morals_str = str(morals_value)
            else:
                morals_str = None
            
            # Create Story record
            story = Story(
                user_id=user_id,
                child_id=child_id,
                title=story_data.get('title', 'Untitled Story'),
                genre=story_data.get('genre'),
                story_length=story_data.get('story_length'),
                thumbnail_url=story_data.get('thumbnail_url'),
                duration=story_data.get('total_duration'),
                target_scenes=story_data.get('target_scenes'),
                age_group=story_data.get('age_group'),
                child_name=story_data.get('child_name'),
                child_age=story_data.get('child_age'),
                story_theme=story_data.get('user_prompt'),
                moral_lesson=story_data.get('moral_lesson'),
                morals=morals_str,
                target_emotion=story_data.get('target_emotion'),
                art_style=story_data.get('art_style'),
                ambient_sound=story_data.get('ambient_sound'),
                thumbnail_prompt=story_data.get('thumbnail_prompt'),
                parent_context=story_data.get('parent_context')
            )
            
            db.add(story)
            await db.flush()
            
            story_id_int = story.story_id
            print(f"📝 Created story from URLs: story_id={story_id_int}, title={story.title}")
            
            # Process scenes
            scenes_data = story_data.get('scenes', [])
            
            for idx, scene_data in enumerate(scenes_data):
                scene_number = scene_data.get('scene_number', idx + 1)
                
                # Create StoryScene
                story_scene = StoryScene(
                    story_id=story_id_int,
                    scene_number=scene_number,
                    includes_child=scene_data.get('includes_child', False),
                    emotion=scene_data.get('emotion'),
                    reference_image_ids=scene_data.get('reference_image_ids', [])
                )
                
                db.add(story_scene)
                await db.flush()
                
                scene_id = story_scene.story_scene_id
                
                # Create StorySceneImage if URL provided
                if scene_data.get('image_url'):
                    scene_image = StorySceneImage(
                        story_scene_id=scene_id,
                        text=scene_data.get('text'),
                        visual_prompt=scene_data.get('visual_prompt'),
                        image_url=scene_data.get('image_url'),
                        image_type='scene'
                    )
                    db.add(scene_image)
                
                # Create StorySceneAudio if URL provided
                if scene_data.get('audio_url'):
                    scene_audio = StorySceneAudio(
                        story_scene_id=scene_id,
                        text=scene_data.get('text'),
                        audio_url=scene_data.get('audio_url'),
                        audio_type='narration',
                        duration=scene_data.get('duration')
                    )
                    db.add(scene_audio)
            
            await db.commit()
            await db.refresh(story)
            
            print(f"✅ Story saved from URLs: {story_id_int} with {len(scenes_data)} scenes")
            return story
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error saving story from URLs: {str(e)}")
            raise
    
    async def get_story_with_scenes(
        self,
        db: AsyncSession,
        story_id: int,
        user_id: int
    ) -> Optional[Dict]:
        """
        Retrieve complete story with all scenes, images, and audio
        
        Args:
            db: Database session
            story_id: Story ID
            user_id: User ID (for authorization)
            
        Returns:
            Dict: Complete story manifest or None if not found
        """
        try:
            # Query story with relationships
            query = select(Story).where(
                Story.story_id == story_id,
                Story.user_id == user_id
            )
            result = await db.execute(query)
            story = result.scalar_one_or_none()
            
            if not story:
                return None
            
            # Build manifest
            manifest = {
                'story_id': story.story_id,
                'title': story.title,
                'genre': story.genre,
                'story_length': story.story_length,
                'thumbnail_url': story.thumbnail_url,
                'total_duration': story.duration,
                'target_scenes': story.target_scenes,
                'age_group': story.age_group,
                'child_name': story.child_name,
                'child_age': story.child_age,
                'user_prompt': story.story_theme,
                'moral_lesson': story.moral_lesson,
                'morals': story.morals,
                'target_emotion': story.target_emotion,
                'art_style': story.art_style,
                'ambient_sound': story.ambient_sound,
                'thumbnail_prompt': story.thumbnail_prompt,
                'created_at': story.created_at.isoformat() if story.created_at else None,
                'scenes': []
            }
            
            # Build scenes with images and audio
            for scene in story.scenes:
                scene_data = {
                    'scene_number': scene.scene_number,
                    'includes_child': scene.includes_child,
                    'emotion': scene.emotion,
                    'reference_image_ids': scene.reference_image_ids or []
                }
                
                # Add image data
                if scene.images:
                    first_image = scene.images[0]
                    scene_data['text'] = first_image.text
                    scene_data['visual_prompt'] = first_image.visual_prompt
                    scene_data['image_url'] = first_image.image_url
                
                # Add audio data
                if scene.audio:
                    first_audio = scene.audio[0]
                    if not scene_data.get('text'):
                        scene_data['text'] = first_audio.text
                    scene_data['audio_url'] = first_audio.audio_url
                    scene_data['duration'] = first_audio.duration
                
                manifest['scenes'].append(scene_data)
            
            return manifest
            
        except Exception as e:
            print(f"❌ Error retrieving story: {str(e)}")
            return None
    
    async def get_user_stories(
        self,
        db: AsyncSession,
        user_id: int,
        limit: int = 20,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get all stories for a user with basic metadata (no scenes)
        
        Args:
            db: Database session
            user_id: User ID
            limit: Number of stories to return
            offset: Number of stories to skip
            
        Returns:
            List[Dict]: List of story summaries
        """
        try:
            query = (
                select(Story)
                .where(Story.user_id == user_id)
                .order_by(Story.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            
            result = await db.execute(query)
            stories = result.scalars().all()
            
            story_list = []
            for story in stories:
                story_list.append({
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
                    'total_scenes': len(story.scenes) if story.scenes else 0
                })
            
            return story_list
            
        except Exception as e:
            print(f"❌ Error getting user stories: {str(e)}")
            return []
    
    async def delete_story(
        self,
        db: AsyncSession,
        story_id: int,
        user_id: int
    ) -> bool:
        """
        Delete a story and all related scenes, images, and audio
        
        Args:
            db: Database session
            story_id: Story ID
            user_id: User ID (for authorization)
            
        Returns:
            bool: True if deleted, False otherwise
        """
        try:
            query = select(Story).where(
                Story.story_id == story_id,
                Story.user_id == user_id
            )
            result = await db.execute(query)
            story = result.scalar_one_or_none()
            
            if not story:
                return False
            
            # Delete story (cascade will handle scenes, images, audio)
            await db.delete(story)
            await db.commit()
            
            print(f"🗑️ Deleted story {story_id} and all related data")
            return True
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error deleting story: {str(e)}")
            return False


# Singleton instance
story_persistence_service = StoryPersistenceService()
