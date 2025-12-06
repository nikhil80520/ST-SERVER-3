"""
Audio Processing Utilities
==========================
Utilities for normalizing audio format, volume, and headers for ESP32 compatibility
Enhanced with Opus OGG encoding for web delivery optimization
"""

import io
import wave
import struct
import tempfile
import os
from typing import Tuple, Optional


class AudioProcessor:
    """Audio processing utilities for TTS services and web delivery"""
    
    @staticmethod
    def process_for_web_delivery(audio_data: bytes, source_format: str = "auto") -> Tuple[bytes, str, str]:
        """
        Process audio for optimal web delivery using Opus OGG
        
        Args:
            audio_data: Raw audio bytes
            source_format: Source format ('mp3', 'wav', 'opus', 'auto')
            
        Returns:
            Tuple of (processed_audio_bytes, content_type, content_hash)
        """
        try:
            import hashlib
            
            print(f"🌐 Processing audio for web delivery: {len(audio_data)} bytes")
            
            # Check if audio is already Opus/OGG format (magic bytes: 'OggS')
            if audio_data.startswith(b'OggS'):
                print(f"✅ Audio is already in Opus/OGG format, skipping re-encoding")
                content_hash = hashlib.sha256(audio_data).hexdigest()[:8]
                return audio_data, "audio/opus", content_hash
            
            from app.utils.opus_encoder import OpusEncoder
            
            # Encode to Opus OGG for optimal web delivery
            opus_data, content_hash = OpusEncoder.encode_to_opus(audio_data, source_format)
            
            # Determine content type based on actual output
            if opus_data.startswith(b'OggS'):  # Opus OGG magic bytes
                content_type = "audio/opus"  # Use audio/opus for better compatibility
                print(f"✅ Audio processed as Opus for web delivery")
            else:
                # Fallback to original format detection
                if audio_data.startswith(b'RIFF') and b'WAVE' in audio_data[:12]:
                    content_type = "audio/wav"
                elif audio_data.startswith(b'ID3') or audio_data.startswith(b'\xff\xfb'):
                    content_type = "audio/mpeg"
                else:
                    content_type = "audio/wav"  # Default
                print(f"⚠️ Using fallback format: {content_type}")
            
            return opus_data, content_type, content_hash
            
        except ImportError:
            print(f"⚠️ Opus encoder not available, using original format")
            # Fallback to original processing
            if audio_data.startswith(b'RIFF') and b'WAVE' in audio_data[:12]:
                content_type = "audio/wav"
            elif audio_data.startswith(b'ID3') or audio_data.startswith(b'\xff\xfb'):
                content_type = "audio/mpeg"
            else:
                content_type = "audio/wav"
            
            # Generate simple hash for fallback
            import hashlib
            content_hash = hashlib.sha256(audio_data).hexdigest()[:8]
            
            return audio_data, content_type, content_hash
        except Exception as e:
            print(f"❌ Web delivery processing failed: {str(e)}")
            # Return original with basic content type detection
            content_type = "audio/wav"  # Safe default
            import hashlib
            content_hash = hashlib.sha256(audio_data).hexdigest()[:8]
            return audio_data, content_type, content_hash
    
    @staticmethod
    def normalize_audio_for_esp32(audio_data: bytes, source_format: str = "auto", 
                                target_volume_gain: float = 1.5) -> bytes:
        """
        Normalize audio data for ESP32 compatibility
        
        Args:
            audio_data: Raw audio bytes
            source_format: Source format ('mp3', 'wav', 'auto')
            target_volume_gain: Volume multiplier (default: 1.5 for 50% louder)
            
        Returns:
            Normalized WAV audio bytes with ESP32-compatible headers
        """
        try:
            # Check if it's already WAV format
            if AudioProcessor._is_wav_format(audio_data):
                print("🔧 Processing WAV audio for ESP32 compatibility...")
                return AudioProcessor._process_wav_for_esp32(audio_data, target_volume_gain)
            else:
                # Handle MP3 or other formats - convert to ESP32-compatible WAV
                print("🔧 Converting MP3/other format to ESP32-compatible WAV...")
                return AudioProcessor._convert_to_esp32_wav(audio_data, target_volume_gain)
            
        except Exception as e:
            print(f"❌ Audio normalization failed: {str(e)}")
            # Fallback: return original data
            return audio_data
    
    @staticmethod
    def _is_wav_format(audio_data: bytes) -> bool:
        """Check if audio data is WAV format"""
        return audio_data.startswith(b'RIFF') and b'WAVE' in audio_data[:12]
    
    @staticmethod
    def _convert_to_esp32_wav(audio_data: bytes, volume_gain: float = 1.5) -> bytes:
        """
        Convert MP3 or other format to ESP32-compatible WAV
        Uses ffmpeg command-line tool if available, otherwise returns original data
        """
        try:
            import subprocess
            import tempfile
            import os
            
            # Create temporary files
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as input_file:
                input_file.write(audio_data)
                input_path = input_file.name
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as output_file:
                output_path = output_file.name
            
            try:
                # Use ffmpeg to convert MP3 to ESP32-compatible WAV
                # ESP32 specs: 16-bit PCM, mono, with volume boost
                cmd = [
                    'ffmpeg',
                    '-i', input_path,
                    '-ar', '22050',  # 22050 Hz sample rate (good for ESP32)
                    '-ac', '1',      # Mono channel
                    '-sample_fmt', 's16',  # 16-bit signed integer
                    '-af', f'volume={volume_gain}',  # Volume boost
                    '-y',            # Overwrite output file
                    output_path
                ]
                
                # Run ffmpeg with error capture
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                
                if result.returncode == 0:
                    # Read the converted WAV file
                    with open(output_path, 'rb') as f:
                        converted_data = f.read()
                    
                    print(f"🔧 MP3 converted to ESP32 WAV: {len(audio_data)} → {len(converted_data)} bytes")
                    print(f"   📊 22050Hz, Mono, 16-bit PCM, Volume: {volume_gain}x")
                    
                    return converted_data
                else:
                    print(f"❌ ffmpeg conversion failed: {result.stderr}")
                    return audio_data
                    
            finally:
                # Clean up temporary files
                try:
                    os.unlink(input_path)
                    os.unlink(output_path)
                except:
                    pass
                    
        except (ImportError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            print(f"⚠️ ffmpeg not available ({str(e)}), using basic conversion...")
            # Fallback: create a simple WAV wrapper (won't actually convert MP3)
            return AudioProcessor._create_basic_wav_wrapper(audio_data, volume_gain)
        except Exception as e:
            print(f"❌ Audio conversion failed: {str(e)}")
            return audio_data
    
    @staticmethod
    def _create_basic_wav_wrapper(audio_data: bytes, volume_gain: float = 1.5) -> bytes:
        """
        Create a basic WAV wrapper for compatibility
        Note: This doesn't actually convert MP3, just adds WAV headers
        """
        try:
            # Create a basic WAV header for the data
            # This is a simplified approach that may not work perfectly with MP3 data
            sample_rate = 22050
            channels = 1
            bits_per_sample = 16
            
            wav_header = AudioProcessor._create_wav_header(
                len(audio_data), sample_rate, channels, bits_per_sample
            )
            
            print(f"🔧 Created basic WAV wrapper: {len(audio_data)} bytes + header")
            return wav_header + audio_data
            
        except Exception as e:
            print(f"❌ WAV wrapper creation failed: {str(e)}")
            return audio_data
    
    @staticmethod
    def _create_wav_header(data_size: int, sample_rate: int, channels: int, bits_per_sample: int) -> bytes:
        """Create WAV file header"""
        import struct
        
        # WAV header structure
        header = b'RIFF'
        header += struct.pack('<I', data_size + 36)  # File size - 8
        header += b'WAVE'
        header += b'fmt '
        header += struct.pack('<I', 16)  # Subchunk1Size
        header += struct.pack('<H', 1)   # AudioFormat (PCM)
        header += struct.pack('<H', channels)
        header += struct.pack('<I', sample_rate)
        header += struct.pack('<I', sample_rate * channels * bits_per_sample // 8)  # ByteRate
        header += struct.pack('<H', channels * bits_per_sample // 8)  # BlockAlign
        header += struct.pack('<H', bits_per_sample)
        header += b'data'
        header += struct.pack('<I', data_size)
        
        return header
    
    @staticmethod
    def _process_wav_for_esp32(wav_data: bytes, volume_gain: float = 1.5) -> bytes:
        """
        Process WAV data for ESP32 compatibility and amplify volume
        
        Args:
            wav_data: WAV audio bytes
            volume_gain: Volume multiplier
            
        Returns:
            Processed WAV bytes
        """
        try:
            # Read WAV file
            wav_input = wave.open(io.BytesIO(wav_data), 'rb')
            
            # Get audio parameters
            channels = wav_input.getnchannels()
            sample_width = wav_input.getsampwidth()
            frame_rate = wav_input.getframerate()
            frames = wav_input.getnframes()
            
            # Read audio data
            audio_frames = wav_input.readframes(frames)
            wav_input.close()
            
            # Amplify volume if needed
            if volume_gain != 1.0:
                audio_frames = AudioProcessor._amplify_audio(audio_frames, sample_width, volume_gain)
            
            # Create output WAV with ESP32-compatible settings
            output_buffer = io.BytesIO()
            
            # Ensure ESP32-compatible settings:
            # - Keep original sample rate (usually 24000 from OpenAI or 44100 from Cartesia)
            # - Ensure 16-bit depth
            # - Mono channel preferred for ESP32
            target_channels = 1  # Mono for ESP32
            target_sample_width = 2  # 16-bit
            
            with wave.open(output_buffer, 'wb') as wav_output:
                wav_output.setnchannels(target_channels)
                wav_output.setsampwidth(target_sample_width)
                wav_output.setframerate(frame_rate)  # Keep original frame rate
                
                # Convert stereo to mono if needed
                if channels == 2 and target_channels == 1:
                    audio_frames = AudioProcessor._stereo_to_mono(audio_frames, sample_width)
                
                # Convert bit depth if needed
                if sample_width != target_sample_width:
                    audio_frames = AudioProcessor._convert_bit_depth(audio_frames, sample_width, target_sample_width)
                
                wav_output.writeframes(audio_frames)
            
            processed_data = output_buffer.getvalue()
            
            print(f"🔧 WAV processed for ESP32: {len(wav_data)} → {len(processed_data)} bytes")
            print(f"   📊 {frame_rate}Hz, {target_channels}ch, {target_sample_width*8}bit")
            print(f"   🔊 Volume gain: {volume_gain}x")
            
            return processed_data
            
        except Exception as e:
            print(f"❌ WAV processing failed: {str(e)}")
            return wav_data
    
    @staticmethod
    def _amplify_audio(audio_data: bytes, sample_width: int, gain: float) -> bytes:
        """Amplify audio volume"""
        try:
            if sample_width == 2:  # 16-bit
                # Convert to 16-bit signed integers
                samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
                # Amplify and clamp
                amplified = []
                for sample in samples:
                    new_sample = int(sample * gain)
                    # Clamp to 16-bit range
                    new_sample = max(-32768, min(32767, new_sample))
                    amplified.append(new_sample)
                # Convert back to bytes
                return struct.pack('<' + 'h' * len(amplified), *amplified)
            else:
                # For other bit depths, return original
                return audio_data
        except Exception as e:
            print(f"❌ Audio amplification failed: {str(e)}")
            return audio_data
    
    @staticmethod
    def _stereo_to_mono(audio_data: bytes, sample_width: int) -> bytes:
        """Convert stereo audio to mono"""
        try:
            if sample_width == 2:  # 16-bit
                samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
                # Average every two samples (left and right channels)
                mono_samples = []
                for i in range(0, len(samples), 2):
                    if i + 1 < len(samples):
                        mono_sample = (samples[i] + samples[i + 1]) // 2
                    else:
                        mono_sample = samples[i]
                    mono_samples.append(mono_sample)
                return struct.pack('<' + 'h' * len(mono_samples), *mono_samples)
            else:
                return audio_data
        except Exception as e:
            print(f"❌ Stereo to mono conversion failed: {str(e)}")
            return audio_data
    
    @staticmethod
    def _convert_bit_depth(audio_data: bytes, from_width: int, to_width: int) -> bytes:
        """Convert audio bit depth"""
        if from_width == to_width:
            return audio_data
        
        # For now, only handle 16-bit output
        if to_width == 2:  # Convert to 16-bit
            return audio_data  # Assume it's already compatible
        
        return audio_data
    
    @staticmethod
    def create_esp32_compatible_wav(pcm_data: bytes, sample_rate: int = 22050, 
                                  channels: int = 1, sample_width: int = 2,
                                  volume_gain: float = 1.5) -> bytes:
        """
        Create ESP32-compatible WAV file with proper headers
        
        Args:
            pcm_data: Raw PCM audio data
            sample_rate: Sample rate in Hz (default: 22050)
            channels: Number of channels (default: 1 for mono)
            sample_width: Sample width in bytes (default: 2 for 16-bit)
            volume_gain: Volume multiplier
            
        Returns:
            WAV file bytes with proper headers
        """
        try:
            # Amplify PCM data if needed
            if volume_gain != 1.0:
                pcm_data = AudioProcessor._amplify_audio(pcm_data, sample_width, volume_gain)
            
            # Create WAV file in memory
            output_buffer = io.BytesIO()
            
            with wave.open(output_buffer, 'wb') as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm_data)
            
            wav_bytes = output_buffer.getvalue()
            
            print(f"🎵 ESP32 WAV created: {len(wav_bytes)} bytes")
            print(f"   📊 {sample_rate}Hz, {channels}ch, {sample_width*8}bit")
            print(f"   🔊 Volume: {volume_gain}x")
            
            return wav_bytes
            
        except Exception as e:
            print(f"❌ ESP32 WAV creation failed: {str(e)}")
            return pcm_data
