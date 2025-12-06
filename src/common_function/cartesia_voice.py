"""
Cartesia Voice Cloning and TTS Service
======================================
Handles voice cloning, TTS generation, and voice management for users using Cartesia AI.
This is the primary TTS service for all voice cloning and text-to-speech operations.
"""

import aiohttp
import asyncio
import json
import base64
import uuid
import tempfile
import os
from typing import Optional, Dict, Any, List
from fastapi import HTTPException
from src.core.config import settings
from src.common_function.firebase_init import get_firestore_client, is_firebase_available
from google.cloud import firestore
from src.common_function.audio_processor import AudioProcessor
from datetime import datetime


class CartesiaService:
    def __init__(self):
        self.api_key = getattr(settings, 'cartesia_api_key', None)
        self.base_url = "https://api.cartesia.ai"
        self.api_version = "2024-06-10"  # Cartesia API version
        self.default_voice_id = "79a125e8-cd45-4c13-8a67-188112f4dd22"  # Cartesia default British Lady voice
        self._db = None
        
        # Cartesia model IDs - Using sonic-3-2025-10-27 (latest and best model)
        self.model_id = "sonic-3-2025-10-27"  # Latest Cartesia model with best quality
        self.multilingual_model_id = "sonic-3-2025-10-27"  # sonic-3 supports all languages
        
        if not self.api_key:
            print("⚠️ Cartesia API key not found. Please set CARTESIA_API_KEY in environment.")
        else:
            print("✅ Cartesia Service initialized")
    
    @property
    def db(self):
        """Lazy initialization of Firestore client"""
        if self._db is None:
            self._db = get_firestore_client()
        return self._db
    
    @property
    def headers(self):
        """Get headers for Cartesia API requests"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Cartesia-Version": self.api_version,
            "Content-Type": "application/json"
        }
    
    async def clone_voice_from_audio(
        self, 
        audio_data: bytes, 
        user_id: str, 
        voice_name: str,
        description: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        remove_background_noise: bool = True,
        language: str = "en",
        base_voice_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Clone a voice from audio data using Cartesia and save the voice ID to Firebase
        
        Args:
            audio_data: Raw audio bytes (supports various formats)
            user_id: User ID for whom to clone the voice
            voice_name: Name for the cloned voice
            description: Optional description for the voice clone
            labels: Optional labels dict (kept for compatibility, mapped to description)
            remove_background_noise: Enhance audio quality (default: True)
            language: Language code (default: "en")
            base_voice_id: Optional base voice to use as template
            
        Returns:
            voice_id: Cartesia voice ID if successful, None otherwise
        """
        try:
            if not self.api_key:
                print("❌ Cartesia API key not available")
                return None
            
            print(f"🎤 Starting voice cloning with Cartesia for user {user_id}")
            print(f"📊 Audio input: {len(audio_data)} bytes")
            
            # Validate audio size
            if len(audio_data) < 1000:  # Less than 1KB
                print("❌ Audio data too small for voice cloning (minimum ~1KB required)")
                return None
            elif len(audio_data) > 25 * 1024 * 1024:  # More than 25MB
                print("❌ Audio data too large for voice cloning (maximum 25MB)")
                return None
            
            # Detect audio format from the audio data
            audio_format, content_type = self._detect_audio_format(audio_data)
            print(f"📊 Detected audio format: {audio_format} ({content_type})")
            
            # Handle raw PCM data if needed
            if audio_format == "pcm_raw":
                print("🔧 Converting raw PCM data to WAV format for Cartesia compatibility...")
                audio_data = self._convert_pcm_to_wav(audio_data)
                audio_format = "wav"
                content_type = "audio/wav"
                print(f"✅ Converted to WAV: {len(audio_data)} bytes")
            
            # Create temporary file for upload
            with tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False) as temp_file:
                temp_file.write(audio_data)
                temp_file_path = temp_file.name
            
            try:
                # Prepare the voice cloning request using multipart form-data
                url = f"{self.base_url}/voices/clone"
                
                async with aiohttp.ClientSession() as session:
                    # Create multipart form data
                    data = aiohttp.FormData()
                    data.add_field('name', voice_name)
                    
                    # Add description
                    if description:
                        data.add_field('description', description)
                    else:
                        data.add_field('description', f'High-quality cloned voice for user {user_id}')
                    
                    # Add language
                    data.add_field('language', language)
                    
                    # Add enhancement flag
                    data.add_field('enhance', 'true' if remove_background_noise else 'false')
                    print(f"🔇 Audio enhancement: {'enabled' if remove_background_noise else 'disabled'}")
                    
                    # Add base voice if provided
                    if base_voice_id:
                        data.add_field('base_voice_id', base_voice_id)
                        print(f"🎭 Using base voice: {base_voice_id}")
                    
                    # Add the audio file
                    with open(temp_file_path, 'rb') as audio_file:
                        filename = f'voice_sample.{audio_format}'
                        data.add_field('clip', audio_file, filename=filename, content_type=content_type)
                        
                        # Make the request
                        headers = {
                            "Authorization": f"Bearer {self.api_key}",
                            "Cartesia-Version": self.api_version
                        }
                        
                        async with session.post(url, data=data, headers=headers) as response:
                            response_text = await response.text()
                            
                            print(f"🔍 Cartesia API Response Status: {response.status}")
                            print(f"🔍 Cartesia API Response: {response_text[:500]}...")
                            
                            if response.status == 200 or response.status == 201:
                                voice_data = json.loads(response_text)
                                voice_id = voice_data.get("id")  # Cartesia returns "id" not "voice_id"
                                
                                print(f"✅ Voice cloned successfully with Cartesia! Voice ID: {voice_id}")
                                
                                # Save voice metadata to Firebase
                                await self.save_user_voice_metadata(user_id, voice_id, voice_name)
                                
                                return voice_id
                            else:
                                error_msg = f"Cartesia API error {response.status}: {response_text}"
                                print(f"❌ Voice cloning failed: {error_msg}")
                                raise Exception(error_msg)
                
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    
        except Exception as e:
            print(f"❌ Voice cloning error: {str(e)}")
            raise e
    
    def _detect_audio_format(self, audio_data: bytes) -> tuple[str, str]:
        """
        Detect audio format from file header/magic bytes
        
        Args:
            audio_data: Raw audio bytes
            
        Returns:
            tuple: (file_extension, content_type)
        """
        if len(audio_data) < 16:
            print(f"⚠️ Audio data too short ({len(audio_data)} bytes), defaulting to WAV")
            return "wav", "audio/wav"
        
        header = audio_data[:16]
        
        # WAV format detection
        if header.startswith(b'RIFF') and header[8:12] == b'WAVE':
            return "wav", "audio/wav"
        
        # FLAC format detection
        if header.startswith(b'fLaC'):
            return "flac", "audio/flac"
        
        # MP3 format detection
        if header.startswith(b'ID3') or (header[0:2] in [b'\xff\xfb', b'\xff\xfa', b'\xff\xf3', b'\xff\xf2']):
            return "mp3", "audio/mpeg"
        
        # M4A/AAC format detection
        if header[4:8] == b'ftyp':
            return "m4a", "audio/mp4"
        
        # OGG format detection
        if header.startswith(b'OggS'):
            return "ogg", "audio/ogg"
        
        # Check if this could be raw PCM data
        if self._is_likely_raw_pcm(audio_data):
            return "pcm_raw", "audio/pcm"
        
        # Default to WAV
        print(f"⚠️ Unknown audio format. Header: {header.hex()[:32]}. Defaulting to WAV")
        return "wav", "audio/wav"
    
    def _is_likely_raw_pcm(self, audio_data: bytes) -> bool:
        """Check if audio data is likely raw PCM"""
        try:
            if len(audio_data) < 100:
                return False
            
            import struct
            
            # Try 16-bit interpretation
            if len(audio_data) % 2 == 0:
                sample_size = min(200, len(audio_data) // 2)
                samples = struct.unpack('<' + 'h' * sample_size, audio_data[:sample_size * 2])
                
                # Check for reasonable audio characteristics
                min_val = min(samples)
                max_val = max(samples)
                unique_values = len(set(samples[:100]))
                
                if min_val >= -32768 and max_val <= 32767 and unique_values >= 3:
                    range_used = max_val - min_val
                    if range_used > 65535 * 0.001:  # At least 0.1% of range used
                        return True
            
            return False
            
        except Exception:
            return False
    
    def _convert_pcm_to_wav(self, audio_data: bytes) -> bytes:
        """Convert raw PCM data to WAV format"""
        # Assume 16kHz, mono, 16-bit for voice
        sample_rate = 16000
        channels = 1
        sample_width = 2
        
        return AudioProcessor.create_esp32_compatible_wav(
            pcm_data=audio_data,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            volume_gain=1.0
        )
    
    async def save_user_voice_metadata(self, user_id: str, voice_id: str, voice_name: str):
        """Save voice metadata to Firebase"""
        try:
            if not is_firebase_available() or self.db is None:
                print("⚠️ Firebase not available, cannot save voice metadata")
                return
            
            voice_metadata = {
                'voice_id': voice_id,
                'voice_name': voice_name,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'clone_status': 'active',
                'provider': 'cartesia'
            }
            
            # Update user document with voice metadata
            user_ref = self.db.collection('users').document(user_id)
            user_ref.update({
                'voice_clone': voice_metadata,
                'updated_at': datetime.utcnow()
            })
            
            print(f"✅ Voice metadata saved for user {user_id}")
            
        except Exception as e:
            print(f"❌ Failed to save voice metadata: {str(e)}")
    
    async def get_user_voice_id(self, user_id: str, use_cloned_voice: bool = True, voice_clone_id: str = None) -> str:
        """
        Get user's active cloned voice ID or return default voice
        
        Args:
            user_id: User ID
            use_cloned_voice: Whether to use cloned voice if available
            voice_clone_id: Specific voice clone ID to use (overrides auto-detection)
            
        Returns:
            voice_id: Cartesia voice ID (specified, active cloned voice, or default)
        """
        try:
            # If specific voice_clone_id is provided, try to resolve it
            if voice_clone_id:
                print(f"🎤 Using provided voice clone ID for user {user_id}: {voice_clone_id}")

                # If the caller passed a local clone id (e.g. 'vc_...'), resolve to provider voice_id stored in Firestore
                try:
                    if isinstance(voice_clone_id, str) and voice_clone_id.startswith('vc_') and is_firebase_available() and self.db:
                        clone_ref = self.db.collection('users').document(user_id).collection('voice_clones').document(voice_clone_id)
                        clone_doc = clone_ref.get()
                        if clone_doc and clone_doc.exists:
                            clone_data = clone_doc.to_dict()
                            provider_voice_id = clone_data.get('voice_id')
                            if provider_voice_id:
                                print(f"🎤 Resolved local voice_clone_id {voice_clone_id} -> provider voice_id {provider_voice_id}")
                                return provider_voice_id
                            else:
                                print(f"⚠️ Voice clone document {voice_clone_id} missing provider voice_id")
                except Exception as e:
                    print(f"⚠️ Could not resolve voice_clone_id {voice_clone_id}: {e}")

                # Fallback: return the provided id (if it isn't a local id or resolution failed)
                return voice_clone_id
            
            if not use_cloned_voice:
                print(f"🎤 Cloned voice disabled, using default voice for user {user_id}")
                return self.default_voice_id
            
            if not is_firebase_available() or self.db is None:
                print("⚠️ Firebase not available, using default voice")
                return self.default_voice_id
            
            # Get active voice clone from voice_clones subcollection
            active_voice_clone_id = await self.get_active_voice_clone_id(user_id)
            
            if active_voice_clone_id:
                voice_clone_ref = self.db.collection('users').document(user_id).collection('voice_clones').document(active_voice_clone_id)
                voice_clone_doc = voice_clone_ref.get()
                
                if voice_clone_doc.exists:
                    voice_clone_data = voice_clone_doc.to_dict()
                    provider = voice_clone_data.get('provider')
                    cartesia_voice_id = voice_clone_data.get('voice_id')
                    
                    # Only use voice_id if it's from Cartesia provider
                    if cartesia_voice_id:
                        if provider == 'cartesia':
                            print(f"🎤 Using active Cartesia cloned voice for user {user_id}: {cartesia_voice_id}")
                            return cartesia_voice_id
                        else:
                            print(f"⚠️ Active voice clone is not Cartesia (provider: {provider}), using default voice")
                            print(f"   Legacy voice_id: {cartesia_voice_id} (ElevenLabs/Other)")
            
            print(f"🎤 No active Cartesia voice clone found for user {user_id}, using default voice")
            return self.default_voice_id
            
        except Exception as e:
            print(f"❌ Error getting user voice: {str(e)}")
            return self.default_voice_id
    
    async def generate_speech_cartesia(
        self,
        text: str,
        voice_id: str = None,
        scene_number: int = None,
        language: str = "en",
        speed: str = "normal",
        emotion: str = "neutral",
        volume_gain: float = 3.0,
        max_retries: int = 3,
    ) -> bytes:
        """
        Generate speech using Cartesia TTS with retry logic
        
        Args:
            text: Text to convert to speech
            voice_id: Cartesia voice ID (uses default if not provided)
            scene_number: Scene number for logging
            language: Language code (e.g., "en", "es", "fr")
            speed: Speech speed: "slowest", "slow", "normal", "fast", "fastest"
            emotion: Emotion: "neutral", "happy", "sad", "angry", "surprised"
            volume_gain: Volume multiplier (default 3.0, clamped to 0.5-2.0)
            max_retries: Maximum number of retry attempts (default 3)
            
        Returns:
            audio_data: Generated audio as bytes
        """
        last_error = None
        
        for attempt in range(max_retries):
            try:
                if not self.api_key:
                    raise Exception("Cartesia API key not available")
                
                # Use provided voice or default
                if not voice_id:
                    voice_id = self.default_voice_id
                
                if attempt > 0:
                    wait_time = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
                    print(f"🔄 Retry attempt {attempt + 1}/{max_retries} for scene {scene_number or 'preview'} (waiting {wait_time}s)")
                    await asyncio.sleep(wait_time)
                
                print(f"🎤 Generating speech with Cartesia (voice: {voice_id}, language: {language})")
                if scene_number:
                    print(f"   Scene: {scene_number}")
                
                url = f"{self.base_url}/tts/bytes"
                
                # Use sonic-3 for all languages (it supports multilingual)
                model_id = self.model_id
                
                print(f"🎯 Using Cartesia model: {model_id} (emotion: {emotion}, speed: {speed}, volume: {volume_gain})")
                
                # Clamp volume to safe range [0.5, 2.0] - use 2.0 max for loudest audio
                try:
                    vol = float(volume_gain)
                except Exception:
                    vol = 2.0  # Default to maximum safe volume
                vol = max(0.5, min(2.0, vol))  # 3.0 will be clamped to 2.0 (max safe)

                # Prepare payload according to Cartesia API v2024-06-10
                payload = {
                    "model_id": model_id,
                    "transcript": text,
                    "voice": {
                        "mode": "id",
                        "id": voice_id
                    },
                    "language": language,
                    "generation_config": {
                        "volume": vol,
                        "emotion": emotion
                    },
                    "output_format": {
                        "container": "mp3",
                        "encoding": "mp3",
                        "sample_rate": 44100
                    },
                    "speed": speed,  # Speed parameter at top level (not in generation_config)
                    "save": False
                }
                
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Cartesia-Version": self.api_version,
                    "Content-Type": "application/json"
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers) as response:
                        if response.status == 200:
                            audio_data = await response.read()
                            print(f"✅ Cartesia TTS generated {len(audio_data)} bytes (attempt {attempt + 1})")
                            return audio_data
                        else:
                            error_text = await response.text()
                            print(f"❌ Cartesia TTS failed: {response.status} - {error_text}")
                            raise Exception(f"Cartesia TTS failed: {response.status}")
                            
            except Exception as e:
                last_error = e
                print(f"❌ Cartesia TTS error on attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries - 1:
                    print(f"❌ All {max_retries} retry attempts failed")
                    raise
        
        # Should never reach here, but just in case
        raise last_error if last_error else Exception("Unknown error in Cartesia TTS")
    
    async def generate_voice_preview(
        self,
        voice_id: str,
        preview_text: str = "Hello! This is a preview of my voice.",
        volume_gain: float = 3.0,
    ) -> bytes:
        """
        Generate a voice preview audio sample
        
        Args:
            voice_id: Cartesia voice ID
            preview_text: Text to use for preview (default: sample text)
            
        Returns:
            audio_data: Generated preview audio as bytes (MP3 format)
        """
        try:
            print(f"🎙️ Generating voice preview for voice {voice_id}")
            
            # Use the generate_speech_cartesia method with default settings
            audio_data = await self.generate_speech_cartesia(
                text=preview_text,
                voice_id=voice_id,
                language="en",
                speed="normal",
                emotion="neutral",
                volume_gain=volume_gain,
            )
            
            print(f"✅ Voice preview generated: {len(audio_data)} bytes")
            return audio_data
            
        except Exception as e:
            print(f"❌ Failed to generate voice preview: {str(e)}")
            raise
    
    async def generate_speech_batch_cartesia(
        self, 
        scenes: List[Dict], 
        user_id: str, 
        use_cloned_voice: bool = True, 
        language: str = "en",
        voice_clone_id: str = None
    ) -> List[bytes]:
        """
        Generate speech for multiple scenes using Cartesia TTS
        
        Args:
            scenes: List of scene dictionaries with 'text' field
            user_id: User ID to get cloned voice
            use_cloned_voice: Whether to use cloned voice if available
            language: Language code
            voice_clone_id: Optional specific voice clone ID to use (overrides auto-detection)
            
        Returns:
            List of audio data as bytes
        """
        try:
            # Get user's voice ID
            voice_id = await self.get_user_voice_id(user_id, use_cloned_voice, voice_clone_id)
            
            print(f"🎵 Cartesia batch TTS for {len(scenes)} scenes in {language}")
            print(f"🎤 Using voice: {voice_id}")
            
            # Process with concurrency limit
            semaphore = asyncio.Semaphore(5)
            
            async def rate_limited_generation(scene, scene_num):
                async with semaphore:
                    text = scene.get('text', str(scene)) if isinstance(scene, dict) else str(scene)
                    emotion = scene.get('emotion', 'neutral') if isinstance(scene, dict) else 'neutral'
                    
                    # Retry logic
                    for attempt in range(3):
                        try:
                            result = await self.generate_speech_cartesia(
                                text, 
                                voice_id, 
                                scene_num, 
                                language,
                                emotion=emotion
                            )
                            if attempt > 0:
                                print(f"✅ Scene {scene_num} succeeded on retry {attempt} (emotion: {emotion})")
                            return result
                        except Exception as e:
                            if attempt < 2:
                                wait_time = (attempt + 1) * 2
                                print(f"⚠️ Scene {scene_num} failed (attempt {attempt + 1}), retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                            else:
                                print(f"❌ Scene {scene_num} failed after 3 attempts: {str(e)}")
                                raise e
            
            tasks = [rate_limited_generation(scene, i + 1) for i, scene in enumerate(scenes)]
            audio_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            audio_files = []
            for i, result in enumerate(audio_results):
                if isinstance(result, Exception):
                    print(f"❌ Scene {i + 1} audio generation failed: {str(result)}")
                    audio_files.append(None)
                else:
                    audio_files.append(result)
            
            successful_audio = [audio for audio in audio_files if audio is not None]
            if not successful_audio:
                raise Exception("Cartesia TTS failed: All scenes failed")
            
            print(f"✅ Cartesia batch TTS completed: {len(successful_audio)} audio files")
            return audio_files
            
        except Exception as e:
            print(f"❌ Cartesia batch TTS error: {str(e)}")
            raise Exception(f"Cartesia TTS failed: {str(e)}")
    
    async def delete_cloned_voice(self, voice_id: str, user_id: str = None):
        """
        Delete a cloned voice from Cartesia
        
        Args:
            voice_id: Cartesia voice ID to delete
            user_id: User ID to update Firebase metadata
        """
        try:
            if not self.api_key:
                print("❌ Cartesia API key not available")
                return False
            
            url = f"{self.base_url}/voices/{voice_id}"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Cartesia-Version": self.api_version
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    if response.status == 200 or response.status == 204:
                        print(f"✅ Voice {voice_id} deleted from Cartesia")
                        
                        # Update Firebase metadata
                        if user_id and is_firebase_available() and self.db:
                            try:
                                user_ref = self.db.collection('users').document(user_id)
                                user_ref.update({
                                    'voice_clone': None,
                                    'updated_at': datetime.utcnow()
                                })
                                print(f"✅ Voice metadata removed from Firebase for user {user_id}")
                            except Exception as e:
                                print(f"⚠️ Failed to update Firebase: {str(e)}")
                        
                        return True
                    else:
                        error_text = await response.text()
                        print(f"❌ Failed to delete voice: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"❌ Voice deletion error: {str(e)}")
            return False
    
    async def update_voice_metadata(
        self,
        voice_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        gender: Optional[str] = None
    ) -> bool:
        """
        Update voice metadata in Cartesia
        
        Args:
            voice_id: Voice ID to update
            name: Optional new name
            description: Optional new description
            gender: Optional gender ("masculine", "feminine", "nonbinary")
        """
        try:
            if not self.api_key:
                return False
            
            url = f"{self.base_url}/voices/{voice_id}"
            
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if gender:
                payload["gender"] = gender
            
            if not payload:
                return True  # Nothing to update
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Cartesia-Version": self.api_version,
                "Content-Type": "application/json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=headers) as response:
                    if response.status == 200:
                        print(f"✅ Voice metadata updated for {voice_id}")
                        return True
                    else:
                        error_text = await response.text()
                        print(f"❌ Failed to update voice: {response.status} - {error_text}")
                        return False
                        
        except Exception as e:
            print(f"❌ Voice update error: {str(e)}")
            return False
    
    # Voice clone management methods
    # These methods provide CRUD operations for voice clones in Firebase
    
    async def get_active_voice_clone_id(self, user_id: str) -> Optional[str]:
        """Get the active voice clone ID for a user"""
        try:
            if not is_firebase_available() or not self.db:
                return None
            
            user_ref = self.db.collection('users').document(user_id)
            user_doc = user_ref.get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
                return user_data.get('active_voice_clone_id')
            
            return None
            
        except Exception as e:
            print(f"❌ get_active_voice_clone_id error: {str(e)}")
            return None
    
    async def create_voice_clone_multiple(
        self, 
        user_id: str, 
        voice_name: str,
        audio_data: bytes,
        description: str = "Custom voice clone"
    ) -> Optional[Dict[str, Any]]:
        """Create a new voice clone for a user"""
        try:
            print(f"🎤 Creating voice clone with Cartesia for user {user_id}: {voice_name}")
            
            voice_id = await self.clone_voice_from_audio(
                audio_data=audio_data,
                user_id=user_id,
                voice_name=voice_name,
                description=description
            )
            
            if not voice_id:
                return None
            
            # Generate unique clone ID
            voice_clone_id = f"vc_{uuid.uuid4().hex[:12]}"
            
            # Save to voice_clones subcollection
            if is_firebase_available() and self.db:
                voice_clone_ref = self.db.collection('users').document(user_id).collection('voice_clones').document(voice_clone_id)
                
                voice_clone_data = {
                    'voice_clone_id': voice_clone_id,
                    'voice_id': voice_id,
                    'voice_name': voice_name,
                    'description': description,
                    'is_active': False,
                    'provider': 'cartesia',
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }
                
                voice_clone_ref.set(voice_clone_data)
                print(f"✅ Voice clone saved to Firestore: {voice_clone_id}")
                
                return voice_clone_data
            
            return None
            
        except Exception as e:
            print(f"❌ create_voice_clone_multiple error: {str(e)}")
            return None
    
    async def get_user_voice_clones(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all voice clones for a user"""
        try:
            if not is_firebase_available() or not self.db:
                return []
            
            voice_clones_ref = self.db.collection('users').document(user_id).collection('voice_clones')
            voice_clones_docs = voice_clones_ref.stream()
            
            voice_clones = []
            for doc in voice_clones_docs:
                clone_data = doc.to_dict()
                
                # Convert datetime to ISO string
                if 'created_at' in clone_data and hasattr(clone_data['created_at'], 'isoformat'):
                    clone_data['created_at'] = clone_data['created_at'].isoformat()
                if 'updated_at' in clone_data and hasattr(clone_data['updated_at'], 'isoformat'):
                    clone_data['updated_at'] = clone_data['updated_at'].isoformat()
                
                voice_clones.append(clone_data)
            
            print(f"📋 Found {len(voice_clones)} voice clones for user {user_id}")
            return voice_clones
            
        except Exception as e:
            print(f"❌ get_user_voice_clones error: {str(e)}")
            return []
    
    async def set_active_voice_clone(self, user_id: str, voice_clone_id: Optional[str]) -> bool:
        """Set the active voice clone for a user"""
        try:
            if not is_firebase_available() or not self.db:
                return False
            
            user_ref = self.db.collection('users').document(user_id)
            
            if voice_clone_id:
                user_ref.update({
                    'active_voice_clone_id': voice_clone_id,
                    'updated_at': datetime.utcnow()
                })
                
                # Update voice clone flags
                voice_clones_ref = self.db.collection('users').document(user_id).collection('voice_clones')
                voice_clones_docs = voice_clones_ref.stream()
                
                for doc in voice_clones_docs:
                    doc.reference.update({
                        'is_active': doc.id == voice_clone_id,
                        'updated_at': datetime.utcnow()
                    })
                
                print(f"✅ Set active voice clone: {voice_clone_id}")
            else:
                user_ref.update({
                    'active_voice_clone_id': firestore.DELETE_FIELD,
                    'updated_at': datetime.utcnow()
                })
                
                # Set all as inactive
                voice_clones_ref = self.db.collection('users').document(user_id).collection('voice_clones')
                voice_clones_docs = voice_clones_ref.stream()
                
                for doc in voice_clones_docs:
                    doc.reference.update({
                        'is_active': False,
                        'updated_at': datetime.utcnow()
                    })
                
                print(f"✅ Set to use default voice")
            
            return True
            
        except Exception as e:
            print(f"❌ set_active_voice_clone error: {str(e)}")
            return False
    
    async def delete_voice_clone_by_id(self, user_id: str, voice_clone_id: str) -> bool:
        """Delete a specific voice clone"""
        try:
            if not is_firebase_available() or not self.db:
                return False
            
            voice_clone_ref = self.db.collection('users').document(user_id).collection('voice_clones').document(voice_clone_id)
            voice_clone_doc = voice_clone_ref.get()
            
            if not voice_clone_doc.exists:
                print(f"⚠️ Voice clone not found: {voice_clone_id}")
                return False
            
            voice_clone_data = voice_clone_doc.to_dict()
            voice_id = voice_clone_data.get('voice_id')
            
            # Delete from Cartesia
            if voice_id:
                try:
                    await self.delete_cloned_voice(voice_id, user_id)
                except Exception as e:
                    print(f"⚠️ Failed to delete from Cartesia: {e}")
            
            # Delete from Firestore
            voice_clone_ref.delete()
            print(f"✅ Voice clone deleted: {voice_clone_id}")
            
            # Clear active voice if needed
            active_voice_id = await self.get_active_voice_clone_id(user_id)
            if active_voice_id == voice_clone_id:
                await self.set_active_voice_clone(user_id, None)
            
            return True
            
        except Exception as e:
            print(f"❌ delete_voice_clone_by_id error: {str(e)}")
            return False
    
    def get_default_voice_info(self) -> Dict[str, Any]:
        """Get default voice information"""
        return {
            "voice_id": self.default_voice_id,
            "voice_name": "British Lady (Default)",
            "description": "Professional female narrator voice",
            "is_default": True,
            "language": "English",
            "accent": "British",
            "provider": "cartesia"
        }
