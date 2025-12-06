# ===== COMPLETE STORY ID ARRAY IMPLEMENTATION - STORAGE SERVICE =====
# Replace your entire storage_service.py with this enhanced version

import tempfile
import io
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Optional
from fastapi import HTTPException
import httpx
from firebase_admin import firestore
from src.common_function.firebase_init import get_storage_bucket, get_firestore_client
from src.common_function.s3_client import get_s3_client, get_s3_bucket_name
from src.config import settings
import secrets
from src.common_function.async_utils import get_or_create_event_loop
from src.share.schema import (
    ShareSettings,
    SharedStory,
    SharedStoryAccessLog,
    UserSharingStats,
    StorySharingStats
)

class StorageService:
    def __init__(self):
        self.bucket = None
        self.db = None
        self._init_clients()
    
    def _init_clients(self):
        """Initialize Firebase clients with error handling"""
        try:
            self.bucket = get_storage_bucket()
            self.db = get_firestore_client()
            
            if self.bucket:
                print(f"✅ Storage Service initialized with Firebase bucket: {self.bucket.name}")
            else:
                print("⚠️ Storage Service: No Firebase bucket available")
                
        except Exception as e:
            print(f"⚠️ Storage Service initialization error: {str(e)}")

    # ===== MEDIA UPLOAD METHODS (Keep existing) =====
    
    async def upload_audio(self, audio_data: bytes, story_id: str, scene_number: int) -> tuple[str, int]:
        """
        Upload audio to Firebase Storage with Opus OGG encoding and optimal caching
        
        Returns:
            Tuple of (public_url, duration_ms) where duration_ms is the actual audio duration
        """
        try:
            print(f"📤 Uploading audio to Firebase: story_id={story_id}, scene={scene_number} ({len(audio_data)} bytes)")
            
            # Extract actual audio duration before processing
            from src.common_function.helpers import get_audio_duration_from_file
            actual_duration = get_audio_duration_from_file(audio_data)
            
            # Process audio for web delivery (Opus OGG encoding)
            try:
                from src.common_function.audio_processor import AudioProcessor
                from src.common_function.opus_encoder import OpusEncoder
                
                # Convert to Opus OGG for optimal web delivery
                processed_audio, content_type, content_hash = AudioProcessor.process_for_web_delivery(
                    audio_data, source_format="auto"
                )
                
                # If we couldn't get duration from original, try from processed audio
                if actual_duration is None:
                    actual_duration = get_audio_duration_from_file(processed_audio)
                
                # Create versioned filename with content hash for cache busting
                base_filename = f"scene_{scene_number}"
                if content_type == "audio/opus":
                    versioned_filename = OpusEncoder.create_versioned_filename(base_filename, content_hash, "opus")
                    file_extension = "opus"
                else:
                    # Fallback to original format
                    file_extension = settings.audio_format
                    versioned_filename = f"{base_filename}-{content_hash}.{file_extension}"
                
                filename = f"stories/{story_id}/audio/{versioned_filename}"
                
                print(f"🎵 Audio processed: {content_type}, filename: {versioned_filename}")
                if actual_duration:
                    print(f"⏱️  Actual duration: {actual_duration}ms ({actual_duration/1000:.2f}s)")
                
            except Exception as e:
                print(f"⚠️ Audio processing failed, using original format: {str(e)}")
                # Fallback to original processing
                processed_audio = audio_data
                content_type = f"audio/{settings.audio_format}"
                import time, hashlib
                timestamp = int(time.time())
                content_hash = hashlib.sha256(audio_data).hexdigest()[:8]
                filename = f"stories/{story_id}/audio/scene_{scene_number}_{timestamp}.{settings.audio_format}"
            
            # Upload to Firebase Storage with optimized headers
            blob = self.bucket.blob(filename)
            
            # Run all blocking Firebase operations in executor with timeout
            loop = get_or_create_event_loop()
            
            def upload_with_metadata():
                """Upload file and set metadata synchronously"""
                blob.upload_from_string(
                    processed_audio, 
                    content_type=content_type
                )
                # Set cache control and other metadata for optimal delivery
                blob.cache_control = "public, max-age=31536000, immutable"  # 1 year cache
                blob.content_encoding = None  # Let browser handle compression
                blob.patch()
                blob.make_public()
            
            try:
                # Execute all Firebase operations with timeout (120s for upload + metadata)
                await asyncio.wait_for(
                    loop.run_in_executor(None, upload_with_metadata),
                    timeout=120.0  # Increased from 60s to 120s for large files and slow networks
                )
            except asyncio.TimeoutError:
                print(f"⚠️ Firebase audio upload timed out after 120s for scene {scene_number}")
                raise HTTPException(status_code=500, detail=f"Audio upload timeout for scene {scene_number}")
            
            # Use media endpoint for direct access (avoids metadata calls)
            public_url = f"{blob.public_url}?alt=media"
            
            size_bytes = len(processed_audio)
            dur_ms = actual_duration if actual_duration else 0
            print(f"✅ Audio uploaded: scene={scene_number} size={size_bytes}B duration={dur_ms}ms url={public_url}")
            
            return public_url, actual_duration
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Firebase audio upload failed for scene {scene_number}: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
    
    async def upload_user_voice_audio(self, audio_data: bytes, user_id: str) -> str:
        """Upload user's voice cloning audio to Firebase Storage with Opus optimization"""
        try:
            print(f"📤 Uploading user voice audio to Firebase: user_id={user_id} ({len(audio_data)} bytes)")
            
            # Process audio for web delivery (Opus OGG encoding)
            try:
                from src.common_function.audio_processor import AudioProcessor
                from src.common_function.opus_encoder import OpusEncoder
                
                # Convert to Opus OGG for optimal web delivery
                processed_audio, content_type, content_hash = AudioProcessor.process_for_web_delivery(
                    audio_data, source_format="auto"
                )
                
                # Create versioned filename with content hash
                base_filename = "voice_sample"
                if content_type == "audio/opus":
                    versioned_filename = OpusEncoder.create_versioned_filename(base_filename, content_hash, "opus")
                else:
                    # Fallback to original format
                    file_extension = settings.audio_format
                    versioned_filename = f"{base_filename}-{content_hash}.{file_extension}"
                
                filename = f"users/{user_id}/voice/{versioned_filename}"
                
                print(f"🎵 Voice audio processed: {content_type}, filename: {versioned_filename}")
                
            except Exception as e:
                print(f"⚠️ Voice audio processing failed, using original format: {str(e)}")
                # Fallback to original processing
                processed_audio = audio_data
                content_type = f"audio/{settings.audio_format}"
                import time
                timestamp = int(time.time())
                filename = f"users/{user_id}/voice/voice_sample_{timestamp}.{settings.audio_format}"
            
            # Upload to Firebase Storage
            blob = self.bucket.blob(filename)
            
            # Set optimal headers for web delivery and caching
            blob.upload_from_string(
                processed_audio, 
                content_type=content_type
            )
            
            # Set cache control for user voice (shorter cache due to potential updates)
            blob.cache_control = "public, max-age=2592000"  # 30 days cache for user voice
            blob.patch()  # Apply metadata changes
            
            # Make the blob public
            blob.make_public()
            
            # Use media endpoint for direct access
            public_url = f"{blob.public_url}?alt=media"
            
            print(f"✅ User voice audio uploaded: url={public_url}")
            
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"User voice audio upload failed: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
    
    async def upload_image_data(self, image_data: bytes, story_id: str, scene_number: int) -> str:
        """Upload grayscale image data directly to Firebase Storage (legacy method)"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading grayscale image data: {len(image_data)} bytes")
            
            # Validate image data
            if len(image_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Image data too small: {len(image_data)} bytes")
            
            # Always use JPEG format for all images
            content_type = "image/jpeg"
            file_extension = "jpg"
            # Using JPEG format (grayscale)
            
            # Use _grayscale suffix to indicate the image has been processed
            filename = f"stories/{story_id}/images/scene_{scene_number}_grayscale.{file_extension}"
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def upload_image_sync():
                blob = self.bucket.blob(filename)
                
                # Upload image data
                blob.upload_from_string(image_data, content_type=content_type)
                blob.make_public()
                
                # Verify upload
                if blob.exists():
                    return blob.public_url
                else:
                    raise Exception("Upload completed but file verification failed")
            
            # Run upload in thread pool
            public_url = await loop.run_in_executor(None, upload_image_sync)
            
            print(f"✅ Grayscale image uploaded: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Colored image upload failed for scene {scene_number}: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_colored_image(self, image_data: bytes, story_id: str, scene_number: int) -> str:
        """Upload colored image data directly to Firebase Storage"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading colored image data: {len(image_data)} bytes")
            
            # Validate image data
            if len(image_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Image data too small: {len(image_data)} bytes")
            
            # Always use JPEG format for all images
            content_type = "image/jpeg"
            file_extension = "jpg"
            # Using JPEG format (colored)
            
            # Use _colored suffix to indicate the original colored image
            filename = f"stories/{story_id}/images/scene_{scene_number}_colored.{file_extension}"
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            async def upload_image_with_timeout():
                def upload_image_sync():
                    blob = self.bucket.blob(filename)
                    
                    # Upload image data
                    blob.upload_from_string(image_data, content_type=content_type)
                    blob.make_public()
                    
                    # Verify upload
                    if blob.exists():
                        return blob.public_url
                    else:
                        raise Exception("Upload completed but file verification failed")
                
                # Run upload in thread pool with timeout (180s for large images)
                try:
                    public_url = await asyncio.wait_for(
                        loop.run_in_executor(None, upload_image_sync),
                        timeout=180.0  # Increased from 60s to 180s for 2048x2048 images
                    )
                    return public_url
                except asyncio.TimeoutError:
                    print(f"⚠️ Image upload timed out after 180s for scene {scene_number}")
                    raise Exception(f"Image upload timed out after 180 seconds")
            
            # Run upload with timeout
            public_url = await upload_image_with_timeout()
            
            print(f"✅ Colored image uploaded successfully: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Colored image upload failed for scene {scene_number}: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_story_thumbnail(self, thumbnail_data: bytes, story_id: str) -> str:
        """Upload story thumbnail image to Firebase Storage"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading story thumbnail: {len(thumbnail_data)} bytes")
            
            # Validate thumbnail data
            if len(thumbnail_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Thumbnail data too small: {len(thumbnail_data)} bytes")
            
            # Always use JPEG format for thumbnails
            content_type = "image/jpeg"
            file_extension = "jpg"
            print(f"🖼️ Storing thumbnail as JPEG format")
            
            # Create filename for thumbnail
            filename = f"stories/{story_id}/thumbnail.{file_extension}"
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            async def upload_thumbnail_with_timeout():
                def upload_thumbnail_sync():
                    blob = self.bucket.blob(filename)
                    
                    # Upload thumbnail data
                    blob.upload_from_string(thumbnail_data, content_type=content_type)
                    blob.make_public()
                    
                    # Verify upload
                    if blob.exists():
                        return blob.public_url
                    else:
                        raise Exception("Upload completed but file verification failed")
                
                # Run upload in thread pool with timeout (180s for thumbnails)
                try:
                    public_url = await asyncio.wait_for(
                        loop.run_in_executor(None, upload_thumbnail_sync),
                        timeout=180.0  # Increased from 60s to 180s
                    )
                    return public_url
                except asyncio.TimeoutError:
                    print(f"⚠️ Thumbnail upload timed out after 180s for story {story_id}")
                    raise Exception(f"Thumbnail upload timed out after 180 seconds")
            
            # Run upload with timeout
            public_url = await upload_thumbnail_with_timeout()
            
            print(f"✅ Story thumbnail uploaded successfully: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Thumbnail upload failed for story {story_id}: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_scene_image(self, image_data: bytes, story_id: str, scene_number: int) -> str:
        """Upload scene image (colored only, no grayscale)"""
        try:
            from PIL import Image
            import io
            
            # Validate image data using PIL
            image = Image.open(io.BytesIO(image_data))
            
            # Image dimensions are now dynamic based on request, verify reasonable size
            width, height = image.size
            if width < 100 or height < 100 or width > 5000 or height > 5000:
                print(f"⚠️ Unusual image size {image.size}, but proceeding...")
            else:
                print(f"✅ Image size: {image.size}")
            
            # Upload only colored image
            colored_url = await self.upload_colored_image(image_data, story_id, scene_number)
            
            return colored_url
            
        except Exception as e:
            error_msg = f"Scene image upload failed for scene {scene_number}: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_user_image(self, image_data: bytes, user_id: str) -> str:
        """Upload user profile image to Firebase Storage"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading user profile image: {len(image_data)} bytes")
            
            # Validate image data
            if len(image_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Image data too small: {len(image_data)} bytes")
            
            # Always use JPEG format for all images
            content_type = "image/jpeg"
            file_extension = "jpg"
            print(f"🖼️ Storing as JPEG format (user profile)")
            
            # Use timestamp to avoid conflicts
            from datetime import datetime
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"users/{user_id}/profile_image_{timestamp}.{file_extension}"
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def upload_image_sync():
                blob = self.bucket.blob(filename)
                
                # Upload image data
                blob.upload_from_string(image_data, content_type=content_type)
                blob.make_public()
                
                # Verify upload
                if blob.exists():
                    return blob.public_url
                else:
                    raise Exception("Upload completed but file verification failed")
            
            # Run upload in thread pool
            public_url = await loop.run_in_executor(None, upload_image_sync)
            
            print(f"✅ User profile image uploaded successfully: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"User profile image upload failed: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_image(self, image_data: bytes, filename: str, content_type: str = "image/jpeg") -> str:
        """Generic image upload method for temporary files"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading image: {filename} ({len(image_data)} bytes)")
            
            # Validate image data
            if len(image_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Image data too small: {len(image_data)} bytes")
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def upload_image_sync():
                blob = self.bucket.blob(filename)
                
                # Upload image data
                blob.upload_from_string(image_data, content_type=content_type)
                blob.make_public()
                
                # Verify upload
                if blob.exists():
                    return blob.public_url
                else:
                    raise Exception("Upload completed but file verification failed")
            
            # Run upload in thread pool
            public_url = await loop.run_in_executor(None, upload_image_sync)
            
            print(f"✅ Image uploaded successfully: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Image upload failed: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def upload_audio_file(self, audio_data: bytes, filename: str, content_type: str = "audio/wav") -> str:
        """Generic audio file upload method for temporary files"""
        try:
            if not self.bucket:
                raise HTTPException(status_code=503, detail="Firebase Storage not available")
            
            print(f"📤 Uploading audio file: {filename} ({len(audio_data)} bytes)")
            
            # Validate audio data
            if len(audio_data) < 1000:  # Less than 1KB is probably an error
                raise Exception(f"Audio data too small: {len(audio_data)} bytes")
            
            # Create blob and upload in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def upload_audio_sync():
                blob = self.bucket.blob(filename)
                
                # Upload audio data
                blob.upload_from_string(audio_data, content_type=content_type)
                blob.make_public()
                
                # Verify upload
                if blob.exists():
                    return blob.public_url
                else:
                    raise Exception("Upload completed but file verification failed")
            
            # Run upload in thread pool
            public_url = await loop.run_in_executor(None, upload_audio_sync)
            
            print(f"✅ Audio file uploaded successfully: {public_url}")
            return public_url
            
        except HTTPException:
            raise
        except Exception as e:
            error_msg = f"Audio file upload failed: {str(e)}"
            print(f"❌ {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)

    async def delete_file(self, filename: str) -> bool:
        """Delete a file from Firebase Storage"""
        try:
            if not self.bucket:
                print("⚠️ Firebase Storage not available - cannot delete file")
                return False
            
            print(f"🗑️ Deleting file: {filename}")
            
            # Run deletion in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def delete_file_sync():
                blob = self.bucket.blob(filename)
                if blob.exists():
                    blob.delete()
                    return True
                else:
                    print(f"⚠️ File {filename} does not exist")
                    return False
            
            # Run deletion in thread pool
            result = await loop.run_in_executor(None, delete_file_sync)
            
            if result:
                print(f"✅ File deleted successfully: {filename}")
            
            return result
            
        except Exception as e:
            print(f"❌ File deletion failed for {filename}: {str(e)}")
            return False

    # ===== ENHANCED STORY METADATA MANAGEMENT WITH STORY ID ARRAYS =====
    
    async def save_story_metadata(self, story_id: str, user_id: str, title: str, prompt: str, manifest: Dict, child_id: str = None, child_snapshot: Dict = None):
        """Save story metadata with story ID array tracking for each user and MinIO audio URLs.
        Now accepts optional child_id and child_snapshot (parent-centric model). If provided,
        the story document will include the child's ID and a snapshot of the child's profile
        at generation time to make stories immutable to later child profile edits.
        """
        try:
            if not self.db:
                print("⚠️ Firestore not available - skipping metadata save")
                return
            
            # Run Firestore operations in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def save_metadata_with_story_arrays():
                current_time = datetime.utcnow()
                
                # Process scenes to separate audio URLs and image URLs
                scenes_data = manifest.get('scenes', [])
                firebase_audio_urls = []
                
                for i, scene in enumerate(scenes_data):
                    if 'audio_url' in scene:
                        firebase_audio_urls.append({
                            'scene_number': i + 1,
                            'audio_url': scene['audio_url'],
                            'text': scene.get('text', ''),
                            'duration': scene.get('duration', 0)
                        })
                
                # 1. MAIN STORY DOCUMENT with Firebase audio URLs
                story_doc = {
                    'story_id': story_id,
                    'user_id': user_id,
                    'title': title,
                    'user_prompt': prompt,
                    'manifest': manifest,
                    # Parent-centric child data (optional)
                    'child_id': child_id,
                    'child_snapshot': child_snapshot,
                    'created_at': current_time,
                    'updated_at': current_time,
                    'status': manifest.get('status', 'completed'),
                    'total_scenes': manifest.get('total_scenes', 0),
                    'total_duration': manifest.get('total_duration', 0),
                    'generation_method': manifest.get('generation_method', 'optimized_parallel'),
                    'image_format': 'custom_dimensions_from_deepai',
                    'scenes_data': scenes_data,
                    'audio_urls': firebase_audio_urls,  # Firebase audio URLs for easy access
                    'audio_storage': 'minio',  # Indicate audio is stored in MinIO
                    'image_storage': 'firebase',  # Images still in Firebase
                    'optimizations': manifest.get('optimizations', []),
                    'ai_models_used': {
                        'text_generation': settings.llm_model,
                        'image_generation': 'gpt-image-1-mini',
                        'audio_generation': 'cartesia-sonic-3'
                    }
                }
                
                # Use the proper thumbnail URL if available
                if manifest.get('thumbnail_url'):
                    story_doc['thumbnail_url'] = manifest.get('thumbnail_url')
                else:
                    # Only fallback to first scene if no dedicated thumbnail
                    scenes = manifest.get('scenes', [])
                    if scenes and len(scenes) > 0:
                        story_doc['thumbnail_url'] = scenes[0].get('image_url')
                    else:
                        story_doc['thumbnail_url'] = None  # Leave empty if no valid thumbnail
                
                # Save to main stories collection
                doc_ref = self.db.collection('stories').document(story_id)
                doc_ref.set(story_doc)
                
                # 2. UPDATE USER DOCUMENT WITH STORY ID ARRAY
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                current_story_count = 0
                existing_story_ids = []
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    current_story_count = user_data.get('story_count', 0)
                    existing_story_ids = user_data.get('story_ids', [])
                
                # 🚫 FIX: Only add story_id if it's not already in the array
                if story_id not in existing_story_ids:
                    updated_story_ids = existing_story_ids + [story_id]
                    new_story_count = len(updated_story_ids)
                else:
                    updated_story_ids = existing_story_ids
                    new_story_count = len(updated_story_ids)
                    print(f"📝 Story {story_id} already exists in user's story_ids array")
                
                # Update story document with story number
                story_doc['story_number'] = new_story_count
                doc_ref.update({'story_number': new_story_count})
                
                # Enhanced user document update with story ID array
                user_update_data = {
                    'story_count': new_story_count,
                    'story_ids': updated_story_ids,  # CRITICAL: Array of all story IDs
                    'last_active': current_time,
                    'last_story_created': current_time,
                    'last_story_id': story_id,
                    'last_story_title': title,
                    # Enhanced statistics
                    'story_statistics': {
                        'total_stories': new_story_count,
                        'total_scenes_created': sum(story.get('total_scenes', 0) for story in [story_doc]),
                        'total_duration_seconds': sum(story.get('total_duration', 0) for story in [story_doc]) / 1000,
                        'last_generation_method': story_doc['generation_method'],
                        'creation_dates': existing_story_ids + [{'story_id': story_id, 'created_at': current_time}]
                    }
                }
                
                # Update main user document
                if user_doc.exists:
                    user_ref.update(user_update_data)
                else:
                    user_update_data.update({
                        'created_at': current_time,
                        'user_id': user_id
                    })
                    user_ref.set(user_update_data)
                
                print(f"📝 Updated user {user_id} story_ids array: {len(updated_story_ids)} stories")
                print(f"📝 Story IDs: {updated_story_ids}")
                print(f"📤 Saved {len(firebase_audio_urls)} Firebase audio URLs for story {story_id}")
                
                return True
            
            # Execute in thread pool
            await loop.run_in_executor(None, save_metadata_with_story_arrays)
            
            print(f"✅ Story metadata saved with Firebase audio URLs: {story_id} for user {user_id}")
            
        except Exception as e:
            print(f"⚠️ Failed to save story metadata with arrays: {str(e)}")

    async def get_user_stories_using_id_array(self, user_id: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """Get user stories using the story ID array - MAIN METHOD with timezone fix"""
        try:
            if not self.db:
                print("⚠️ Firestore not available")
                return {
                    "stories": [],
                    "total_count": 0,
                    "has_more": False,
                    "user_info": None,
                    "method_used": "firestore_unavailable"
                }
            
            # Run Firestore query in thread pool
            loop = get_or_create_event_loop()
            
            def get_stories_from_id_array():
                # 1. GET USER DOCUMENT WITH STORY ID ARRAY
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if not user_doc.exists:
                    return {
                        "stories": [],
                        "total_count": 0,
                        "has_more": False,
                        "user_info": None,
                        "method_used": "user_not_found"
                    }
                
                user_data = user_doc.to_dict()
                story_ids = user_data.get('story_ids', [])
                
                # Remove duplicates from story_ids
                story_ids = list(dict.fromkeys(story_ids))
                total_count = len(story_ids)
                
                print(f"📋 Found {total_count} unique story IDs for user {user_id}")
                print(f"📋 Story IDs: {story_ids}")
                
                if not story_ids:
                    user_info = self._extract_user_info(user_data)
                    return {
                        "stories": [],
                        "total_count": 0,
                        "has_more": False,
                        "user_info": user_info,
                        "method_used": "story_id_array_empty"
                    }
                
                # 2. APPLY PAGINATION TO STORY IDS (newest first)
                story_ids_reversed = list(reversed(story_ids))
                paginated_story_ids = story_ids_reversed[offset:offset + limit]
                
                print(f"📄 Paginated IDs (offset:{offset}, limit:{limit}): {paginated_story_ids}")
                
                # 3. BATCH FETCH STORY DOCUMENTS USING STORY IDS
                stories_data = []
                
                def safe_datetime_conversion(dt_value):
                    """Safely convert datetime values with timezone handling"""
                    if dt_value is None:
                        return None
                    
                    try:
                        # If it's already a datetime object
                        if isinstance(dt_value, datetime):
                            # If it's naive, make it timezone aware (UTC)
                            if dt_value.tzinfo is None:
                                return dt_value.replace(tzinfo=timezone.utc)
                            return dt_value
                        
                        # If it's a Firestore timestamp
                        if hasattr(dt_value, 'seconds'):
                            return datetime.fromtimestamp(dt_value.seconds, tz=timezone.utc)
                        
                        # If it's a string, try to parse it
                        if isinstance(dt_value, str):
                            try:
                                parsed_dt = datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
                                if parsed_dt.tzinfo is None:
                                    return parsed_dt.replace(tzinfo=timezone.utc)
                                return parsed_dt
                            except:
                                return datetime.now(timezone.utc)  # Fallback
                        
                        return datetime.now(timezone.utc)  # Final fallback
                    except Exception as e:
                        print(f"⚠️ Datetime conversion error: {e}")
                        return datetime.now(timezone.utc)
                
                # Fetch each story document
                for story_id in paginated_story_ids:
                    try:
                        print(f"📖 Fetching story document: {story_id}")
                        story_ref = self.db.collection('stories').document(story_id)
                        story_doc = story_ref.get()
                        
                        if story_doc.exists:
                            story_data = story_doc.to_dict()
                            print(f"✅ Found story: {story_data.get('title', 'Unknown')}")
                            
                            # Safe datetime conversion
                            created_at = safe_datetime_conversion(story_data.get('created_at'))
                            updated_at = safe_datetime_conversion(story_data.get('updated_at'))
                            
                            # Calculate days ago safely
                            days_ago = None
                            created_at_formatted = None
                            
                            try:
                                if created_at:
                                    now_utc = datetime.now(timezone.utc)
                                    days_ago = (now_utc - created_at).days
                                    created_at_formatted = created_at.strftime('%Y-%m-%d %H:%M:%S')
                            except Exception as e:
                                print(f"⚠️ Date calculation error: {e}")
                                days_ago = 0
                                created_at_formatted = "Unknown"
                            
                            # Extract manifest for easier access to nested fields
                            manifest = story_data.get('manifest', {})
                            
                            # Build story summary with safe datetime handling
                            story_summary = {
                                'story_id': story_doc.id,
                                'title': story_data.get('title', 'Untitled Story'),
                                'user_prompt': story_data.get('user_prompt', ''),
                                'created_at': created_at,
                                'updated_at': updated_at,
                                'total_scenes': story_data.get('total_scenes', 0),
                                'total_duration': story_data.get('total_duration', 0),
                                'status': story_data.get('status', 'unknown'),
                                'story_number': story_data.get('story_number', 0),
                                'thumbnail_url': story_data.get('thumbnail_url'),
                                'generation_method': story_data.get('generation_method', 'unknown'),
                                'ai_models_used': story_data.get('ai_models_used', {}),
                                'image_format': story_data.get('image_format', 'unknown'),
                                'optimizations': story_data.get('optimizations', []),
                                'scenes_data': story_data.get('scenes_data', []),
                                'manifest': manifest,
                                # Extract important fields from manifest to top level for easier client access
                                'child_name': manifest.get('child_name'),
                                'child_age': manifest.get('child_age'),
                                'morals': manifest.get('morals', []),
                                'story_length': manifest.get('story_length'),
                                'art_style': manifest.get('art_style'),
                                'dimensions': manifest.get('dimensions'),
                                'voice_metadata': manifest.get('voice_metadata'),  # NEW: Voice metadata at top level
                                # Formatted timestamps
                                'created_at_formatted': created_at_formatted,
                                'days_ago': days_ago,
                                # Position in user's story collection
                                'position_in_user_stories': story_ids.index(story_id) + 1 if story_id in story_ids else 0,
                                'total_user_stories': total_count
                            }
                            
                            stories_data.append(story_summary)
                            print(f"✅ Story {story_id} processed successfully")
                            
                        else:
                            print(f"⚠️ Story document not found: {story_id}")
                            
                    except Exception as story_error:
                        print(f"❌ Error fetching story {story_id}: {str(story_error)}")
                        continue
                
                # 4. BUILD USER INFO with safe datetime handling
                user_info = self._extract_user_info(user_data)
                
                # 5. BUILD PAGINATION INFO
                pagination_info = {
                    "current_page": (offset // limit) + 1,
                    "total_pages": (total_count + limit - 1) // limit,
                    "page_size": limit,
                    "offset": offset,
                    "returned_count": len(stories_data),
                    "total_count": total_count,
                    "has_more": (offset + limit) < total_count
                }
                
                print(f"✅ Successfully fetched {len(stories_data)} stories using ID array method")
                
                return {
                    "stories": stories_data,
                    "total_count": total_count,
                    "has_more": (offset + limit) < total_count,
                    "user_info": user_info,
                    "pagination": pagination_info,
                    "method_used": "story_id_array",
                    "performance_info": {
                        "total_story_ids": len(story_ids),
                        "fetched_stories": len(stories_data),
                        "pagination_applied": True,
                        "batch_fetched": True
                    }
                }
            
            # Execute in thread pool
            result = await loop.run_in_executor(None, get_stories_from_id_array)
            return result
            
        except Exception as e:
            print(f"❌ Error fetching user stories using ID array: {str(e)}")
            return {
                "stories": [],
                "total_count": 0,
                "has_more": False,
                "user_info": None,
                "error": str(e),
                "method_used": "error"
            }

    def _extract_user_info(self, user_data: Dict) -> Dict:
        """Extract user info from user document with timezone-aware datetime handling"""
        def safe_datetime(dt_value):
            """Safely handle datetime conversion with timezone awareness"""
            if dt_value is None:
                return None
            
            # If it's already a datetime object
            if isinstance(dt_value, datetime):
                # If it's naive (no timezone), make it UTC
                if dt_value.tzinfo is None:
                    return dt_value.replace(tzinfo=timezone.utc)
                return dt_value
            
            # If it's a string, try to parse it
            if isinstance(dt_value, str):
                try:
                    parsed_dt = datetime.fromisoformat(dt_value.replace('Z', '+00:00'))
                    if parsed_dt.tzinfo is None:
                        return parsed_dt.replace(tzinfo=timezone.utc)
                    return parsed_dt
                except:
                    return None
            
            # If it's a Firestore timestamp, convert it
            if hasattr(dt_value, 'seconds'):  # Firestore Timestamp
                return datetime.fromtimestamp(dt_value.seconds, tz=timezone.utc)
            
            return None

        return {
            'total_stories': user_data.get('story_count', 0),
            'story_ids_array_length': len(user_data.get('story_ids', [])),
            'last_active': safe_datetime(user_data.get('last_active')),
            'last_story_created': safe_datetime(user_data.get('last_story_created')),
            'last_story_id': user_data.get('last_story_id'),
            'last_story_title': user_data.get('last_story_title'),
            'child_name': user_data.get('child', {}).get('name', 'Your child'),
            'child_age': user_data.get('child', {}).get('age'),
            'child_interests': user_data.get('child', {}).get('interests', []),
            'story_statistics': user_data.get('story_statistics', {}),
            'created_at': safe_datetime(user_data.get('created_at')),
            'story_ids_preview': user_data.get('story_ids', [])[-5:] if user_data.get('story_ids') else []
        }

    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """
        Get user profile data from Firestore
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            User profile dictionary
            
        Raises:
            HTTPException: If user not found or error occurs
        """
        try:
            if not self.db:
                raise HTTPException(status_code=503, detail="Firestore not available")
            
            loop = get_or_create_event_loop()
            
            def get_user_sync():
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if user_doc.exists:
                    return user_doc.to_dict()
                else:
                    return None
            
            user_data = await loop.run_in_executor(None, get_user_sync)
            
            if user_data:
                return user_data
            else:
                raise HTTPException(status_code=404, detail="User not found")
                
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching user profile: {str(e)}")

    async def get_story_details(self, story_id: str, user_id: str = None) -> Dict[str, Any]:
        """Get complete story details with optional user verification"""
        try:
            if not self.db:
                raise HTTPException(status_code=503, detail="Firestore not available")
            
            # Run Firestore query in thread pool
            loop = get_or_create_event_loop()
            
            def get_story_sync():
                doc_ref = self.db.collection('stories').document(story_id)
                doc = doc_ref.get()
                
                if doc.exists:
                    story_data = doc.to_dict()
                    
                    # Optional: Verify user ownership using story_ids array
                    if user_id:
                        story_owner_id = story_data.get('user_id')
                        if story_owner_id != user_id:
                            return None  # User doesn't own this story
                        
                        # Double-check: Verify story ID is in user's story_ids array
                        user_ref = self.db.collection('users').document(user_id)
                        user_doc = user_ref.get()
                        
                        if user_doc.exists:
                            user_data = user_doc.to_dict()
                            story_ids = user_data.get('story_ids', [])
                            
                            if story_id not in story_ids:
                                print(f"⚠️ Story {story_id} not found in user {user_id}'s story_ids array")
                                return None
                    
                    return story_data
                else:
                    return None
            
            # Execute in thread pool
            story_data = await loop.run_in_executor(None, get_story_sync)
            
            if story_data:
                return story_data
            else:
                raise HTTPException(status_code=404, detail="Story not found or access denied")
                
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching story details: {str(e)}")

    async def delete_user_story(self, story_id: str, user_id: str) -> bool:
        """Delete a story and remove it from user's story_ids array"""
        try:
            if not self.db:
                raise HTTPException(status_code=503, detail="Firestore not available")
            
            loop = get_or_create_event_loop()
            
            def delete_story_with_array_update():
                # 1. Verify the story belongs to the user and get current arrays
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if not user_doc.exists:
                    return False
                
                user_data = user_doc.to_dict()
                story_ids = user_data.get('story_ids', [])
                
                if story_id not in story_ids:
                    print(f"⚠️ Story {story_id} not found in user {user_id}'s story_ids array")
                    return False
                
                # 2. Verify story document exists and belongs to user
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                
                if not story_doc.exists:
                    return False
                
                story_data = story_doc.to_dict()
                if story_data.get('user_id') != user_id:
                    return False
                
                # 3. Delete from main stories collection
                story_ref.delete()
                
                # 4. Remove story ID from user's story_ids array
                updated_story_ids = [sid for sid in story_ids if sid != story_id]
                
                # 5. Update user document
                user_ref.update({
                    'story_ids': updated_story_ids,
                    'story_count': len(updated_story_ids),
                    'updated_at': datetime.utcnow()
                })
                
                print(f"✅ Removed story {story_id} from user {user_id}'s story_ids array")
                print(f"📋 Updated story_ids: {updated_story_ids}")
                
                return True
            
            result = await loop.run_in_executor(None, delete_story_with_array_update)
            return result
            
        except Exception as e:
            print(f"❌ Error deleting story with array update: {str(e)}")
            return False

    # ===== STORY SHARING METHODS =====

    async def enable_story_sharing(self, story_id: str, user_id: str, settings: ShareSettings, expires_at: datetime = None) -> Tuple[str, str]:
        """Enable sharing for a story, creating a shareable link."""
        try:
            loop = get_or_create_event_loop()

            def _enable_sharing():
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()

                if not story_doc.exists or story_doc.to_dict().get('user_id') != user_id:
                    raise HTTPException(status_code=403, detail="User does not own this story.")

                share_token = secrets.token_urlsafe(16)
                now = datetime.utcnow()

                # Create document in shared_stories
                shared_story_data = SharedStory(
                    share_id=share_token,
                    story_id=story_id,
                    owner_id=user_id,
                    share_token=share_token,
                    created_at=now,
                    expires_at=expires_at,
                    settings=settings
                ).dict()
                self.db.collection('shared_stories').document(share_token).set(shared_story_data)

                # Update original story document
                story_ref.update({
                    'privacy': 'shareable',
                    'sharing.is_shareable': True,
                    'sharing.share_token': share_token,
                    'sharing.created_at': now,
                    'sharing.expires_at': expires_at
                })

                # Update user stats
                user_ref = self.db.collection('users').document(user_id)
                user_ref.update({
                    'sharing_stats.stories_shared_by_me': firestore.Increment(1)
                })
                
                # Use app_base_url from global config (not ShareSettings)
                from src.core.config import settings as config_settings
                # Share URL uses simple format: storymagic://share/{story_id}
                # Frontend expects this format for deep linking
                share_url = f"{config_settings.app_base_url}/{story_id}"
                qr_code_url = f"{config_settings.app_base_url}/stories/share/qr/{share_token}"
                return share_url, qr_code_url

            share_url, qr_code_url = await loop.run_in_executor(None, _enable_sharing)
            return share_url, qr_code_url

        except Exception as e:
            print(f"❌ Error enabling story sharing: {e}")
            raise HTTPException(status_code=500, detail=f"Could not enable sharing: {e}")

    async def disable_story_sharing(self, story_id: str, user_id: str) -> bool:
        """Disable sharing for a story."""
        try:
            loop = get_or_create_event_loop()

            def _disable_sharing():
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                story_data = story_doc.to_dict()

                if not story_doc.exists or story_data.get('user_id') != user_id:
                    raise HTTPException(status_code=403, detail="User does not own this story.")

                share_token = story_data.get('sharing', {}).get('share_token')
                if not share_token:
                    return True # Already disabled

                # Disable in shared_stories
                self.db.collection('shared_stories').document(share_token).update({
                    'is_active': False,
                    'disabled_at': datetime.utcnow()
                })

                # Update original story
                story_ref.update({
                    'privacy': 'private',
                    'sharing.is_shareable': False,
                    'sharing.disabled_at': datetime.utcnow()
                })
                
                # Update user stats
                user_ref = self.db.collection('users').document(user_id)
                user_ref.update({
                    'sharing_stats.stories_shared_by_me': firestore.Increment(-1)
                })
                return True

            return await loop.run_in_executor(None, _disable_sharing)
        except Exception as e:
            print(f"❌ Error disabling story sharing: {e}")
            return False

    async def get_shared_story(self, share_token: str, accessing_user_id: str = None) -> Dict[str, Any]:
        """Get a shared story's data using a share token."""
        try:
            loop = get_or_create_event_loop()

            def _get_shared():
                shared_story_ref = self.db.collection('shared_stories').document(share_token)
                shared_story_doc = shared_story_ref.get()

                if not shared_story_doc.exists:
                    raise HTTPException(status_code=404, detail="Shared story not found.")

                shared_story_data = shared_story_doc.to_dict()

                if not shared_story_data.get('is_active'):
                    raise HTTPException(status_code=403, detail="This share link has been disabled.")

                # Log access
                log_entry = SharedStoryAccessLog(user_id=accessing_user_id or "anonymous", action="viewed").dict()
                shared_story_ref.update({
                    'access_log': firestore.ArrayUnion([log_entry]),
                    'stats.total_views': firestore.Increment(1)
                })

                story_ref = self.db.collection('stories').document(shared_story_data['story_id'])
                story_doc = story_ref.get()
                if not story_doc.exists:
                    raise HTTPException(status_code=404, detail="Original story not found.")
                
                story_ref.update({
                    'analytics.views': firestore.Increment(1),
                    'analytics.last_viewed': datetime.utcnow()
                })

                return story_doc.to_dict()

            return await loop.run_in_executor(None, _get_shared)
        except Exception as e:
            print(f"❌ Error getting shared story: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def copy_shared_story(self, share_token: str, user_id: str) -> str:
        """Creates a copy of a shared story for the logged-in user."""
        try:
            loop = get_or_create_event_loop()

            def _copy_story():
                shared_story_ref = self.db.collection('shared_stories').document(share_token)
                shared_story_doc = shared_story_ref.get()
                if not shared_story_doc.exists or not shared_story_doc.to_dict().get('is_active'):
                    raise HTTPException(status_code=404, detail="Share link is not valid.")

                shared_data = shared_story_doc.to_dict()
                if not shared_data.get('settings', {}).get('allow_copy', True):
                    raise HTTPException(status_code=403, detail="Copying is disabled for this story.")

                original_story_ref = self.db.collection('stories').document(shared_data['story_id'])
                original_story_doc = original_story_ref.get()
                if not original_story_doc.exists:
                    raise HTTPException(status_code=404, detail="Original story not found.")

                original_story_data = original_story_doc.to_dict()
                
                new_story_id = self.db.collection('stories').document().id
                new_story_data = original_story_data.copy()
                
                now = datetime.utcnow()
                new_story_data.update({
                    'story_id': new_story_id,
                    'user_id': user_id,
                    'created_at': now,
                    'updated_at': now,
                    'privacy': 'private',
                    'sharing': {}, # Reset sharing info
                    'analytics': {}, # Reset analytics
                    'original_story_id': shared_data['story_id'],
                    'source_user_id': shared_data['owner_id'],
                    'copied_at': now,
                    'copied_from_share': True
                })

                # Save the new story
                self.db.collection('stories').document(new_story_id).set(new_story_data)

                # Update user's collections
                user_ref = self.db.collection('users').document(user_id)
                user_ref.update({
                    'story_ids': firestore.ArrayUnion([new_story_id]),
                    'copied_story_ids': firestore.ArrayUnion([new_story_id]),
                    'story_count': firestore.Increment(1),
                    'sharing_stats.stories_copied': firestore.Increment(1),
                    'sharing_stats.last_copy_date': now
                })

                # Log the copy action
                log_entry = SharedStoryAccessLog(user_id=user_id, action="copied", new_story_id=new_story_id).dict()
                shared_story_ref.update({
                    'access_log': firestore.ArrayUnion([log_entry]),
                    'stats.total_copies': firestore.Increment(1)
                })
                original_story_ref.update({
                    'analytics.copies_made': firestore.Increment(1)
                })

                return new_story_id

            return await loop.run_in_executor(None, _copy_story)
        except Exception as e:
            print(f"❌ Error copying story: {e}")
            raise HTTPException(status_code=500, detail=f"Could not copy story: {e}")

    async def accept_shared_story(self, share_token: str, receiving_user_id: str) -> Dict[str, Any]:
        """
        Accept a shared story - adds it to the receiving user's shared_stories_received array.
        The story is NOT copied; instead, the story_id is added to their account so they can access it.
        """
        try:
            loop = get_or_create_event_loop()

            def _accept_story():
                # Get the shared story record
                shared_story_ref = self.db.collection('shared_stories').document(share_token)
                shared_story_doc = shared_story_ref.get()
                
                if not shared_story_doc.exists:
                    raise HTTPException(status_code=404, detail="Share link not found.")
                
                shared_data = shared_story_doc.to_dict()
                
                # Check if share is active
                if not shared_data.get('is_active', False):
                    raise HTTPException(status_code=410, detail="This share link has been disabled.")
                
                # Check if expired
                expires_at = shared_data.get('expires_at')
                if expires_at and expires_at < datetime.utcnow():
                    raise HTTPException(status_code=410, detail="This share link has expired.")
                
                story_id = shared_data['story_id']
                owner_id = shared_data['owner_id']
                
                # Check if user is trying to share with themselves
                if receiving_user_id == owner_id:
                    raise HTTPException(status_code=400, detail="You cannot share a story with yourself.")
                
                # Check if story still exists
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                if not story_doc.exists:
                    raise HTTPException(status_code=404, detail="Original story no longer exists.")
                
                now = datetime.utcnow()
                
                # Add to receiving user's shared_stories_received array
                user_ref = self.db.collection('users').document(receiving_user_id)
                user_doc = user_ref.get()
                
                if not user_doc.exists:
                    raise HTTPException(status_code=404, detail="User not found.")
                
                user_data = user_doc.to_dict()
                shared_received = user_data.get('shared_stories_received', [])
                
                # Check if already received
                already_received = any(s.get('story_id') == story_id for s in shared_received)
                if already_received:
                    # Already in their library, just return success
                    return {
                        "story_id": story_id,
                        "shared_by": {
                            "user_id": owner_id
                        },
                        "received_at": now,
                        "already_had": True
                    }
                
                # Add share record to user's array
                share_record = {
                    "story_id": story_id,
                    "share_token": share_token,
                    "shared_by_user_id": owner_id,
                    "received_at": now
                }
                
                user_ref.update({
                    'shared_stories_received': firestore.ArrayUnion([share_record]),
                    'sharing_stats.stories_received': firestore.Increment(1),
                    'sharing_stats.last_received_date': now
                })
                
                # Track in shared_stories document
                shared_story_ref.update({
                    'stats.total_views': firestore.Increment(1),
                    'access_log': firestore.ArrayUnion([{
                        'user_id': receiving_user_id,
                        'timestamp': now,
                        'action': 'received'
                    }])
                })
                
                # Get sharer's info
                owner_ref = self.db.collection('users').document(owner_id)
                owner_doc = owner_ref.get()
                owner_data = owner_doc.to_dict() if owner_doc.exists else {}
                
                return {
                    "story_id": story_id,
                    "shared_by": {
                        "user_id": owner_id,
                        "name": owner_data.get('name', 'Unknown'),
                        "email": owner_data.get('email')
                    },
                    "received_at": now,
                    "already_had": False
                }

            return await loop.run_in_executor(None, _accept_story)
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Error accepting shared story: {e}")
            raise HTTPException(status_code=500, detail=f"Could not accept story: {str(e)}")

    async def get_received_shared_stories(self, user_id: str, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """
        Get all stories that have been shared with this user.
        Returns full story details for each shared story.
        """
        try:
            loop = get_or_create_event_loop()

            def _get_received_stories():
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if not user_doc.exists:
                    raise HTTPException(status_code=404, detail="User not found.")
                
                user_data = user_doc.to_dict()
                shared_received = user_data.get('shared_stories_received', [])
                
                total_count = len(shared_received)
                
                # Sort by received_at descending (newest first)
                shared_received.sort(key=lambda x: x.get('received_at', datetime.min), reverse=True)
                
                # Paginate
                paginated_shares = shared_received[offset:offset + limit]
                
                # Fetch full story details for each
                stories = []
                for share_record in paginated_shares:
                    story_id = share_record.get('story_id')
                    story_ref = self.db.collection('stories').document(story_id)
                    story_doc = story_ref.get()
                    
                    if story_doc.exists:
                        story_data = story_doc.to_dict()
                        
                        # Get sharer info
                        sharer_id = share_record.get('shared_by_user_id')
                        sharer_ref = self.db.collection('users').document(sharer_id)
                        sharer_doc = sharer_ref.get()
                        sharer_data = sharer_doc.to_dict() if sharer_doc.exists else {}
                        
                        stories.append({
                            "story": story_data,
                            "share_info": {
                                "received_at": share_record.get('received_at'),
                                "shared_by": {
                                    "user_id": sharer_id,
                                    "name": sharer_data.get('name', 'Unknown'),
                                    "email": sharer_data.get('email')
                                }
                            }
                        })
                
                return {
                    "stories": stories,
                    "total_count": total_count
                }

            return await loop.run_in_executor(None, _get_received_stories)
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Error fetching received stories: {e}")
            raise HTTPException(status_code=500, detail=f"Could not fetch received stories: {str(e)}")

    async def track_story_share_reception(self, story_id: str, receiving_user_id: str) -> Dict[str, Any]:
        """
        Track when a user accesses a shared story.
        Adds the story to user's shared_stories_received array.
        
        Args:
            story_id: ID of the story being accessed
            receiving_user_id: ID of user accessing the story
            
        Returns:
            Dict with already_had flag and sharer info
        """
        try:
            loop = get_or_create_event_loop()
            
            def _track_reception():
                # Get story info
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                if not story_doc.exists:
                    raise HTTPException(status_code=404, detail="Story not found")
                
                story_data = story_doc.to_dict()
                owner_id = story_data.get('user_id')
                
                # Get receiving user
                user_ref = self.db.collection('users').document(receiving_user_id)
                user_doc = user_ref.get()
                if not user_doc.exists:
                    raise HTTPException(status_code=404, detail="User not found")
                
                user_data = user_doc.to_dict()
                shared_stories = user_data.get('shared_stories_received', [])
                
                # Check if already received
                already_had = any(s.get('story_id') == story_id for s in shared_stories)
                
                if not already_had:
                    # Add to user's received stories
                    share_record = {
                        'story_id': story_id,
                        'shared_by_user_id': owner_id,
                        'received_at': firestore.SERVER_TIMESTAMP
                    }
                    
                    user_ref.update({
                        'shared_stories_received': firestore.ArrayUnion([share_record]),
                        'sharing_stats.stories_received': firestore.Increment(1),
                        'sharing_stats.last_received_date': firestore.SERVER_TIMESTAMP
                    })
                
                # Get sharer info
                sharer_ref = self.db.collection('users').document(owner_id)
                sharer_doc = sharer_ref.get()
                sharer_data = sharer_doc.to_dict() if sharer_doc.exists else {}
                
                return {
                    "already_had": already_had,
                    "shared_by": {
                        "user_id": owner_id,
                        "name": sharer_data.get('name', 'Unknown'),
                        "email": sharer_data.get('email')
                    }
                }
            
            return await loop.run_in_executor(None, _track_reception)
        except HTTPException:
            raise
        except Exception as e:
            print(f"❌ Error tracking story reception: {e}")
            raise HTTPException(status_code=500, detail=f"Could not track story reception: {str(e)}")

    async def get_story_analytics(self, story_id: str, user_id: str) -> Dict[str, Any]:
        """Get analytics for a specific shared story."""
        try:
            loop = get_or_create_event_loop()

            def _get_analytics():
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                if not story_doc.exists or story_doc.to_dict().get('user_id') != user_id:
                    raise HTTPException(status_code=404, detail="Story not found or access denied.")

                story_data = story_doc.to_dict()
                sharing_data = story_data.get('sharing', {})
                analytics_data = story_data.get('analytics', {})
                
                share_token = sharing_data.get('share_token')
                access_log = []
                if share_token:
                    shared_story_doc = self.db.collection('shared_stories').document(share_token).get()
                    if shared_story_doc.exists:
                        access_log = shared_story_doc.to_dict().get('access_log', [])

                return {
                    "story_id": story_id,
                    "title": story_data.get("title"),
                    "is_shareable": sharing_data.get("is_shareable", False),
                    "views": analytics_data.get("views", 0),
                    "copies_made": analytics_data.get("copies_made", 0),
                    "last_viewed": analytics_data.get("last_viewed"),
                    "access_log": access_log[-20:] # Return last 20 access events
                }

            return await loop.run_in_executor(None, _get_analytics)
        except Exception as e:
            print(f"❌ Error getting story analytics: {e}")
            raise HTTPException(status_code=500, detail="Could not retrieve story analytics.")

    async def get_sharing_dashboard(self, user_id: str) -> Dict[str, Any]:
        """Get a dashboard summary of the user's sharing activity."""
        try:
            loop = get_or_create_event_loop()

            def _get_dashboard():
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                if not user_doc.exists:
                    raise HTTPException(status_code=404, detail="User not found.")
                
                user_data = user_doc.to_dict()
                sharing_stats = user_data.get('sharing_stats', {})

                # Find top 5 most viewed stories
                stories_query = self.db.collection('stories').where('user_id', '==', user_id).where('sharing.is_shareable', '==', True).order_by('analytics.views', direction=firestore.Query.DESCENDING).limit(5)
                top_stories_docs = stories_query.stream()
                
                top_stories = []
                for doc in top_stories_docs:
                    story = doc.to_dict()
                    top_stories.append({
                        "story_id": doc.id,
                        "title": story.get("title"),
                        "views": story.get("analytics", {}).get("views", 0),
                        "copies_made": story.get("analytics", {}).get("copies_made", 0)
                    })

                return {
                    "user_id": user_id,
                    "stats": sharing_stats,
                    "top_shared_stories": top_stories
                }

            return await loop.run_in_executor(None, _get_dashboard)
        except Exception as e:
            print(f"❌ Error getting sharing dashboard: {e}")
            raise HTTPException(status_code=500, detail="Could not retrieve sharing dashboard.")

    async def batch_update_sharing(self, story_ids: List[str], user_id: str, enable: bool) -> Dict[str, int]:
        """Batch enable or disable sharing for a list of stories."""
        try:
            tasks = []
            for story_id in story_ids:
                if enable:
                    # For enabling, we might need settings, so we'll just call the single method.
                    # A more advanced implementation could take default settings.
                    tasks.append(self.enable_story_sharing(story_id, user_id, ShareSettings()))
                else:
                    tasks.append(self.disable_story_sharing(story_id, user_id))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if not isinstance(r, Exception) and r)
            failure_count = len(results) - success_count
            
            return {"success": success_count, "failed": failure_count}

        except Exception as e:
            print(f"❌ Error in batch update sharing: {e}")
            raise HTTPException(status_code=500, detail="Batch operation failed.")

    async def renew_share_link(self, story_id: str, user_id: str, new_expires_at: datetime = None) -> bool:
        """Update the expiration date of a share link."""
        try:
            loop = get_or_create_event_loop()

            def _renew():
                story_ref = self.db.collection('stories').document(story_id)
                story_doc = story_ref.get()
                story_data = story_doc.to_dict()

                if not story_doc.exists or story_data.get('user_id') != user_id:
                    raise HTTPException(status_code=403, detail="User does not own this story.")

                share_token = story_data.get('sharing', {}).get('share_token')
                if not share_token:
                    raise HTTPException(status_code=400, detail="Story is not currently shared.")

                # Update shared_stories collection
                self.db.collection('shared_stories').document(share_token).update({
                    'expires_at': new_expires_at
                })

                # Update original story document
                story_ref.update({
                    'sharing.expires_at': new_expires_at
                })
                return True

            return await loop.run_in_executor(None, _renew)
        except Exception as e:
            print(f"❌ Error renewing share link: {e}")
            return False

    # ===== UTILITY METHODS =====
    async def get_user_story_ids(self, user_id: str) -> List[str]:
        """Get just the story IDs array for a user"""
        try:
            if not self.db:
                return []
            
            loop = get_or_create_event_loop()
            
            def get_ids():
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    return user_data.get('story_ids', [])
                return []
            
            result = await loop.run_in_executor(None, get_ids)
            return result
            
        except Exception as e:
            print(f"❌ Error getting user story IDs: {str(e)}")
            return []

    async def update_story_status_and_title(self, story_id: str, status: str, title: str = None):
        """Update story status and optionally title"""
        try:
            if not self.db:
                print("⚠️ Firestore not available - skipping status update")
                return
            
            # Run update in thread pool
            loop = get_or_create_event_loop()
            
            def update_status_sync():
                doc_ref = self.db.collection('stories').document(story_id)
                update_data = {
                    'status': status,
                    'updated_at': datetime.utcnow()
                }
                
                if title:
                    update_data['title'] = title
                    
                doc_ref.update(update_data)
            
            await loop.run_in_executor(None, update_status_sync)
            print(f"✅ Story {story_id} status updated to: {status}")
            
        except Exception as e:
            print(f"⚠️ Failed to update story status: {str(e)}")

    async def update_story_status(self, story_id: str, status: str, error_message: Optional[str] = None):
        """Update story playback status and optionally record error message"""
        try:
            if not self.db:
                print("⚠️ Firestore not available - skipping status update")
                return
            
            # Run update in thread pool
            loop = get_or_create_event_loop()
            
            def update_status_sync():
                doc_ref = self.db.collection('stories').document(story_id)
                update_data = {
                    'playback_status': status,
                    'last_played': datetime.utcnow()
                }
                if error_message:
                    update_data['error_message'] = error_message
                    update_data['failed_at'] = datetime.utcnow()
                doc_ref.update(update_data)
            
            await loop.run_in_executor(None, update_status_sync)
            
        except Exception as e:
            print(f"⚠️ Failed to update story status: {str(e)}")

    async def update_story_manifest(self, story_id: str, updated_manifest: Dict):
        """Update story manifest in Firestore"""
        try:
            if not self.db:
                print("⚠️ Firestore not available - skipping manifest update")
                return False
            
            # Run update in thread pool
            loop = get_or_create_event_loop()
            
            def update_manifest_sync():
                doc_ref = self.db.collection('stories').document(story_id)
                
                # Update the story document with new manifest
                update_data = {
                    'manifest': updated_manifest,
                    'updated_at': datetime.utcnow(),
                    'audio_format': updated_manifest.get('audio_format', 'unknown'),
                    'esp32_compatible': updated_manifest.get('esp32_compatible', False)
                }
                
                # Update top-level fields from manifest for easy querying
                if 'title' in updated_manifest:
                    update_data['title'] = updated_manifest['title']
                if 'total_scenes' in updated_manifest:
                    update_data['total_scenes'] = updated_manifest['total_scenes']
                if 'total_duration' in updated_manifest:
                    update_data['total_duration'] = updated_manifest['total_duration']
                
                doc_ref.update(update_data)
                print(f"✅ Updated story manifest for {story_id}")
                return True
            
            result = await loop.run_in_executor(None, update_manifest_sync)
            return result
            
        except Exception as e:
            print(f"❌ Failed to update story manifest: {str(e)}")
            return False

    def test_storage_access(self):
        """Test Firebase Storage access"""
        firebase_result = None
        
        # Test Firebase Storage
        try:
            if not self.bucket:
                firebase_result = (False, "No Firebase storage bucket available")
            else:
                test_blob = self.bucket.blob("test/connection_test.txt")
                test_blob.upload_from_string("test", content_type="text/plain")
                
                if test_blob.exists():
                    test_blob.delete()
                    firebase_result = (True, f"Firebase Storage access successful: {self.bucket.name}")
                else:
                    firebase_result = (False, "Firebase upload test failed")
                    
        except Exception as e:
            firebase_result = (False, f"Firebase Storage test failed: {str(e)}")
        
        return {
            "firebase": firebase_result,
            "status": "success" if firebase_result[0] else "error"
        }
    
    async def add_story_to_user_collection(self, user_id: str, story_id: str):
        """Add a story ID to user's story_ids array (for demo endpoint)"""
        try:
            if not self.db:
                print("⚠️ Firestore not available - skipping story addition")
                return False
            
            # Run Firestore operations in thread pool to avoid blocking
            loop = get_or_create_event_loop()
            
            def add_story_to_array():
                current_time = datetime.utcnow()
                
                # Get user document
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                existing_story_ids = []
                current_story_count = 0
                
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    existing_story_ids = user_data.get('story_ids', [])
                    current_story_count = user_data.get('story_count', 0)
                
                # Only add story_id if it's not already in the array
                if story_id not in existing_story_ids:
                    updated_story_ids = existing_story_ids + [story_id]
                    new_story_count = len(updated_story_ids)
                    
                    # Update user document
                    user_update_data = {
                        'story_count': new_story_count,
                        'story_ids': updated_story_ids,
                        'last_active': current_time,
                        'last_demo_story_added': current_time,
                        'last_story_id': story_id
                    }
                    
                    user_ref.update(user_update_data)
                    print(f"📝 Added story {story_id} to user {user_id} collection")
                    return True
                else:
                    print(f"📝 Story {story_id} already exists in user {user_id} collection")
                    return True
            
            result = await loop.run_in_executor(None, add_story_to_array)
            return result
            
        except Exception as e:
            print(f"❌ Error adding story to user collection: {e}")
            return False

    async def delete_user_story(self, user_id: str, story_id: str) -> bool:
        """Delete a story from user's collection and remove from Firestore"""
        try:
            if not self.db:
                raise HTTPException(status_code=503, detail="Firestore not available")
            
            loop = get_or_create_event_loop()
            
            def delete_story_sync():
                try:
                    # 1. Get current user document
                    user_ref = self.db.collection('users').document(user_id)
                    user_doc = user_ref.get()
                    
                    if not user_doc.exists:
                        print(f"⚠️ User document not found: {user_id}")
                        return False
                    
                    user_data = user_doc.to_dict()
                    story_ids = user_data.get('story_ids', [])
                    
                    # 2. Check if story exists in user's collection
                    if story_id not in story_ids:
                        print(f"⚠️ Story {story_id} not found in user {user_id}'s collection")
                        return False
                    
                    # 3. Remove story from user's story_ids array
                    updated_story_ids = [sid for sid in story_ids if sid != story_id]
                    new_story_count = len(updated_story_ids)
                    
                    # 4. Update user document
                    user_update_data = {
                        'story_count': new_story_count,
                        'story_ids': updated_story_ids,
                        'last_active': firestore.SERVER_TIMESTAMP
                    }
                    
                    user_ref.update(user_update_data)
                    print(f"🗑️ Removed story {story_id} from user {user_id}'s collection")
                    
                    # 5. Delete the story document from stories collection
                    story_ref = self.db.collection('stories').document(story_id)
                    story_doc = story_ref.get()
                    
                    if story_doc.exists:
                        # TODO: In the future, could also delete associated media files from Firebase Storage
                        # For now, just delete the Firestore document
                        story_ref.delete()
                        print(f"🗑️ Deleted story document {story_id} from Firestore")
                    else:
                        print(f"⚠️ Story document {story_id} not found in Firestore")
                    
                    return True
                    
                except Exception as e:
                    print(f"❌ Error in delete_story_sync: {e}")
                    return False
            
            result = await loop.run_in_executor(None, delete_story_sync)
            return result
            
        except Exception as e:
            print(f"❌ Error deleting story: {e}")
            return False

    async def get_user_stories_filtered(self, user_id: str, filter_type: str, limit: int, offset: int) -> Dict[str, Any]:
        """Get user stories with filtering for owned, shared, and copied stories."""
        if filter_type == "owned":
            return await self.get_user_stories_using_id_array(user_id, limit, offset)
        elif filter_type == "shared":
            return await self._get_stories_by_id_array_type(user_id, "shared_story_ids", limit, offset)
        elif filter_type == "copied":
            return await self._get_stories_by_id_array_type(user_id, "copied_story_ids", limit, offset)
        elif filter_type == "all":
            # For 'all', we can combine owned and copied for now.
            # A more complex union might be needed for true 'all' across different collections.
            return await self.get_user_stories_using_id_array(user_id, limit, offset) # Fallback to owned for now
        else:
            raise HTTPException(status_code=400, detail="Invalid filter type specified.")

    async def get_user_stories(self, user_id: str, limit: int = 20, offset: int = 0, child_id: Optional[str] = None) -> Dict[str, Any]:
        """Simple story listing with optional child_id filter used by children router.

        This is a lightweight implementation independent of the story_id array logic.
        """
        try:
            if not self.db:
                return {"stories": [], "total_count": 0, "has_more": False}

            loop = get_or_create_event_loop()

            def _query():
                # Base query: stories for user
                collection = self.db.collection('stories').where('user_id', '==', user_id)
                if child_id:
                    collection = collection.where('child_id', '==', child_id)
                docs = list(collection.stream())
                total = len(docs)
                # Sort by created_at descending if available
                def _sort_key(d):
                    data = d.to_dict() or {}
                    return data.get('created_at') or datetime.min
                docs.sort(key=_sort_key, reverse=True)
                paginated = docs[offset:offset+limit]
                stories = []
                for doc in paginated:
                    data = doc.to_dict() or {}
                    # Minimal shape expected by child stories endpoint
                    stories.append({
                        'story_id': data.get('story_id', doc.id),
                        'title': data.get('title'),
                        'status': data.get('status'),
                        'total_scenes': data.get('total_scenes'),
                        'total_duration': data.get('total_duration'),
                        'child_id': data.get('child_id'),
                        'created_at': data.get('created_at'),
                        'thumbnail_url': data.get('thumbnail_url'),
                    })
                return {
                    'stories': stories,
                    'total_count': total,
                    'has_more': (offset + limit) < total
                }

            result = await loop.run_in_executor(None, _query)
            return result
        except Exception as e:
            print(f"❌ Error in get_user_stories(child_id filter): {e}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stories: {e}")

    async def _get_stories_by_id_array_type(self, user_id: str, id_array_field: str, limit: int, offset: int) -> Dict[str, Any]:
        """Internal helper to get stories based on a specific ID array field in the user document."""
        try:
            if not self.db:
                raise HTTPException(status_code=503, detail="Firestore not available")

            loop = get_or_create_event_loop()

            def _get_stories():
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                if not user_doc.exists:
                    return {"stories": [], "total_count": 0, "has_more": False, "user_info": None}

                user_data = user_doc.to_dict()
                story_ids = user_data.get(id_array_field, [])
                total_count = len(story_ids)

                if not story_ids:
                    return {"stories": [], "total_count": 0, "has_more": False, "user_info": self._extract_user_info(user_data)}

                # Paginate IDs
                paginated_ids = list(reversed(story_ids))[offset:offset + limit]

                # Batch fetch stories
                story_refs = [self.db.collection('stories').document(sid) for sid in paginated_ids]
                story_docs = self.db.get_all(story_refs)

                stories_data = [doc.to_dict() for doc in story_docs if doc.exists]
                
                # This part is simplified. A full implementation would re-use the story formatting from get_user_stories_using_id_array
                
                return {
                    "stories": stories_data,
                    "total_count": total_count,
                    "has_more": (offset + limit) < total_count,
                    "user_info": self._extract_user_info(user_data),
                    "method_used": f"filtered_{id_array_field}"
                }

            return await loop.run_in_executor(None, _get_stories)

        except Exception as e:
            print(f"❌ Error fetching stories with filter '{id_array_field}': {e}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch stories: {e}")