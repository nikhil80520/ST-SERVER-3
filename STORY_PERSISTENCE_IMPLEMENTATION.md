# Story Generation Persistence Pipeline - Complete Implementation

## Overview

This document describes the complete story-generation saving pipeline that stores all generated content (metadata, scenes, images, audio) in the correct PostgreSQL database tables and uploads all media files to the S3 bucket `june_story`.

## Database Models

The implementation uses the following SQLModel classes (exact field names preserved):

### Story
```python
- story_id: int (PK, auto-increment)
- user_id: int (FK → user.user_id)
- child_id: int (FK → child.child_id)
- title: str
- genre: Optional[str]
- story_length: Optional[str]
- thumbnail_url: Optional[str]
- duration: Optional[int]
- target_scenes: Optional[int]
- age_group: Optional[str]
- child_name: Optional[str]
- child_age: Optional[int]
- story_theme: Optional[str]
- moral_lesson: Optional[str]
- morals: Optional[str]
- target_emotion: Optional[str]
- art_style: Optional[str]
- ambient_sound: Optional[str]
- thumbnail_prompt: Optional[str]
- parent_context: Optional[str]
- created_at, updated_at
```

### StoryScene
```python
- story_scene_id: int (PK, auto-increment)
- story_id: int (FK → story.story_id)
- scene_number: int
- includes_child: bool
- emotion: Optional[str]
- reference_image_ids: Optional[List[str]]  # JSON array
- created_at, updated_at
```

### StorySceneImage
```python
- story_scene_image_id: int (PK, auto-increment)
- story_scene_id: int (FK → story_scene.story_scene_id)
- text: Optional[str]  # Scene narration text
- visual_prompt: Optional[str]
- image_url: Optional[str]  # S3 URL
- image_type: Optional[str]  # 'scene', 'thumbnail', etc.
- created_at, updated_at
```

### StorySceneAudio
```python
- story_scene_audio_id: int (PK, auto-increment)
- story_scene_id: int (FK → story_scene.story_scene_id)
- text: Optional[str]  # Audio narration text
- audio_url: Optional[str]  # S3 URL
- audio_type: Optional[str]  # 'narration', 'background', 'effects'
- duration: Optional[int]  # Duration in seconds
- created_at, updated_at
```

## Implementation: StoryPersistenceService

### File: `src/story/story_persistence_service.py`

#### Initialization
```python
def __init__(self):
    self.s3_client = get_s3_client()
    self.bucket_name = get_s3_bucket_name() or "june_story"
```

### Method 1: `save_complete_story()` - Full Pipeline with S3 Uploads

**Use Case**: When you have raw binary data (bytes) for all media that needs to be uploaded

**Signature**:
```python
async def save_complete_story(
    db: AsyncSession,
    user_id: int,
    child_id: int,
    story_data: Dict,
    thumbnail_data: Optional[bytes] = None,
    scene_images_data: Optional[List[bytes]] = None,
    scene_audio_data: Optional[List[bytes]] = None
) -> Story
```

**Pipeline Steps**:

1. **Create Story Record**
   ```python
   story = Story(
       user_id=user_id,
       child_id=child_id,
       title=story_data.get('title'),
       genre=story_data.get('genre'),
       ...
   )
   db.add(story)
   await db.flush()  # Get story_id
   ```

2. **Upload Thumbnail to S3**
   ```python
   if thumbnail_data:
       thumbnail_url = await self.upload_to_s3(
           file_data=thumbnail_data,
           key=f"stories/{story_uuid}/thumbnail.png",
           content_type='image/png'
       )
       story.thumbnail_url = thumbnail_url
   ```

3. **For Each Scene**:
   
   a. **Create StoryScene** (metadata only):
   ```python
   story_scene = StoryScene(
       story_id=story_id,
       scene_number=scene_number,
       includes_child=scene_data.get('includes_child'),
       emotion=scene_data.get('emotion'),
       reference_image_ids=scene_data.get('reference_image_ids', [])
   )
   db.add(story_scene)
   await db.flush()  # Get story_scene_id
   ```
   
   b. **Upload Scene Image** and create StorySceneImage:
   ```python
   if scene_images_data[idx]:
       image_url = await self.upload_to_s3(
           file_data=scene_images_data[idx],
           key=f"stories/{uuid}/scenes/scene_{scene_number:03d}.png",
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
   ```
   
   c. **Upload Scene Audio** and create StorySceneAudio:
   ```python
   if scene_audio_data[idx]:
       audio_url = await self.upload_to_s3(
           file_data=scene_audio_data[idx],
           key=f"stories/{uuid}/audio/scene_{scene_number:03d}.mp3",
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
   ```

4. **Commit Transaction**
   ```python
   await db.commit()
   await db.refresh(story)
   return story
   ```

### Method 2: `save_story_from_urls()` - Save with Pre-Uploaded Media

**Use Case**: When media is already uploaded and you have URLs

**Signature**:
```python
async def save_story_from_urls(
    db: AsyncSession,
    user_id: int,
    child_id: int,
    story_data: Dict  # Contains thumbnail_url, scenes with image_url/audio_url
) -> Story
```

**What it does**:
- Creates Story, StoryScene, StorySceneImage, StorySceneAudio records
- Uses URLs from `story_data` instead of uploading
- Useful when media is uploaded separately (e.g., via existing upload pipeline)

### Method 3: `get_story_with_scenes()` - Retrieve Complete Story

**Signature**:
```python
async def get_story_with_scenes(
    db: AsyncSession,
    story_id: int,
    user_id: int
) -> Optional[Dict]
```

**Returns**:
```python
{
    'story_id': 123,
    'title': 'Ben\'s Backyard Blast-Off',
    'genre': 'Adventure',
    'thumbnail_url': 'https://june_story.s3.amazonaws.com/...',
    'scenes': [
        {
            'scene_number': 1,
            'text': 'Ben found a rocket ship...',
            'visual_prompt': 'A 5 year old boy...',
            'image_url': 'https://june_story.s3.amazonaws.com/...',
            'audio_url': 'https://june_story.s3.amazonaws.com/...',
            'duration': 15,
            'includes_child': True,
            'emotion': 'excited',
            'reference_image_ids': ['child_123']
        },
        ...
    ]
}
```

### S3 Upload Helper

```python
async def upload_to_s3(
    file_data: bytes,
    key: str,
    content_type: str,
    acl: str = 'public-read'
) -> str
```

**S3 Path Structure**:
```
june_story/
  stories/
    {uuid}/
      thumbnail.png
      scenes/
        scene_001.png
        scene_002.png
        scene_003.png
        ...
      audio/
        scene_001.mp3
        scene_002.mp3
        scene_003.mp3
        ...
```

## Usage Example

### Example 1: Complete Pipeline with Binary Data

```python
from src.story.story_persistence_service import story_persistence_service
from src.db import get_session

async def save_generated_story():
    db = await anext(get_session())
    
    # Story metadata
    story_data = {
        'title': 'Ben\'s Backyard Blast-Off',
        'genre': 'Adventure',
        'story_length': 'medium',
        'target_scenes': 7,
        'child_name': 'Ben',
        'child_age': 5,
        'morals': ['courage', 'curiosity'],
        'art_style': 'magical',
        'user_prompt': 'A story about a boy who finds a rocket ship',
        'total_duration': 180,
        'scenes': [
            {
                'scene_number': 1,
                'text': 'Ben discovered a shiny rocket ship...',
                'visual_prompt': 'Ben, a 5 year old boy with...',
                'includes_child': True,
                'emotion': 'excited',
                'reference_image_ids': ['child_123'],
                'duration': 15
            },
            # ... more scenes
        ]
    }
    
    # Binary media data
    thumbnail_bytes = b'...'  # PNG image bytes
    scene_images = [b'...', b'...', ...]  # List of PNG bytes
    scene_audio = [b'...', b'...', ...]  # List of MP3 bytes
    
    # Save everything
    story = await story_persistence_service.save_complete_story(
        db=db,
        user_id=192,
        child_id=2,
        story_data=story_data,
        thumbnail_data=thumbnail_bytes,
        scene_images_data=scene_images,
        scene_audio_data=scene_audio
    )
    
    print(f"✅ Story saved: {story.story_id}")
    print(f"   Thumbnail: {story.thumbnail_url}")
    print(f"   Scenes: {len(story.scenes)}")
```

### Example 2: Save with Pre-Uploaded URLs

```python
async def save_story_with_urls():
    db = await anext(get_session())
    
    story_data = {
        'title': 'Adventure Story',
        'thumbnail_url': 'https://june_story.s3.amazonaws.com/thumb.png',
        'scenes': [
            {
                'scene_number': 1,
                'text': 'Once upon a time...',
                'visual_prompt': 'A magical forest...',
                'image_url': 'https://june_story.s3.amazonaws.com/scene1.png',
                'audio_url': 'https://june_story.s3.amazonaws.com/audio1.mp3',
                'duration': 12
            },
            # ... more scenes
        ]
    }
    
    story = await story_persistence_service.save_story_from_urls(
        db=db,
        user_id=192,
        child_id=2,
        story_data=story_data
    )
```

## Database Relationships

```
Story (1) ─────→ (Many) StoryScene
                    │
                    ├─→ (Many) StorySceneImage
                    └─→ (Many) StorySceneAudio
```

**Cascade Deletes**: Deleting a Story automatically deletes all related:
- StoryScene records
- StorySceneImage records (via scene cascade)
- StorySceneAudio records (via scene cascade)

## Transaction Safety

All operations use database transactions:
- `await db.commit()` - Commits all changes
- `await db.rollback()` - Rolls back on error
- `await db.flush()` - Gets auto-generated IDs without committing

## Error Handling

- S3 upload failures are logged but don't stop the pipeline
- Database errors trigger rollback
- Detailed error messages with stack traces

## Output Structure

The service returns a `Story` object with:
```python
story.story_id          # Auto-generated ID
story.title             # Story title
story.thumbnail_url     # S3 URL
story.scenes            # List of StoryScene objects
  → scene.images        # List of StorySceneImage objects
  → scene.audio         # List of StorySceneAudio objects
```

## Key Features

✅ **Complete Pipeline**: Handles Story → Scenes → Images → Audio  
✅ **S3 Integration**: Uploads all media to `june_story` bucket  
✅ **Transaction Safe**: All-or-nothing database commits  
✅ **Type Safe**: Uses exact SQLModel field names  
✅ **Flexible**: Supports both binary uploads and pre-uploaded URLs  
✅ **Production Ready**: Proper error handling, logging, rollback  

## Integration with Existing Code

The persistence service is already imported in `src/story/routes.py`:

```python
from src.story.story_persistence_service import story_persistence_service
```

You can call it from any route handler after story generation completes.

## Next Steps

To integrate with your story generation pipeline:

1. **After generating story scenes** (in `routes.py` or `service.py`)
2. **Collect all binary media data** (images, audio)
3. **Call `save_complete_story()`** with the data
4. **Return the created Story object** to the client

The service handles all database operations and S3 uploads automatically.
