# ===== app/services/media_service.py - SEEDREAM 4 IMPLEMENTATION =====
# Updated: October 27, 2025 - Switched to SeeDream 4 hosted by Replicate for image generation
import io
import json
import time
import base64
import asyncio
import aiohttp
import httpx
import random
import tempfile
from typing import Union, List, Dict
from fastapi import HTTPException
from openai import OpenAI
import replicate
from src.core.config import settings
from src.common_function.storage_service import StorageService
from src.common_function.cartesia_voice import CartesiaService
from src.common_function.audio_mixer_service import AudioMixerService
from src.common_function.audio_processor import AudioProcessor
from src.common_function.async_utils import get_or_create_event_loop
from PIL import Image

class MediaService:
    def __init__(self, openai_client: OpenAI):
        self.openai_client = openai_client
        self.cartesia_service = CartesiaService()  # Cartesia for TTS and voice cloning
        self.audio_mixer_service = AudioMixerService()
        # Initialize async HTTP client for non-blocking requests
        self.http_client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
        # Initialize Replicate client for SeeDream 4
        if settings.replicate_api_token:
            import os
            os.environ['REPLICATE_API_TOKEN'] = settings.replicate_api_token
            print("✅ MediaService initialized with SeeDream 4 (Replicate)")
        else:
            print("⚠️ Replicate API token not configured - image generation may not work")
        
        # Face consistency instructions to append to all prompts
        self.face_consistency_instructions = """

These are the instructions for image generation:
Analyze the provided reference image carefully and recreate the person with a face that closely resembles the sample image. Maintain all key physical attributes — including the same skin tone, eye color, hair color, hairstyle, facial structure, and overall age appearance. Ensure the person remains easily recognizable as the same person from the reference image.

You may adjust the pose, body position, and facial expression to make the final image more engaging, friendly, and appealing to young children. The composition, colors, and lighting should all contribute to a warm, cheerful, and visually inviting look suitable for children's content (such as storybooks, educational materials, or cartoons).

Use a soft color palette, gentle lighting, and expressive eyes or smiles to enhance friendliness. The final result should be aesthetically pleasing, child-safe, and emotionally positive, while keeping the person's likeness faithful to the reference."""
    
    def _create_placeholder_image(self, dimensions: tuple = (1024, 1024)) -> bytes:
        """Create a simple placeholder image with text overlay at specified dimensions"""
        try:
            width, height = dimensions
            # Create an image with the specified dimensions
            image = Image.new('RGB', (width, height), color='#f0f0f0')
            
            # Add simple text overlay
            try:
                # Try to use a basic font
                from PIL import ImageDraw
                draw = ImageDraw.Draw(image)
                
                # Add centered text
                text = "Story Image\nGenerating..."
                text_bbox = draw.textbbox((0, 0), text)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                
                x = (width - text_width) // 2
                y = (height - text_height) // 2
                
                draw.text((x, y), text, fill='#666666')
                
            except Exception:
                pass  # Skip text if font issues
            
            # Convert to bytes
            output_buffer = io.BytesIO()
            image.save(output_buffer, format='JPEG', quality=85)
            return output_buffer.getvalue()
            
        except Exception as e:
            print(f"⚠️ Error creating placeholder: {e}")
            # Return minimal valid JPEG
            width, height = dimensions
            minimal_image = Image.new('RGB', (width, height), color='white')
            buffer = io.BytesIO()
            minimal_image.save(buffer, format='JPEG')
            return buffer.getvalue()
    
    def _process_image_fast(self, image_data: bytes, target_dimensions: tuple = (1024, 1024)) -> bytes:
        """Optimized image processing for speed with custom dimensions"""
        try:
            image = Image.open(io.BytesIO(image_data))
            
            # Fast resize with lower quality for speed
            resized_image = image.resize(target_dimensions, Image.NEAREST)  # Faster than LANCZOS
            
            if resized_image.mode in ('RGBA', 'LA', 'P'):
                resized_image = resized_image.convert('RGB')
            
            output_buffer = io.BytesIO()
            resized_image.save(output_buffer, format='JPEG', quality=75, optimize=False)  # Lower quality, no optimization for speed
            
            return output_buffer.getvalue()
        except:
            return self._create_placeholder_image(target_dimensions)

    def _normalize_replicate_output(self, output) -> Union[str, bytes, None]:
        """
        Normalize replicate.run() output to either a URL string or raw image bytes.

        Returns:
            - str: a URL that can be fetched with httpx
            - bytes: raw image bytes (already downloaded/saved)
            - None: if nothing usable could be extracted
        """
        try:
            # If it's already a string URL
            if isinstance(output, str):
                return output

            # If it's a list/tuple, recurse on first element
            if isinstance(output, (list, tuple)) and len(output) > 0:
                return self._normalize_replicate_output(output[0])

            # If it's a mapping (dict-like) with 'url'
            if isinstance(output, dict):
                url = output.get('url') or output.get('file') or output.get('path')
                if isinstance(url, str):
                    return url

            # Generic file-like handling (covers replicate.helpers.FileOutput and similar)
            try:
                # Try common URL-like attributes first
                for attr in ('url', '_url', 'path', 'file', 'name'):
                    if hasattr(output, attr):
                        val = getattr(output, attr)
                        if isinstance(val, str) and val:
                            return val

                # Try to save to a temp file if a save method exists
                if hasattr(output, 'save'):
                    try:
                        tmp = tempfile.NamedTemporaryFile(delete=False)
                        tmp_name = tmp.name
                        tmp.close()
                        output.save(tmp_name)
                        with open(tmp_name, 'rb') as f:
                            data = f.read()
                        return data
                    except Exception:
                        pass

                # Some FileOutput objects are file-like and support read()
                if hasattr(output, 'read'):
                    try:
                        data = output.read()
                        if isinstance(data, (bytes, bytearray)):
                            return bytes(data)
                    except Exception:
                        pass
            except Exception:
                # If something goes wrong, continue to other fallbacks
                pass

            # Fallback: try to coerce to str and hope it's a URL
            try:
                s = str(output)
                if s.startswith('http'):
                    return s
            except Exception:
                pass

        except Exception:
            pass

        return None
    
    # FACE SWAP FEATURE - COMMENTED OUT FOR NOW (DEEPIMAGE AI)
    # async def swap_face_deepimage(self, target_image_bytes: bytes, source_image_url: str) -> bytes:
    #     """
    #     Swap face using Deep-Image AI API with face swapping
    #     target_image_bytes: The generated story image where we want to swap the face
    #     source_image_url: The Firebase URL of the child's reference image
    #     Returns: The face-swapped image as bytes
    #     """
    #     # Face swap functionality disabled for now - return original image
    #     return target_image_bytes

    async def generate_audio_batch(self, scene_texts: List[Dict], isfemale: bool = True, user_id: str = None, use_cloned_voice: bool = True, prefer_voice_consistency: bool = True, language: str = "english", voice_clone_id: str = None) -> List[bytes]:
        """Generate audio for multiple scenes using Cartesia TTS with ambient sound mixing - OPTIMIZED
        
        Args:
            voice_clone_id: Optional specific voice clone ID to use (overrides auto-detection)
        """
        try:
            # Map language name to code (expanded for more languages)
            language_code_map = {
                "english": "en",
                "spanish": "es",
                "french": "fr",
                "german": "de",
                "hindi": "hi",
                "chinese": "zh",
                "japanese": "ja",
                "korean": "ko",
                "portuguese": "pt",
                "italian": "it",
                "russian": "ru",
                "arabic": "ar",
                "bengali": "bn",
                "tamil": "ta",
                "telugu": "te",
                "gujarati": "gu",
                "punjabi": "pa",
                "urdu": "ur",
                "marathi": "mr"
            }
            language_code = language_code_map.get(language.lower(), "en")
            
            print(f"🎵 Batch audio generation: {len(scene_texts)} scenes in {language} ({language_code})")
            
            # Use Cartesia service for batch audio generation
            cartesia_audio = await self.cartesia_service.generate_speech_batch_cartesia(scene_texts, user_id, use_cloned_voice, language_code, voice_clone_id)
            
            # Check for failures
            failed_indices = [i for i, audio in enumerate(cartesia_audio) if audio is None]
            
            if failed_indices:
                failure_percentage = len(failed_indices) / len(scene_texts) * 100
                
                # OPTIMIZED: Simplified retry strategy for better latency
                # If >50% failed with voice clone, switch ALL to default voice immediately (no retries)
                if use_cloned_voice and failure_percentage > 50:
                    # Major failure - switch to default voice for all scenes
                    final_audio = await self.cartesia_service.generate_speech_batch_cartesia(
                        scene_texts, user_id, use_cloned_voice=False, language=language_code, voice_clone_id=None
                    )
                else:
                    # Minor failures - retry only failed scenes once
                    failed_scenes = [scene_texts[i] for i in failed_indices]
                    retry_audio = await self.cartesia_service.generate_speech_batch_cartesia(
                        failed_scenes, user_id, use_cloned_voice=use_cloned_voice, language=language_code, voice_clone_id=voice_clone_id
                    )
                    
                    final_audio = cartesia_audio.copy()
                    for i, fallback_idx in enumerate(failed_indices):
                        if i < len(retry_audio) and retry_audio[i] is not None:
                            final_audio[fallback_idx] = retry_audio[i]
                    
                    # Check remaining failures - use OpenAI as last resort
                    still_failed = [i for i, audio in enumerate(final_audio) if audio is None]
                    if still_failed:
                        still_failed_scenes = [scene_texts[i] for i in still_failed]
                        openai_fallback = await self.generate_audio_batch_openai(still_failed_scenes, isfemale=isfemale, skip_ambient_mixing=True)
                        
                        for i, scene_idx in enumerate(still_failed):
                            if i < len(openai_fallback) and openai_fallback[i] is not None:
                                final_audio[scene_idx] = openai_fallback[i]
            else:
                final_audio = cartesia_audio
            
            # Add ambient sounds
            mixed_audio = []
            for i, (voice_audio, scene_data) in enumerate(zip(final_audio, scene_texts)):
                if voice_audio and voice_audio != b"audio_placeholder":
                    ambient_keywords = scene_data.get("ambient_sound_keywords", "").strip()
                    
                    if ambient_keywords:
                        try:
                            # Call mixer directly (no async with - service manages its own sessions)
                            mixed_scene_audio = await self.audio_mixer_service.process_scene_audio(
                                narration_audio=voice_audio,
                                ambient_keywords=ambient_keywords,
                                scene_number=i+1
                            )
                            mixed_audio.append(mixed_scene_audio)
                        except Exception:
                            mixed_audio.append(voice_audio)
                    else:
                        mixed_audio.append(voice_audio)
                else:
                    mixed_audio.append(voice_audio)
            
            return mixed_audio
            
        except Exception as e:
            print(f"Audio batch generation failed: {str(e)}")
            return await self.generate_audio_batch_openai(scene_texts, isfemale=isfemale)
    
    async def generate_audio_batch_openai(self, scene_texts: List[Dict], isfemale: bool = True, skip_ambient_mixing: bool = False) -> List[bytes]:
        """Optimized batch audio generation using OpenAI TTS with ambient sound mixing"""
        try:
            voice = "sage" if isfemale else "onyx"
            
            async def generate_single_audio_fast(scene_data):
                text = scene_data['text']
                scene_number = scene_data['scene_number']
                
                try:
                    loop = get_or_create_event_loop()
                    
                    def create_tts_fast():
                        response = self.openai_client.audio.speech.create(
                            model="tts-1-hd",
                            voice=voice,
                            input=text[:1000],
                            response_format="mp3",
                            speed=1.1
                        )
                        return response.content
                    
                    audio_data = await loop.run_in_executor(None, create_tts_fast)
                    return audio_data
                    
                except Exception:
                    return b"audio_placeholder"
            
            # Parallel execution with timeout
            tasks = [generate_single_audio_fast(scene_data) for scene_data in scene_texts]
            audio_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=60.0
            )
            
            # Process results
            voice_audio_batch = []
            for i, result in enumerate(audio_results):
                if isinstance(result, Exception):
                    voice_audio_batch.append(b"audio_placeholder")
                else:
                    voice_audio_batch.append(result)
            
            # Add ambient sound mixing if not skipped
            if not skip_ambient_mixing:
                mixed_audio_batch = []
                
                for i, (voice_audio, scene_data) in enumerate(zip(voice_audio_batch, scene_texts)):
                    if voice_audio and voice_audio != b"audio_placeholder":
                        ambient_keywords = scene_data.get("ambient_sound_keywords", "").strip()
                        
                        if ambient_keywords:
                            try:
                                # Call mixer directly (no async with - service manages its own sessions)
                                mixed_scene_audio = await self.audio_mixer_service.process_scene_audio(
                                    narration_audio=voice_audio,
                                    ambient_keywords=ambient_keywords,
                                    scene_number=i+1
                                )
                                mixed_audio_batch.append(mixed_scene_audio)
                            except Exception:
                                mixed_audio_batch.append(voice_audio)
                        else:
                            mixed_audio_batch.append(voice_audio)
                    else:
                        mixed_audio_batch.append(voice_audio)
                
                return mixed_audio_batch
            else:
                return voice_audio_batch
                
        except asyncio.TimeoutError:
            return [b"audio_placeholder" for _ in scene_texts]
        except Exception as e:
            print(f"OpenAI batch processing failed: {str(e)}")
            return [b"audio_placeholder" for _ in scene_texts]
    
    async def generate_image_batch(self, visual_prompts: List[Dict], child_image_url: str = None, target_dimensions: tuple = (2048, 2048)) -> List[bytes]:
        """Generate multiple images in parallel using SeeDream 4 at 2K resolution"""
        try:
            # Force square 2K images for consistency and optimal speed
            target_dimensions = (2048, 2048)
            print(f"🖼️ Batch generating {len(visual_prompts)} images at {target_dimensions[0]}x{target_dimensions[1]} with SeeDream 4 2K")
            
            # Use semaphore to respect API rate limits (increased to 5 for better parallelism)
            semaphore = asyncio.Semaphore(5)
            
            async def generate_single_image(prompt_data):
                """Generate image for a single scene"""
                async with semaphore:
                    try:
                        per_scene_refs = prompt_data.get('reference_image_urls')
                        image_data = await self.generate_image(
                            visual_prompt=prompt_data['visual_prompt'],
                            scene_number=prompt_data['scene_number'],
                            child_image_url=child_image_url,
                            target_dimensions=target_dimensions,
                            reference_image_urls=per_scene_refs
                        )
                        print(f"✅ Scene {prompt_data['scene_number']}: {len(image_data)} bytes")
                        return image_data
                        
                    except Exception as e:
                        print(f"❌ Scene {prompt_data['scene_number']} failed: {str(e)}")
                        return self._create_placeholder_image(target_dimensions)
            
            # Generate all images in parallel
            tasks = [generate_single_image(prompt_data) for prompt_data in visual_prompts]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results and handle any exceptions
            images = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"❌ Exception in batch task {i}: {str(result)}")
                    images.append(self._create_placeholder_image(target_dimensions))
                else:
                    images.append(result)
            
            # Process results
            images = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    print(f"⚠️ Scene {i+1} error, using placeholder")
                    images.append(self._create_placeholder_image(target_dimensions))
                else:
                    images.append(result)
            
            print(f"✅ Batch generation completed: {len(images)} images")
            return images
            
        except Exception as e:
            print(f"❌ Batch generation failed: {str(e)}")
            return [self._create_placeholder_image(target_dimensions) for _ in visual_prompts]
    
    async def generate_audio(self, text: str, scene_number: int, isfemale: bool = True, user_id: str = None, use_cloned_voice: bool = True, ambient_sound_keywords: List[str] = None, language: str = "english", emotion: str = "neutral", voice_clone_id: str = None) -> bytes:
        """Generate audio using Cartesia TTS (primary) with OpenAI fallback
        
        Args:
            text: Text to convert to speech
            scene_number: Scene number for tracking
            isfemale: Gender for fallback voice (if needed)
            user_id: User ID for voice clone lookup
            use_cloned_voice: Whether to use user's cloned voice
            ambient_sound_keywords: Keywords for ambient sound mixing
            language: Language for speech generation
            emotion: Emotion for speech generation
            voice_clone_id: Specific voice clone ID to use (overrides auto-detection)
        """
        print(f"🎵 MediaService.generate_audio called for scene {scene_number} with emotion: {emotion}")
        if voice_clone_id:
            print(f"🎤 Using provided voice_clone_id: {voice_clone_id}")
        if ambient_sound_keywords:
            print(f"🌿 Ambient keywords received: {ambient_sound_keywords}")
        else:
            print(f"🔇 No ambient keywords provided for scene {scene_number}")
        
        # Map language name to code
        language_code_map = {
            "english": "en",
            "spanish": "es",
            "french": "fr",
            "german": "de",
            "hindi": "hi",
            "chinese": "zh",
            "japanese": "ja",
            "korean": "ko",
            "portuguese": "pt",
            "italian": "it",
            "russian": "ru",
            "arabic": "ar"
        }
        language_code = language_code_map.get(language.lower(), "en")
            
        try:
            print(f"🎤 Using Cartesia TTS for scene {scene_number} (language: {language_code}, emotion: {emotion})")
            # Get user's voice ID and generate with Cartesia
            voice_id = await self.cartesia_service.get_user_voice_id(user_id, use_cloned_voice, voice_clone_id) if user_id else voice_clone_id
            audio_bytes = await self.cartesia_service.generate_speech_cartesia(
                text, 
                voice_id, 
                scene_number, 
                language=language_code,
                emotion=emotion
            )
            
            # Mix with ambient sounds if keywords provided
            if ambient_sound_keywords:
                print(f"🎵 Starting ambient sound mixing for scene {scene_number}")
                print(f"🌿 Keywords: {ambient_sound_keywords}")
                try:
                    # Convert list of keywords to string for AudioMixerService
                    if isinstance(ambient_sound_keywords, list):
                        keywords_str = " ".join(ambient_sound_keywords)
                    else:
                        keywords_str = str(ambient_sound_keywords)
                    
                    print(f"🌿 Converting keywords to string: {keywords_str}")
                    
                    # Call mixer directly (no async with - service manages its own sessions)
                    mixed_audio_bytes = await self.audio_mixer_service.process_scene_audio(
                        narration_audio=audio_bytes,
                        ambient_keywords=keywords_str,
                        scene_number=scene_number
                    )
                    print(f"✅ SUCCESS: Ambient mixing completed for scene {scene_number}")
                    print(f"📊 Mixed audio size: {len(mixed_audio_bytes)} bytes (was {len(audio_bytes)} bytes)")
                    return mixed_audio_bytes
                except Exception as ambient_error:
                    print(f"❌ FAILED: Ambient mixing error for scene {scene_number}: {ambient_error}")
                    import traceback
                    traceback.print_exc()
                    print(f"📁 Fallback: Using voice-only audio")
                    return audio_bytes  # Return original audio if mixing fails
            else:
                print(f"🔇 No ambient keywords for scene {scene_number} - using voice-only audio")
            
            print(f"✅ Cartesia voice-only audio ready for scene {scene_number}: {len(audio_bytes)} bytes")
            return audio_bytes
        except Exception as e:
            print(f"❌ Cartesia TTS failed for scene {scene_number}: {str(e)}")
            print(f"🔄 VOICE CONSISTENCY: Retrying with Cartesia default voice before OpenAI fallback...")
            
            try:
                # First try: Retry with Cartesia default voice to maintain consistency
                default_voice_id = self.cartesia_service.default_voice_id
                audio_bytes = await self.cartesia_service.generate_speech_cartesia(
                    text, 
                    default_voice_id, 
                    scene_number, 
                    language=language_code,
                    emotion=emotion
                )
                
                print(f"✅ Scene {scene_number} recovered with Cartesia default voice - consistency maintained")
                
                # Mix with ambient sounds if keywords provided
                if ambient_sound_keywords:
                    try:
                        if isinstance(ambient_sound_keywords, list):
                            keywords_str = " ".join(ambient_sound_keywords)
                        else:
                            keywords_str = str(ambient_sound_keywords)
                        
                        # Call mixer directly (no async with - service manages its own sessions)
                        mixed_audio_bytes = await self.audio_mixer_service.process_scene_audio(
                            narration_audio=audio_bytes,
                            ambient_keywords=keywords_str,
                            scene_number=scene_number
                        )
                        return mixed_audio_bytes
                    except Exception as ambient_error:
                        print(f"❌ Ambient mixing failed for default voice: {ambient_error}")
                        return audio_bytes
                else:
                    return audio_bytes
                    
            except Exception as default_error:
                print(f"❌ Cartesia default voice also failed for scene {scene_number}: {str(default_error)}")
                print(f"🔄 LAST RESORT: Falling back to OpenAI TTS...")
                return await self.generate_audio_openai(text, scene_number, isfemale=isfemale, ambient_sound_keywords=ambient_sound_keywords)
    
    async def generate_audio_openai(self, text: str, scene_number: int, isfemale: bool = True, ambient_sound_keywords: List[str] = None) -> bytes:
        """Fallback: Generate audio using OpenAI Text-to-Speech"""
        print(f"🎵 MediaService.generate_audio_openai called for scene {scene_number}")
        if ambient_sound_keywords:
            print(f"🌿 OpenAI ambient keywords received: {ambient_sound_keywords}")
        else:
            print(f"🔇 No ambient keywords for OpenAI scene {scene_number}")
            
        try:
            # Voice mapping: Eve (female) = "sage", Adam (male) = "onyx" (OpenAI TTS voices)
            voice = "sage" if isfemale else "onyx"  # Female = sage, Male = onyx
            print(f"🎵 Using OpenAI TTS for scene {scene_number}")
            print(f"🎤 Voice selected: {voice} ({'Eve (female)' if isfemale else 'Adam (male)'})")
            
            response = self.openai_client.audio.speech.create(
                model="tts-1",  # Standard model
                voice=voice,   # Dynamic voice based on isfemale parameter
                input=text,
                response_format="wav"  # Changed from mp3 to wav
            )
            
            # Convert response to bytes
            audio_bytes = b""
            for chunk in response.iter_bytes():
                audio_bytes += chunk
                
            print(f"✅ OpenAI audio generated for scene {scene_number}: {len(audio_bytes)} bytes")
            
            # Mix with ambient sounds if keywords provided
            if ambient_sound_keywords and ambient_sound_keywords:
                print(f"🎵 OpenAI TTS: Starting ambient sound processing for scene {scene_number}")
                print(f"🌿 Ambient keywords: {ambient_sound_keywords}")
                try:
                    # Convert list of keywords to string for AudioMixerService
                    if isinstance(ambient_sound_keywords, list):
                        keywords_str = " ".join(ambient_sound_keywords)
                    else:
                        keywords_str = str(ambient_sound_keywords)
                    
                    print(f"🌿 Converting keywords to string: {keywords_str}")
                    
                    # Call mixer directly (no async with - service manages its own sessions)
                    mixed_audio_bytes = await self.audio_mixer_service.process_scene_audio(
                        narration_audio=audio_bytes,
                        ambient_keywords=keywords_str,
                        scene_number=scene_number
                    )
                    print(f"✅ SUCCESS: OpenAI ambient mixing completed for scene {scene_number}")
                    print(f"🌐 Mixed audio ready for web delivery: {len(mixed_audio_bytes)} bytes (was {len(audio_bytes)} bytes)")
                    return mixed_audio_bytes
                except Exception as ambient_error:
                    print(f"❌ FAILED: OpenAI ambient mixing error for scene {scene_number}: {ambient_error}")
                    import traceback
                    traceback.print_exc()
                    print(f"📁 Fallback: Using voice-only audio")
                    # Fall through to return original audio
            else:
                print(f"🔇 No ambient keywords for OpenAI scene {scene_number} - using voice-only audio")
            
            # For web delivery, skip ESP32 normalization to preserve quality for Opus encoding
            # The storage service will handle Opus encoding and optimization
            print(f"🌐 Audio ready for web delivery processing: {len(audio_bytes)} bytes")
            return audio_bytes
            
        except Exception as e:
            print(f"❌ OpenAI TTS error for scene {scene_number}: {str(e)}")
            raise HTTPException(
                status_code=500, 
                detail=f"Audio generation failed for scene {scene_number}: {str(e)}"
            )
    

    


    async def generate_image(self, visual_prompt: str, scene_number: int, child_image_url: str = None, target_dimensions: tuple = (2048, 2048), reference_image_urls: List[str] = None) -> bytes:
        """Generate image using SeeDream 4 via Replicate at 2K resolution (optimized for speed/quality balance)"""
        print(f"🔍 MediaService.generate_image called for scene {scene_number}")
        print(f"   - child_image_url: {child_image_url[:80] if child_image_url else 'None'}...")
        print(f"   - reference_image_urls: {reference_image_urls}")
        try:
            # Use 2K (2048x2048) for optimal speed/quality balance - 4K is too slow for story generation
            target_dimensions = (2048, 2048)
            # Use SeeDream 4
            print(f"🎨 Attempting SeeDream 4 2K for scene {scene_number}")
            return await self.generate_image_seedream(visual_prompt, scene_number, child_image_url, target_dimensions, reference_image_urls)
        except Exception as e:
            print(f"❌ SeeDream 4 failed for scene {scene_number}: {str(e)}")
            print(f"🔄 Creating placeholder image as fallback...")
            return self._create_placeholder_image(target_dimensions)
    
    async def generate_image_seedream(self, visual_prompt: str, scene_number: int, child_image_url: str = None, target_dimensions: tuple = (2048, 2048), reference_image_urls: List[str] = None) -> bytes:
        """Generate image using SeeDream 4 hosted on Replicate with 2K resolution (optimized balance)"""
        print(f"🎨 Using SeeDream 4 2K for scene {scene_number}")
        print(f"🔍 Debug - reference_image_urls parameter: {reference_image_urls}")
        print(f"🔍 Debug - reference_image_urls type: {type(reference_image_urls)}")
        print(f"🔍 Debug - reference_image_urls is None: {reference_image_urls is None}")
        print(f"🔍 Debug - reference_image_urls is empty: {reference_image_urls == []}")
        
        # Extract base prompt
        base_prompt = visual_prompt
        art_style_hint = None
        try:
            if isinstance(visual_prompt, dict):
                base_prompt = visual_prompt.get('visual_prompt', '')
                art_style_hint = visual_prompt.get('art_style')
            elif isinstance(visual_prompt, str):
                pass
        except Exception:
            base_prompt = str(visual_prompt)

        # Compose enhanced prompt with face consistency instructions
        style_prefix = f"Style: {art_style_hint}. " if art_style_hint else ""
        enhanced_prompt = f"Children's book illustration style, colorful and friendly, high quality digital art. {style_prefix}{base_prompt}{self.face_consistency_instructions}"
        
        print(f"📝 SeeDream 4 prompt (truncated): {enhanced_prompt[:150]}...")
        
        # Determine aspect ratio: 16:9 for thumbnails (scene 0), 1:1 for regular scenes
        if scene_number == 0:
            aspect_ratio = "16:9"  # Widescreen for thumbnails
            print(f"📐 Using 16:9 aspect ratio for thumbnail")
        else:
            aspect_ratio = "1:1"  # Square format for regular story scenes
            print(f"📐 Using 1:1 aspect ratio for story scene {scene_number}")
        
        # Prepare input parameters - use 2K for speed/quality balance
        input_params = {
            "prompt": enhanced_prompt,
            "aspect_ratio": aspect_ratio,
            "size": "2K",  # 2K resolution (2048px) - optimal balance
            "enhance_prompt": True  # Enable prompt enhancement
        }
        
        # Build image_input array combining child_image_url and reference_image_urls
        image_inputs = []
        if child_image_url:
            image_inputs.append(child_image_url)
            print(f"👶 Using child image for scene {scene_number}: {child_image_url[:80]}...")
        
        if reference_image_urls:
            image_inputs.extend(reference_image_urls)
            print(f"📸 Using {len(reference_image_urls)} reference image(s) for scene {scene_number}")
            for idx, ref_url in enumerate(reference_image_urls, 1):
                print(f"   Reference {idx}: {ref_url[:80]}...")
        
        # Add combined image inputs to params if we have any
        if image_inputs:
            input_params["image_input"] = image_inputs
            print(f"🖼️ Total {len(image_inputs)} image(s) passed to SeeDream 4")
        
        # Log the exact parameters being sent to the API
        print(f"\n{'='*80}")
        print(f"🔍 SEEDREAM 4 API CALL - Scene {scene_number}")
        print(f"{'='*80}")
        print(f"📋 Input Parameters:")
        for key, value in input_params.items():
            if key == "prompt":
                print(f"  • {key}: {str(value)[:100]}...")
            elif key == "image_input":
                print(f"  • {key}: [{len(value)} image(s)]")
            else:
                print(f"  • {key}: {value}")
        print(f"{'='*80}\n")
        
        # SeeDream 4 API call - Run in executor to avoid blocking event loop
        print(f"⏱️ Starting SeeDream 4 API call...")
        loop = asyncio.get_running_loop()
        
        # Wrap the blocking replicate.run call with timeout
        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(
                    None,  # Use default ThreadPoolExecutor
                    lambda: replicate.run(
                        "bytedance/seedream-4",
                        input=input_params
                    )
                ),
                timeout=120.0  # 2 minute timeout for image generation
            )
        except asyncio.TimeoutError:
            raise Exception(f"SeeDream 4 API call timed out after 120s")
        
        # Output is a list of URLs
        if not output or len(output) == 0:
            raise Exception("SeeDream 4 returned no images")
        
        # Get the first output item and normalize it to either a URL or raw bytes
        image_output = output[0]
        print(f"🔗 SeeDream 4 output (raw): {type(image_output)}")

        # Normalize output: may be a URL string, a replicate.helpers.FileOutput, dict, or bytes
        normalized = self._normalize_replicate_output(image_output)
        if normalized is None:
            raise Exception("SeeDream 4 returned an unsupported output type")

        # If normalized returned raw bytes, use them directly; else fetch the URL
        if isinstance(normalized, (bytes, bytearray)):
            image_data = bytes(normalized)
            print(f"✅ Obtained image bytes directly from Replicate output: {len(image_data)} bytes")
        else:
            image_url = normalized
            print(f"🔗 SeeDream 4 image URL: {image_url}")
            print(f"📥 Downloading image from Replicate CDN...")
            response = await self.http_client.get(image_url)
            response.raise_for_status()
            image_data = response.content
            print(f"✅ Downloaded SeeDream 4 2K image: {len(image_data)} bytes")
        
        # Load image to check dimensions
        image = Image.open(io.BytesIO(image_data))
        width, height = image.size
        actual_aspect_ratio = width / height
        
        print(f"\n{'='*80}")
        print(f"📏 IMAGE DIMENSIONS - Scene {scene_number}")
        print(f"{'='*80}")
        print(f"  Original Width:  {width}px")
        print(f"  Original Height: {height}px")
        print(f"  Aspect Ratio: {actual_aspect_ratio:.4f}")
        
        # Verify aspect ratio matches expectation
        if scene_number == 0:
            expected_ratio = 16/9
            print(f"  Expected (16:9): {expected_ratio:.4f}")
            if abs(actual_aspect_ratio - expected_ratio) < 0.01:
                print(f"  ✅ Correct 16:9 aspect ratio!")
            else:
                print(f"  ⚠️ WARNING: Not 16:9! Difference: {abs(actual_aspect_ratio - expected_ratio):.4f}")
        else:
            expected_ratio = 1.0
            print(f"  Expected (1:1): {expected_ratio:.4f}")
            if abs(actual_aspect_ratio - expected_ratio) < 0.01:
                print(f"  ✅ Correct 1:1 aspect ratio!")
            else:
                print(f"  ⚠️ WARNING: Not 1:1! Difference: {abs(actual_aspect_ratio - expected_ratio):.4f}")
        print(f"{'='*80}\n")
        
        # DO NOT RESIZE - Keep the aspect ratio from the API!
        # The API already generated the image at the correct aspect ratio
        # Resizing would distort the image
        print(f"✅ Keeping original aspect ratio from API")
        
        # Convert to JPEG with optimized quality for 2K
        output_buffer = io.BytesIO()
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        image.save(output_buffer, format='JPEG', quality=95, optimize=True)
        final_image_data = output_buffer.getvalue()
        
        print(f"✅ Scene {scene_number} 2K image: {len(final_image_data)} bytes ({target_dimensions[0]}x{target_dimensions[1]})")
        return final_image_data
    
    async def generate_image_openai(self, visual_prompt: str, scene_number: int, child_image_url: str = None, target_dimensions: tuple = (2048, 2048)) -> bytes:
        """DEPRECATED: Old OpenAI image generation - kept for compatibility"""
        print(f"⚠️ OpenAI image generation is deprecated, using SeeDream 4 2K instead")
        return await self.generate_image_seedream(visual_prompt, scene_number, child_image_url, target_dimensions)
    
    def _sanitize_visual_prompt(self, prompt: str) -> str:
        """Apply child safety filters to visual prompts"""
        # Remove potentially inappropriate keywords
        inappropriate_words = [
            'scary', 'dark', 'violent', 'weapon', 'gun', 'knife', 'blood', 'death',
            'monster', 'evil', 'demon', 'horror', 'nightmare', 'spooky', 'creepy',
            'sad', 'crying', 'angry', 'mean', 'dangerous', 'hurt', 'pain'
        ]
        
        safe_prompt = prompt.lower()
        for word in inappropriate_words:
            safe_prompt = safe_prompt.replace(word, '')
        
        # Add positive descriptors
        safe_descriptors = [
            'happy', 'colorful', 'bright', 'cheerful', 'friendly', 'smiling', 
            'magical', 'wonderful', 'beautiful', 'peaceful', 'joyful'
        ]
        
        # Clean up extra spaces
        safe_prompt = ' '.join(safe_prompt.split())
        
        # Add a random positive descriptor if the prompt seems too plain
        if len(safe_prompt.split()) < 5:
            import random
            safe_prompt += f" {random.choice(safe_descriptors)}"
        
        return safe_prompt
    
    async def generate_story_thumbnail(self, thumbnail_prompt: str, story_id: str, child_image_url: str = None) -> bytes:
        """
        Generate a 16:9 widescreen thumbnail image for the story using SeeDream 4 at 2K
        
        Args:
            thumbnail_prompt: Description for the thumbnail image
            story_id: Story ID for logging
            child_image_url: Optional child image for personalization
            
        Returns:
            thumbnail image bytes in 16:9 format at 2K resolution (optimal for thumbnails)
        """
        try:
            # Use 16:9 aspect ratio at 2K resolution (1920x1080)
            thumbnail_dimensions = (1920, 1080)

            print(f"🖼️ Generating 16:9 widescreen story thumbnail for story {story_id} with SeeDream 4")
            print(f"📐 Thumbnail dimensions: {thumbnail_dimensions[0]}x{thumbnail_dimensions[1]} (16:9 aspect ratio)")

            # Enhance the prompt for thumbnail generation
            enhanced_prompt = f"Widescreen 16:9 thumbnail cover image, children's book style, colorful and engaging, digital illustration, soft shading, semi-realistic: {thumbnail_prompt}"

            # Generate thumbnail using SeeDream 4
            thumbnail_data = await self.generate_image(
                visual_prompt=enhanced_prompt,
                scene_number=0,  # Use 0 to indicate thumbnail
                child_image_url=child_image_url,
                target_dimensions=thumbnail_dimensions
            )

            print(f"✅ Story thumbnail generated: {len(thumbnail_data)} bytes ({thumbnail_dimensions[0]}x{thumbnail_dimensions[1]}, 16:9)")
            return thumbnail_data
            
        except Exception as e:
            print(f"❌ Thumbnail generation failed for story {story_id}: {str(e)}")
            # Create a placeholder thumbnail
            return self._create_placeholder_thumbnail(thumbnail_dimensions)
    
    def _create_placeholder_thumbnail(self, dimensions: tuple = (1920, 1080)) -> bytes:
        """Create a placeholder thumbnail image in 16:9 format"""
        try:
            width, height = dimensions
            print(f"🖼️ Creating placeholder thumbnail: {width}x{height} (16:9)")
            
            # Create thumbnail with gradient background
            image = Image.new('RGB', (width, height), color='#4a90e2')  # Nice blue color
            
            # Add text overlay
            try:
                from PIL import ImageDraw, ImageFont
                draw = ImageDraw.Draw(image)
                
                # Add centered text
                title_text = "Story Thumbnail"
                subtitle_text = "Generating..."
                
                # Calculate positions for centered text
                title_bbox = draw.textbbox((0, 0), title_text)
                title_width = title_bbox[2] - title_bbox[0]
                title_height = title_bbox[3] - title_bbox[1]
                
                subtitle_bbox = draw.textbbox((0, 0), subtitle_text)
                subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
                
                title_x = (width - title_width) // 2
                title_y = (height - title_height) // 2 - 20
                
                subtitle_x = (width - subtitle_width) // 2
                subtitle_y = title_y + title_height + 10
                
                draw.text((title_x, title_y), title_text, fill='white')
                draw.text((subtitle_x, subtitle_y), subtitle_text, fill='white')
                
            except Exception:
                pass  # Skip text if font issues
            
            # Convert to bytes
            output_buffer = io.BytesIO()
            image.save(output_buffer, format='JPEG', quality=85)
            return output_buffer.getvalue()
            
        except Exception as e:
            print(f"⚠️ Error creating placeholder thumbnail: {e}")
            # Return minimal valid JPEG
            width, height = dimensions
            minimal_image = Image.new('RGB', (width, height), color='#f0f0f0')
            buffer = io.BytesIO()
            minimal_image.save(buffer, format='JPEG')
            return buffer.getvalue()

    async def health_check(self) -> Dict[str, bool]:
        """Check health of all services"""
        health = {
            "openai_tts": False,
            "gpt_image_1_mini": False,
            "overall": False
        }
        
        try:
            # Quick OpenAI TTS test
            test_response = self.openai_client.audio.speech.create(
                model="tts-1",
                voice="sage",
                input="test",
                response_format="mp3"
            )
            health["openai_tts"] = len(test_response.content) > 0
            
            # GPT-Image-1-Mini test (quick prompt)
            try:
                test_image_response = self.openai_client.images.generate(
                    model="gpt-image-1-mini",
                    prompt="test image",
                    size="1024x1024",
                    quality="high",
                    n=1
                )
                health["gpt_image_1_mini"] = bool(test_image_response.data and test_image_response.data[0].url)
            except:
                health["gpt_image_1_mini"] = False
            
            health["overall"] = health["openai_tts"] and health["gpt_image_1_mini"]
            
        except Exception as e:
            print(f"Health check failed: {str(e)}")
        
        return health