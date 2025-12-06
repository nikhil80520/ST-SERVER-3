# ===== app/utils/helpers.py =====
import tempfile
import os
import subprocess
import json
from typing import Optional


def calculate_audio_duration(text: str) -> int:
    """Estimate audio duration in milliseconds based on text length"""
    # Approximate: 150 words per minute, average 5 characters per word
    words = len(text) / 5
    duration_minutes = words / 150
    return int(duration_minutes * 60 * 1000)


def get_audio_duration_from_file(audio_data: bytes) -> Optional[int]:
    """
    Extract actual audio duration from audio file using ffprobe
    
    Args:
        audio_data: Audio file bytes (any format supported by ffmpeg)
        
    Returns:
        Duration in milliseconds, or None if extraction fails
    """
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.audio') as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name
        
        try:
            # Use ffprobe to get duration
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                temp_path
            ]
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            if result.returncode == 0:
                info = json.loads(result.stdout)
                
                # Extract duration from format section
                if 'format' in info and 'duration' in info['format']:
                    duration_seconds = float(info['format']['duration'])
                    duration_ms = int(duration_seconds * 1000)
                    print(f"🎵 Audio duration extracted: {duration_ms}ms ({duration_seconds:.2f}s)")
                    return duration_ms
            
            print(f"⚠️ Could not extract audio duration from file")
            return None
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except OSError:
                pass
                
    except FileNotFoundError:
        print(f"⚠️ ffprobe not found - cannot extract audio duration")
        return None
    except Exception as e:
        print(f"⚠️ Error extracting audio duration: {str(e)}")
        return None
