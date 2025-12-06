import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import HTTPException
from src.config import settings
from src.common_function.s3_client import get_s3_client, get_s3_bucket_name
from src.common_function.storage_service import StorageService
from src.common_function.async_utils import get_or_create_event_loop

class S3StorageService(StorageService):
    def __init__(self):
        super().__init__()  # Initialize Firestore and Firebase bucket (if needed for legacy)
        self.s3_client = get_s3_client()
        # Use june_story bucket for all story-related storage
        self.s3_bucket_name = get_s3_bucket_name() or "june_story"
        
        if self.s3_client and self.s3_bucket_name:
            print(f"✅ S3 Storage Service initialized with bucket: {self.s3_bucket_name}")
        else:
            print("⚠️ S3 Storage Service: S3 not configured properly")

    async def upload_file_to_s3(self, file_data: bytes, key: str, content_type: str, cache_control: str = None, acl: str = None) -> str:
        """Upload file to S3 and return public URL
        
        Note: acl parameter is deprecated and ignored. Use bucket policies for public access instead.
        """
        if not self.s3_client or not self.s3_bucket_name:
            raise HTTPException(status_code=503, detail="S3 Storage not available")

        loop = get_or_create_event_loop()

        def upload_sync():
            try:
                # Don't use ACL - bucket must have public access via bucket policy
                extra_args = {'ContentType': content_type}
                if cache_control:
                    extra_args['CacheControl'] = cache_control

                self.s3_client.put_object(
                    Bucket=self.s3_bucket_name,
                    Key=key,
                    Body=file_data,
                    **extra_args
                )
                
                # Construct public URL
                url = f"https://{self.s3_bucket_name}.s3.{settings.aws.region}.amazonaws.com/{key}"
                return url
            except Exception as e:
                print(f"❌ S3 upload failed: {e}")
                raise Exception(f"S3 upload failed: {str(e)}")

        return await loop.run_in_executor(None, upload_sync)

    async def upload_audio(self, audio_data: bytes, story_id: str, scene_number: int) -> tuple[str, int]:
        """Upload audio to S3"""
        try:
            print(f"📤 Uploading audio to S3: story_id={story_id}, scene={scene_number} ({len(audio_data)} bytes)")
            
            # Extract duration
            from src.common_function.helpers import get_audio_duration_from_file
            actual_duration = get_audio_duration_from_file(audio_data)
            
            # Process audio
            try:
                from src.common_function.audio_processor import AudioProcessor
                from src.common_function.opus_encoder import OpusEncoder
                
                processed_audio, content_type, content_hash = AudioProcessor.process_for_web_delivery(
                    audio_data, source_format="auto"
                )
                
                if actual_duration is None:
                    actual_duration = get_audio_duration_from_file(processed_audio)
                
                base_filename = f"scene_{scene_number}"
                if content_type == "audio/opus":
                    versioned_filename = OpusEncoder.create_versioned_filename(base_filename, content_hash, "opus")
                    file_extension = "opus"
                else:
                    file_extension = settings.audio_format
                    versioned_filename = f"{base_filename}-{content_hash}.{file_extension}"
                
                filename = f"stories/{story_id}/audio/{versioned_filename}"
                
            except Exception as e:
                print(f"⚠️ Audio processing failed, using original format: {str(e)}")
                processed_audio = audio_data
                content_type = f"audio/{settings.audio_format}"
                import time
                timestamp = int(time.time())
                filename = f"stories/{story_id}/audio/scene_{scene_number}_{timestamp}.{settings.audio_format}"

            public_url = await self.upload_file_to_s3(
                processed_audio, 
                filename, 
                content_type,
                cache_control="public, max-age=31536000, immutable"
            )
            
            print(f"✅ Audio uploaded to S3: {public_url}")
            return public_url, actual_duration or 0
            
        except Exception as e:
            print(f"❌ S3 audio upload failed: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def upload_image(self, image_data: bytes, filename: str, content_type: str = "image/jpeg") -> str:
        """Generic image upload to S3"""
        return await self.upload_file_to_s3(image_data, filename, content_type)

    async def upload_colored_image(self, image_data: bytes, story_id: str, scene_number: int) -> str:
        filename = f"stories/{story_id}/images/scene_{scene_number}_colored.jpg"
        return await self.upload_file_to_s3(image_data, filename, "image/jpeg")

    async def upload_story_thumbnail(self, thumbnail_data: bytes, story_id: str) -> str:
        filename = f"stories/{story_id}/thumbnail.jpg"
        return await self.upload_file_to_s3(thumbnail_data, filename, "image/jpeg")

    async def upload_user_image(self, image_data: bytes, user_id: str) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"users/{user_id}/profile_image_{timestamp}.jpg"
        return await self.upload_file_to_s3(image_data, filename, "image/jpeg")

    async def upload_user_voice_audio(self, audio_data: bytes, user_id: str) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"users/{user_id}/voice/voice_sample_{timestamp}.wav"
        return await self.upload_file_to_s3(audio_data, filename, "audio/wav")

    async def delete_file(self, filename: str) -> bool:
        """Delete a file from S3"""
        try:
            if not self.s3_client or not self.s3_bucket_name:
                print("⚠️ S3 Storage not available - cannot delete file")
                return False
            
            print(f"🗑️ Deleting file from S3: {filename}")
            
            loop = get_or_create_event_loop()
            
            def delete_sync():
                self.s3_client.delete_object(Bucket=self.s3_bucket_name, Key=filename)
                return True
            
            return await loop.run_in_executor(None, delete_sync)
            
        except Exception as e:
            print(f"❌ S3 file deletion failed for {filename}: {str(e)}")
            return False

    async def update_story_status(self, story_id, status: str, error_message: Optional[str] = None):
        """Update story status - accepts both int and str story_id"""
        try:
            # Convert story_id to string for Firestore
            story_id_str = str(story_id)
            
            if not self.db:
                print("⚠️ Firestore not available - skipping status update")
                return
            
            # Run update in thread pool
            loop = get_or_create_event_loop()
            
            def update_status_sync():
                doc_ref = self.db.collection('stories').document(story_id_str)
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

    async def save_story_metadata(self, story_id: str, user_id: str, title: str, prompt: str, manifest: Dict, child_id: str = None, child_snapshot: Dict = None):
        """Save story metadata with story ID array tracking and S3 storage info."""
        try:
            # Convert story_id to string for Firestore compatibility
            story_id_str = str(story_id)
            
            if not self.db:
                print("⚠️ Firestore not available - skipping metadata save")
                return
            
            loop = get_or_create_event_loop()
            
            def save_metadata_with_story_arrays():
                current_time = datetime.utcnow()
                
                scenes_data = manifest.get('scenes', [])
                audio_urls = []
                
                for i, scene in enumerate(scenes_data):
                    if 'audio_url' in scene:
                        audio_urls.append({
                            'scene_number': i + 1,
                            'audio_url': scene['audio_url'],
                            'text': scene.get('text', ''),
                            'duration': scene.get('duration', 0)
                        })
                
                story_doc = {
                    'story_id': story_id_str,  # Use string version
                    'user_id': user_id,
                    'title': title,
                    'user_prompt': prompt,
                    'manifest': manifest,
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
                    'audio_urls': audio_urls,
                    'audio_storage': 's3',  # Updated to s3
                    'image_storage': 's3',  # Updated to s3
                    'optimizations': manifest.get('optimizations', []),
                    'ai_models_used': {
                        'text_generation': settings.llm_model,
                        'image_generation': 'gpt-image-1-mini',
                        'audio_generation': 'cartesia-sonic-3'
                    }
                }
                
                if manifest.get('thumbnail_url'):
                    story_doc['thumbnail_url'] = manifest.get('thumbnail_url')
                else:
                    scenes = manifest.get('scenes', [])
                    if scenes and len(scenes) > 0:
                        story_doc['thumbnail_url'] = scenes[0].get('image_url')
                    else:
                        story_doc['thumbnail_url'] = None
                
                doc_ref = self.db.collection('stories').document(story_id_str)
                doc_ref.set(story_doc)
                
                user_ref = self.db.collection('users').document(user_id)
                user_doc = user_ref.get()
                
                existing_story_ids = []
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    existing_story_ids = user_data.get('story_ids', [])
                    # Ensure all IDs in the list are strings
                    existing_story_ids = [str(sid) for sid in existing_story_ids]
                
                if story_id_str not in existing_story_ids:
                    updated_story_ids = existing_story_ids + [story_id_str]
                    new_story_count = len(updated_story_ids)
                else:
                    updated_story_ids = existing_story_ids
                    new_story_count = len(updated_story_ids)
                
                story_doc['story_number'] = new_story_count
                doc_ref.update({'story_number': new_story_count})
                
                user_update_data = {
                    'story_count': new_story_count,
                    'story_ids': updated_story_ids,  # Now all strings
                    'last_active': current_time,
                    'last_story_created': current_time,
                    'last_story_id': story_id_str,  # Use string version
                    'last_story_title': title,
                    'story_statistics': {
                        'total_stories': new_story_count,
                        'total_scenes_created': sum(story.get('total_scenes', 0) for story in [story_doc]),
                        'total_duration_seconds': sum(story.get('total_duration', 0) for story in [story_doc]) / 1000,
                        'last_generation_method': story_doc['generation_method'],
                        'creation_dates': existing_story_ids + [{'story_id': story_id, 'created_at': current_time}]
                    }
                }
                
                if user_doc.exists:
                    user_ref.update(user_update_data)
                else:
                    user_update_data.update({
                        'created_at': current_time,
                        'user_id': user_id
                    })
                    user_ref.set(user_update_data)
                
                print(f"📝 Updated user {user_id} story_ids array: {len(updated_story_ids)} stories")
                return True
            
            await loop.run_in_executor(None, save_metadata_with_story_arrays)
            print(f"✅ Story metadata saved with S3 URLs: {story_id} for user {user_id}")
            
        except Exception as e:
            print(f"⚠️ Failed to save story metadata with arrays: {str(e)}")
