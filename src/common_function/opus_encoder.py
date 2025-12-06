"""
Opus OGG Audio Encoder
=====================
Utility for encoding audio to Opus OGG format with optimal settings for web delivery
"""

import io
import subprocess
import tempfile
import os
import hashlib
from typing import Optional, Tuple
from datetime import datetime


class OpusEncoder:
    """Opus OGG encoder with optimized settings for Firebase storage and web delivery"""
    
    # Opus encoding settings optimized for voice content
    SAMPLE_RATE = 16000      # 16kHz - optimal for voice
    CHANNELS = 1             # Mono
    BITRATE = 16             # 16 kbps - very efficient for voice
    
    @staticmethod
    def encode_to_opus(audio_data: bytes, source_format: str = "auto") -> Tuple[bytes, str]:
        """
        Encode audio data to Opus OGG format
        
        Args:
            audio_data: Raw audio bytes (WAV, MP3, etc.)
            source_format: Source format hint ('wav', 'mp3', 'auto')
            
        Returns:
            Tuple of (opus_ogg_bytes, content_hash) for version tracking
        """
        try:
            print(f"🎵 Encoding to Opus OGG: {len(audio_data)} bytes input")
            
            # Generate content hash for versioning
            content_hash = OpusEncoder._generate_content_hash(audio_data)
            
            # Convert using ffmpeg
            opus_data = OpusEncoder._convert_with_ffmpeg(audio_data, source_format)
            
            if opus_data:
                compression_ratio = len(audio_data) / len(opus_data)
                print(f"✅ Opus encoding successful:")
                print(f"   📊 {len(audio_data)} → {len(opus_data)} bytes")
                print(f"   📈 Compression: {compression_ratio:.1f}x smaller")
                print(f"   🏷️ Content hash: {content_hash[:8]}...")
                print(f"   🎛️ Settings: {OpusEncoder.SAMPLE_RATE}Hz, {OpusEncoder.CHANNELS}ch, {OpusEncoder.BITRATE}kbps")
                return opus_data, content_hash
            else:
                raise Exception("ffmpeg conversion failed")
                
        except Exception as e:
            print(f"❌ Opus encoding failed: {str(e)}")
            print(f"⚠️ Falling back to original audio format")
            # Return original data with hash
            content_hash = OpusEncoder._generate_content_hash(audio_data)
            return audio_data, content_hash
    
    @staticmethod
    def _convert_with_ffmpeg(audio_data: bytes, source_format: str) -> Optional[bytes]:
        """
        Convert audio to Opus OGG using ffmpeg
        
        Args:
            audio_data: Input audio bytes
            source_format: Source format hint
            
        Returns:
            Opus OGG bytes or None if conversion fails
        """
        try:
            # Determine input file extension
            if source_format == "auto":
                if audio_data.startswith(b'RIFF') and b'WAVE' in audio_data[:12]:
                    input_ext = '.wav'
                elif audio_data.startswith(b'ID3') or audio_data.startswith(b'\xff\xfb'):
                    input_ext = '.mp3'
                else:
                    input_ext = '.wav'  # Default assumption
            else:
                input_ext = f'.{source_format}'
            
            # Create temporary files
            with tempfile.NamedTemporaryFile(delete=False, suffix=input_ext) as input_file:
                input_file.write(audio_data)
                input_path = input_file.name
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as output_file:
                output_path = output_file.name
            
            try:
                # Build ffmpeg command for Opus encoding
                cmd = [
                    'ffmpeg',
                    '-i', input_path,
                    '-c:a', 'libopus',                    # Use Opus codec
                    '-ar', str(OpusEncoder.SAMPLE_RATE),  # Sample rate: 16kHz
                    '-ac', str(OpusEncoder.CHANNELS),     # Channels: Mono
                    '-b:a', f'{OpusEncoder.BITRATE}k',    # Bitrate: 16kbps
                    '-vbr', 'on',                         # Variable bitrate for efficiency
                    '-compression_level', '10',           # Maximum compression
                    '-application', 'voip',               # Optimize for voice
                    '-cutoff', '8000',                    # Low-pass filter at 8kHz
                    '-y',                                 # Overwrite output
                    output_path
                ]
                
                print(f"🔧 Running ffmpeg: {' '.join(cmd[1:6])}...")
                
                # Execute ffmpeg with timeout
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=60,  # 60 second timeout
                    check=False  # Don't raise exception on non-zero exit
                )
                
                if result.returncode == 0:
                    # Read the converted Opus file
                    with open(output_path, 'rb') as f:
                        opus_data = f.read()
                    
                    if len(opus_data) > 0:
                        return opus_data
                    else:
                        print(f"❌ ffmpeg produced empty output")
                        return None
                else:
                    print(f"❌ ffmpeg failed with return code {result.returncode}")
                    print(f"   stderr: {result.stderr[:200]}...")
                    return None
                    
            finally:
                # Clean up temporary files
                try:
                    os.unlink(input_path)
                    os.unlink(output_path)
                except OSError:
                    pass  # Ignore cleanup errors
                    
        except subprocess.TimeoutExpired:
            print(f"❌ ffmpeg timeout - conversion took too long")
            return None
        except FileNotFoundError:
            print(f"❌ ffmpeg not found - install ffmpeg to enable Opus encoding")
            return None
        except Exception as e:
            print(f"❌ ffmpeg conversion error: {str(e)}")
            return None
    
    @staticmethod
    def _generate_content_hash(audio_data: bytes) -> str:
        """
        Generate a content hash for filename versioning
        
        Args:
            audio_data: Audio bytes to hash
            
        Returns:
            Hex string hash (first 8 characters for filename use)
        """
        return hashlib.sha256(audio_data).hexdigest()[:8]
    
    @staticmethod
    def create_versioned_filename(base_name: str, content_hash: str, extension: str = "ogg") -> str:
        """
        Create a versioned filename with content hash
        
        Args:
            base_name: Base filename (e.g., "scene_1", "lesson_1")
            content_hash: Content hash from encode_to_opus
            extension: File extension (default: "ogg")
            
        Returns:
            Versioned filename (e.g., "scene_1-a1b2c3d4.ogg")
        """
        return f"{base_name}-{content_hash}.{extension}"
    
    @staticmethod
    def is_ffmpeg_available() -> bool:
        """
        Check if ffmpeg is available in the system
        
        Returns:
            True if ffmpeg is available, False otherwise
        """
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'], 
                capture_output=True, 
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    @staticmethod
    def get_opus_info(opus_data: bytes) -> dict:
        """
        Get information about Opus OGG file
        
        Args:
            opus_data: Opus OGG bytes
            
        Returns:
            Dictionary with file information
        """
        try:
            # Create temporary file to analyze
            with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as temp_file:
                temp_file.write(opus_data)
                temp_path = temp_file.name
            
            try:
                # Use ffprobe to get file info
                cmd = [
                    'ffprobe',
                    '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_format',
                    '-show_streams',
                    temp_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    import json
                    info = json.loads(result.stdout)
                    
                    # Extract relevant information
                    if 'streams' in info and len(info['streams']) > 0:
                        stream = info['streams'][0]
                        return {
                            'codec': stream.get('codec_name', 'unknown'),
                            'sample_rate': int(stream.get('sample_rate', 0)),
                            'channels': int(stream.get('channels', 0)),
                            'bitrate': int(stream.get('bit_rate', 0)),
                            'duration': float(stream.get('duration', 0)),
                            'size_bytes': len(opus_data)
                        }
                
                return {'error': 'Could not analyze Opus file'}
                
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
                    
        except Exception as e:
            return {'error': str(e)}


# Test function for development
def test_opus_encoding():
    """Test function to verify Opus encoding works"""
    print("🧪 Testing Opus encoding...")
    
    # Check if ffmpeg is available
    if not OpusEncoder.is_ffmpeg_available():
        print("❌ ffmpeg not available - Opus encoding will not work")
        return False
    
    # Create a simple test WAV file (1 second of silence)
    import wave
    import struct
    
    sample_rate = 22050
    duration = 1.0  # 1 second
    amplitude = 16383
    samples = int(sample_rate * duration)
    
    # Generate silence
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # Write silence
        for _ in range(samples):
            wav_file.writeframes(struct.pack('<h', 0))
    
    test_audio = wav_buffer.getvalue()
    print(f"📝 Created test WAV: {len(test_audio)} bytes")
    
    # Test Opus encoding
    try:
        opus_data, content_hash = OpusEncoder.encode_to_opus(test_audio, 'wav')
        
        if len(opus_data) > 0:
            print(f"✅ Opus encoding test successful!")
            print(f"   📊 WAV: {len(test_audio)} bytes → Opus: {len(opus_data)} bytes")
            print(f"   🏷️ Content hash: {content_hash}")
            
            # Test versioned filename
            filename = OpusEncoder.create_versioned_filename("test_audio", content_hash)
            print(f"   📁 Versioned filename: {filename}")
            
            # Get Opus info
            info = OpusEncoder.get_opus_info(opus_data)
            print(f"   📋 Opus info: {info}")
            
            return True
        else:
            print("❌ Opus encoding test failed - empty output")
            return False
            
    except Exception as e:
        print(f"❌ Opus encoding test failed: {str(e)}")
        return False


if __name__ == "__main__":
    test_opus_encoding()
