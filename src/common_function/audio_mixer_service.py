# ===== app/services/audio_mixer_service.py =====
import os
import asyncio
import aiohttp
import json
import tempfile
from typing import Optional, List, Dict, Any, Tuple
from pydub import AudioSegment
from pydub.effects import normalize, compress_dynamic_range
import io
import concurrent.futures
import base64
from src.core.config import settings
from src.common_function.async_utils import get_or_create_event_loop

class AudioMixerService:
    """Service for fetching ambient sounds from Freesound.org and mixing with narration"""
    
    def __init__(self, freesound_api_key: Optional[str] = None):
        self.freesound_api_key = freesound_api_key or getattr(settings, 'freesound_api_key', '')
        # Optional OAuth2 access token (preferred for full-quality downloads)
        self.freesound_oauth_token = os.environ.get('FREESOUND_OAUTH_TOKEN') or getattr(settings, 'freesound_oauth_token', '')
        self.freesound_base_url = "https://freesound.org/apiv2"
        
        # Cache for ambient sounds to avoid re-downloading the same sound multiple times per story
        self._ambient_cache: Dict[str, bytes] = {}
        # Lock to prevent race condition when multiple scenes try to download the same ambient sound
        # Lazy-initialized to avoid event loop issues
        self._cache_lock: Optional[asyncio.Lock] = None
        # Optional global bed reuse (per-process scope)
        self._global_bed_key: str = "__global__"

        # Disk persistence setup
        self._enable_persistence: bool = getattr(settings, 'enable_ambient_persistence', False)
        self._cache_dir: str = getattr(settings, 'ambient_cache_dir', './cache/ambient')
        self._cache_max_entries: int = getattr(settings, 'ambient_cache_max_entries', 100)
        self._reuse_single_bed: bool = getattr(settings, 'reuse_single_ambient_bed', False)
        self._enable_enhancement: bool = getattr(settings, 'enable_audio_enhancement', True)

        if self._enable_persistence:
            try:
                os.makedirs(self._cache_dir, exist_ok=True)
                self._load_disk_cache_initial()
                print(f"💾 Ambient persistence enabled. Directory: {self._cache_dir}")
            except Exception as e:
                print(f"⚠️ Failed to initialize ambient cache directory '{self._cache_dir}': {e}")
                self._enable_persistence = False
        
        # Log API key status for debugging
        if self.freesound_api_key:
            print(f"🔑 Freesound API key configured (length: {len(self.freesound_api_key)})")
        else:
            print("⚠️ Freesound API key not configured - ambient sounds will be disabled")
            print("💡 Set FREESOUND_API_KEY environment variable to enable ambient sounds")
    
    @property
    def cache_lock(self) -> asyncio.Lock:
        """Lazy-initialize the cache lock to avoid event loop issues during __init__"""
        if self._cache_lock is None:
            self._cache_lock = asyncio.Lock()
        return self._cache_lock

    # ===== Disk Cache Helpers =====
    def _cache_filename(self, key: str) -> str:
        safe_key = key.replace(' ', '_').replace('/', '_')[:120]
        return os.path.join(self._cache_dir, f"{safe_key}.bin")

    def _load_disk_cache_initial(self):
        """Load a limited number of ambient cache files into memory on startup."""
        try:
            files = [f for f in os.listdir(self._cache_dir) if f.endswith('.bin')]
            # Limit initial load to max entries
            for f in files[: self._cache_max_entries]:
                path = os.path.join(self._cache_dir, f)
                try:
                    with open(path, 'rb') as fh:
                        data = fh.read()
                    key = f[:-4].replace('_', ' ')  # Approximate reverse (best-effort)
                    self._ambient_cache[key] = data
                except Exception:
                    continue
            if files:
                print(f"📦 Preloaded {min(len(files), self._cache_max_entries)} ambient cache file(s) from disk")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"⚠️ Failed preloading ambient cache: {e}")

    def _persist_to_disk(self, key: str, data: bytes):
        if not self._enable_persistence:
            return
        try:
            # Enforce max entries: simple strategy - if exceeded, delete oldest file
            current_files = [f for f in os.listdir(self._cache_dir) if f.endswith('.bin')]
            if len(current_files) >= self._cache_max_entries:
                oldest = sorted(
                    (os.path.getmtime(os.path.join(self._cache_dir, f)), f) for f in current_files
                )[0][1]
                try:
                    os.unlink(os.path.join(self._cache_dir, oldest))
                except Exception:
                    pass
            # Write new file
            with open(self._cache_filename(key), 'wb') as fh:
                fh.write(data)
        except Exception as e:
            print(f"⚠️ Failed to persist ambient '{key}' to disk: {e}")
    
    async def search_ambient_sound(self, keywords: str, duration_limit: int = 30, max_retries: int = 2) -> Optional[Dict[str, Any]]:
        """
        Search for ambient sound on Freesound.org using keywords with retry logic
        Returns the highest rated sound that matches the criteria
        Reduced to 2 retries for faster failure recovery
        """
        if not self.freesound_api_key or len(self.freesound_api_key.strip()) == 0:
            print("⚠️ Freesound API key not configured, skipping ambient sound search")
            print("💡 Add FREESOUND_API_KEY to environment variables to enable ambient sounds")
            return None
        
        for attempt in range(max_retries):
            try:
                print(f"🔍 FreeSound search attempt {attempt + 1}/{max_retries}...")
                
                # Clean and prepare search query
                search_query = keywords.strip().replace(" ", "+")
                
                # Search parameters for ambient/background sounds  
                params = {
                    'query': f'{search_query} ambient background',
                    'filter': f'duration:[5.0 TO {duration_limit}.0] avg_rating:[4 TO 10]',
                    'sort': 'rating_desc',
                    'fields': 'id,name,url,previews,duration,avg_rating,download',
                    'page_size': 10,
                }
                
                # Use Authorization header instead of token parameter
                headers = {
                    'Authorization': f'Token {self.freesound_api_key}'
                }
                
                url = f"{self.freesound_base_url}/search/text/"
                
                # Use fresh session to avoid 'Connector is closed' errors with timeout
                timeout = aiohttp.ClientTimeout(total=10)  # Reduced from 15s to 10s
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, params=params, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            sounds = data.get('results', [])
                            
                            if sounds:
                                # Return the highest rated sound
                                best_sound = sounds[0]
                                print(f"🎵 Found ambient sound: {best_sound['name']} (rating: {best_sound.get('avg_rating', 'N/A')})")
                                return best_sound
                            else:
                                print(f"🔇 No ambient sounds found for '{keywords}'")
                                if attempt < max_retries - 1:
                                    print(f"⏱️ Retrying in 1 second...")
                                    await asyncio.sleep(1)  # Reduced from 2s to 1s
                                    continue
                                return None
                        else:
                            error_text = await response.text()
                            print(f"❌ Freesound API error: {response.status}")
                            print(f"   Error details: {error_text}")
                            if attempt < max_retries - 1:
                                print(f"⏱️ Retrying in 1 second...")
                                await asyncio.sleep(1)  # Reduced from 2s to 1s
                                continue
                            return None
                        
            except asyncio.TimeoutError:
                print(f"⏱️ FreeSound API timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Reduced from 2s to 1s
                    continue
                return None
            except Exception as e:
                print(f"❌ Error searching for ambient sound '{keywords}' (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Reduced from 2s to 1s
                    continue
                return None
        
        # All retries failed
        print(f"❌ All {max_retries} attempts to search FreeSound failed for '{keywords}'")
        return None
    
    async def _download_sound(self, sound_id: str, output_path: str) -> bool:
        """Download a sound file from Freesound"""
        try:
            download_url = f"https://freesound.org/apiv2/sounds/{sound_id}/download/"
            
            # Create a fresh session with proper headers for download
            # Prefer OAuth2 Bearer token when available for full downloads
            headers = {'User-Agent': 'StorytellerApp/1.0'}
            if hasattr(self, 'freesound_oauth_token') and self.freesound_oauth_token:
                headers['Authorization'] = f'Bearer {self.freesound_oauth_token}'
            else:
                headers['Authorization'] = f'Token {self.freesound_api_key}'
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    download_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
                ) as response:
                    if response.status == 200:
                        print(f"📥 Downloading sound {sound_id}...")
                        with open(output_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        print(f"✅ Downloaded sound to {output_path}")
                        return True
                    elif response.status == 401:
                        print(f"❌ Download failed: Invalid Freesound API key (401)")
                        print(f"💡 Check FREESOUND_API_KEY in environment variables")
                        return False
                    else:
                        error_text = await response.text()
                        print(f"❌ Download failed with status {response.status}")
                        print(f"📋 Error details: {error_text[:200]}...")
                        return False
                    
        except Exception as e:
            print(f"❌ Error downloading ambient sound: {e}")
            return False
    
    async def download_ambient_sound(self, sound_info: Dict[str, Any]) -> Optional[bytes]:
        """Download ambient sound from Freesound and return as bytes"""
        try:
            sound_id = str(sound_info.get('id', ''))
            if not sound_id:
                print("❌ No sound ID found in sound_info")
                return None
            
            # Create temporary file for download
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name
            # Use preview CDN URLs only (no OAuth/download attempts)
            previews = sound_info.get('previews', {}) if isinstance(sound_info.get('previews', {}), dict) else {}
            preview_url = previews.get('preview-hq-mp3') or previews.get('preview-hq-ogg') or previews.get('preview-lq-mp3')
            if not preview_url:
                print("� No preview URL available for this sound; cannot download without OAuth2 (skipping)")
                # Clean up temp file
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                return None

            print(f"📥 Downloading preview from CDN: {preview_url}")
            preview_success = await self._download_preview_url(preview_url, temp_path)
            if not preview_success:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                print("❌ Preview download failed")
                return None

            # Read the downloaded file as bytes
            with open(temp_path, 'rb') as f:
                audio_bytes = f.read()

            # Clean up temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

            print(f"✅ Successfully downloaded preview ambient sound: {len(audio_bytes)} bytes")
            return audio_bytes
                
        except Exception as e:
            print(f"❌ Error in download_ambient_sound: {e}")
            return None
    
    def mix_narration_with_ambient(self, narration_audio: bytes, ambient_audio: bytes, 
                                  ambient_volume: float = 0.12, fade_duration: int = 2000) -> bytes:
        """
        Mix narration audio with ambient background sound
        
        Args:
            narration_audio: Main narration audio (from Cartesia)
            ambient_audio: Background ambient sound (from Freesound)
            ambient_volume: Volume level for ambient sound (0.0 to 1.0) - default 0.12 for subtle background
            fade_duration: Fade in/out duration for ambient sound in milliseconds
        
        Returns:
            Mixed audio as bytes (opus encoded)
        """
        try:
            # Load audio segments
            narration = AudioSegment.from_file(io.BytesIO(narration_audio))
            ambient = AudioSegment.from_file(io.BytesIO(ambient_audio))
            
            # Normalize narration audio (ensure narration is clear and prominent)
            narration = normalize(narration)
            
            # Adjust ambient sound to be subtle but audible background
            ambient = normalize(ambient)
            # Reduce ambient volume for pleasant background ambience: -20dB to -26dB depending on ambient_volume setting
            # This ensures narration is clearly audible while ambient enhances the storytelling atmosphere
            volume_reduction_db = 20 + (6 * (1.0 - ambient_volume))  # Range: 20-26 dB reduction
            ambient = ambient - volume_reduction_db
            
            # Loop ambient sound to match narration duration if needed
            narration_duration = len(narration)
            if len(ambient) < narration_duration:
                # Loop the ambient sound to cover the entire narration
                loops_needed = (narration_duration // len(ambient)) + 1
                ambient = ambient * loops_needed
            
            # Trim ambient to match narration duration
            ambient = ambient[:narration_duration]
            
            # Add fade in/out to ambient sound for smooth, unobtrusive experience
            # Longer fade for more subtle ambient presence
            ambient = ambient.fade_in(fade_duration).fade_out(fade_duration)
            
            # Mix the audio tracks (ambient will be MUCH quieter than narration)
            mixed_audio = narration.overlay(ambient)
            
            # Apply gentle dynamic range compression to ensure consistent narration volume
            # But not too aggressive - we want natural storytelling feel
            mixed_audio = compress_dynamic_range(mixed_audio, threshold=-22.0, ratio=3.0)
            
            # Normalize final output
            mixed_audio = normalize(mixed_audio)
            
            # Export intermediate mix as WAV (lossless) so final export can control codec/format
            output_buffer = io.BytesIO()
            mixed_audio.export(output_buffer, format="wav")
            
            output_buffer.seek(0)
            result = output_buffer.read()
            
            print(f"✅ Mixed audio created: {len(result)} bytes (WAV format)")
            return result
            
        except Exception as e:
            print(f"❌ Error mixing audio: {str(e)}")
            # Return original narration if mixing fails
            return narration_audio

    async def _download_preview_url(self, preview_url: str, output_path: str, max_retries: int = 3) -> bool:
        """Download a preview URL (CDN) which does not require Freesound OAuth2 token with retry logic."""
        for attempt in range(max_retries):
            try:
                print(f"📥 Download attempt {attempt + 1}/{max_retries}...")
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(preview_url) as resp:
                        if resp.status == 200:
                            print(f"📥 Downloading preview from CDN...")
                            with open(output_path, 'wb') as fh:
                                async for chunk in resp.content.iter_chunked(8192):
                                    fh.write(chunk)
                            print(f"✅ Preview downloaded to {output_path}")
                            return True
                        else:
                            print(f"❌ Preview download failed with status {resp.status}")
                            if attempt < max_retries - 1:
                                print(f"⏱️ Retrying in 1 second...")
                                await asyncio.sleep(1)
                                continue
                            return False
            except asyncio.TimeoutError:
                print(f"⏱️ Download timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return False
            except Exception as e:
                print(f"❌ Error downloading preview URL (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return False
        
        print(f"❌ All {max_retries} download attempts failed")
        return False
    
    def enhance_storytelling_audio(self, audio_data: bytes) -> bytes:
        """
        Apply audio processing to make the mixed audio sound more like a professional story narration
        """
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_data))
            
            # Apply storytelling enhancements
            # 1. Add subtle reverb effect by layering slightly delayed and quieter version
            delayed_audio = audio - 15  # Reduce volume by 15dB
            delayed_audio = delayed_audio._spawn(delayed_audio.raw_data[100:])  # 100ms delay
            audio = audio.overlay(delayed_audio)
            
            # 2. Dynamic range compression for consistent volume
            # Gentler compression to maintain natural storytelling dynamics
            audio = compress_dynamic_range(audio, threshold=-20.0, ratio=2.5, attack=5.0, release=50.0)
            
            # 3. Final normalization
            audio = normalize(audio)
            
            # 4. Export with storytelling-optimized settings as OGG/Opus for efficient web delivery
            output_buffer = io.BytesIO()
            # Use libopus for high-quality Opus encoding inside an OGG container
            # Requires: ffmpeg with opus support (install: apt-get install ffmpeg opus-tools libopus0)
            audio.export(output_buffer, format="ogg", codec="libopus", bitrate="64k")
            
            output_buffer.seek(0)
            result = output_buffer.read()
            
            print(f"✅ Enhanced storytelling audio: {len(result)} bytes (OGG/Opus format)")
            return result
            
        except Exception as e:
            print(f"❌ Error enhancing storytelling audio: {str(e)}")
            return audio_data
    
    async def process_scene_audio(self, narration_audio: bytes, ambient_keywords: str, 
                                scene_number: int) -> bytes:
        """
        Complete pipeline: fetch ambient sound, mix with narration, and enhance for storytelling.
        Uses caching to avoid re-downloading the same ambient sound for multiple scenes.
        """
        print(f"🎬 AudioMixerService.process_scene_audio START for scene {scene_number}")
        print(f"🌿 Ambient keywords received: '{ambient_keywords}' (type: {type(ambient_keywords)})")
        print(f"🎤 Narration audio size: {len(narration_audio)} bytes")
        
        if not ambient_keywords or not ambient_keywords.strip():
            print("⚠️ No ambient keywords provided, using narration only")
            return self.enhance_storytelling_audio(narration_audio) if self._enable_enhancement else narration_audio
        
        try:
            # Check cache first (with lock to prevent race condition)
            cache_key = ambient_keywords.strip().lower()
            
            # Fast path: check cache without lock first
            # Global bed reuse override
            if self._reuse_single_bed and self._global_bed_key in self._ambient_cache:
                print(f"🔁 Reusing global ambient bed for scene {scene_number}")
                ambient_audio = self._ambient_cache[self._global_bed_key]
            elif cache_key in self._ambient_cache:
                print(f"💾 Using cached ambient sound for '{ambient_keywords}'")
                ambient_audio = self._ambient_cache[cache_key]
            else:
                # Slow path: acquire lock and check again (double-check locking pattern)
                async with self.cache_lock:
                    # Check again in case another task just downloaded it
                    if self._reuse_single_bed and self._global_bed_key in self._ambient_cache:
                        print(f"🔁 Using global ambient bed for '{ambient_keywords}' (post-lock)")
                        ambient_audio = self._ambient_cache[self._global_bed_key]
                    elif cache_key in self._ambient_cache:
                        print(f"💾 Using cached ambient sound for '{ambient_keywords}' (acquired after lock)")
                        ambient_audio = self._ambient_cache[cache_key]
                    else:
                        # Step 1 & 2: Search and download with overall timeout (60s max)
                        try:
                            print(f"🔍 Step 1: Searching for ambient sound with keywords: '{ambient_keywords}'")
                            
                            # Wrap search + download in overall timeout to prevent long delays
                            async def search_and_download():
                                sound_info = await self.search_ambient_sound(ambient_keywords)
                                if not sound_info:
                                    return None
                                print(f"✅ Step 1 SUCCESS: Found ambient sound: '{sound_info.get('name', 'Unknown')}' (ID: {sound_info.get('id', 'N/A')})")
                                
                                print(f"📥 Step 2: Downloading ambient sound...")
                                ambient_audio = await self.download_ambient_sound(sound_info)
                                if not ambient_audio:
                                    return None
                                print(f"✅ Step 2 SUCCESS: Downloaded ambient audio ({len(ambient_audio)} bytes)")
                                return ambient_audio
                            
                            # Apply 60s timeout to entire search + download process
                            ambient_audio = await asyncio.wait_for(search_and_download(), timeout=60)
                            
                            if not ambient_audio:
                                print("🔇 No ambient sound found or downloaded, using narration only")
                                return self.enhance_storytelling_audio(narration_audio)
                            
                            # Cache the downloaded ambient sound
                            # Cache logic (store both specific key and optionally global)
                            self._ambient_cache[cache_key] = ambient_audio
                            if self._reuse_single_bed and self._global_bed_key not in self._ambient_cache:
                                self._ambient_cache[self._global_bed_key] = ambient_audio
                                print(f"🔁 Set global ambient bed from '{ambient_keywords}'")
                            print(f"💾 Cached ambient sound for '{ambient_keywords}'")
                            self._persist_to_disk(cache_key, ambient_audio)
                            
                        except asyncio.TimeoutError:
                            print(f"⏱️ Ambient sound search/download timed out after 60s, using narration only")
                            return self.enhance_storytelling_audio(narration_audio)
            
            # Step 3: Mix narration with ambient sound (with timeout to prevent hangs)
            print(f"🎵 Step 3: Mixing narration with ambient sound...")
            try:
                # Run mixing in executor to avoid blocking and add timeout
                loop = get_or_create_event_loop()
                mixed_audio = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, 
                        self.mix_narration_with_ambient, 
                        narration_audio, 
                        ambient_audio
                    ),
                    timeout=15  # 15 second timeout for mixing (reduced from 30s)
                )
                print(f"✅ Step 3 SUCCESS: Mixed audio created ({len(mixed_audio)} bytes)")
            except asyncio.TimeoutError:
                print(f"⏱️ Step 3 TIMEOUT: Mixing took too long (>15s), using narration only")
                return self.enhance_storytelling_audio(narration_audio) if self._enable_enhancement else narration_audio
            except Exception as mix_error:
                print(f"❌ Step 3 FAILED: Mixing error: {mix_error}, using narration only")
                return self.enhance_storytelling_audio(narration_audio) if self._enable_enhancement else narration_audio
            
            # Step 4: Apply storytelling enhancements (with timeout)
            print(f"✨ Step 4: Applying storytelling enhancements...")
            try:
                loop = get_or_create_event_loop()
                if self._enable_enhancement:
                    final_audio = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            self.enhance_storytelling_audio,
                            mixed_audio
                        ),
                        timeout=15
                    )
                    print(f"✅ COMPLETE: Scene {scene_number} ambient audio processing finished ({len(final_audio)} bytes)")
                    return final_audio
                else:
                    print(f"🚫 Enhancement disabled; returning mixed audio for scene {scene_number}")
                    return mixed_audio
            except asyncio.TimeoutError:
                if self._enable_enhancement:
                    print(f"⏱️ Step 4 TIMEOUT: Enhancement took too long (>15s), using mixed audio")
                return mixed_audio
            except Exception as enhance_error:
                if self._enable_enhancement:
                    print(f"⚠️ Step 4 WARNING: Enhancement error: {enhance_error}, using mixed audio")
                return mixed_audio
            
        except Exception as e:
            print(f"❌ Error processing scene audio: {str(e)}")
            return self.enhance_storytelling_audio(narration_audio) if self._enable_enhancement else narration_audio

# Global instance  
audio_mixer_service = AudioMixerService()