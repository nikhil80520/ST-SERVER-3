# PostgreSQL Story Storage Implementation

## Overview
This document describes the implementation of PostgreSQL-based story storage for the STS-Server application. All story data, including scenes, images, and audio, are now stored in PostgreSQL tables with S3 URLs for media files.

## Database Schema

### Story Table
Stores main story metadata:
- `story_id`: Auto-increment integer primary key
- `user_id`: Foreign key to User table (integer)
- `child_id`: Foreign key to Child table (integer)
- `title`, `genre`, `story_length`: Story metadata
- `thumbnail_url`, `local_thumbnail_path`: Story thumbnail
- `duration`, `target_scenes`, `age_group`: Story parameters
- `child_name`, `child_age`: Child info snapshot
- `story_theme`, `moral_lesson`, `morals`, `target_emotion`, `parent_context`: Story generation parameters
- `art_style`, `ambient_sound`, `thumbnail_prompt`: Style parameters
- `created_at`, `updated_at`: Timestamps

### StoryScene Table
Stores individual scenes:
- `story_scene_id`: Auto-increment integer primary key
- `story_id`: Foreign key to Story table
- `scene_number`: Integer (1, 2, 3, ...)
- `includes_child`: Boolean
- `emotion`: String (happy, sad, excited, etc.)
- `reference_image_ids`: JSON array of reference image IDs
- `created_at`, `updated_at`: Timestamps

### StorySceneImage Table
Stores images for each scene:
- `story_scene_image_id`: Auto-increment integer primary key
- `story_scene_id`: Foreign key to StoryScene table
- `text`: Scene narration text
- `visual_prompt`: Image generation prompt
- `image_url`: S3 URL (e.g., `https://june_story.s3.us-east-1.amazonaws.com/stories/{story_id}/images/scene_{scene_number}_colored.jpg`)
- `image_type`: 'scene', 'thumbnail', etc.
- `created_at`, `updated_at`: Timestamps

### StorySceneAudio Table
Stores audio for each scene:
- `story_scene_audio_id`: Auto-increment integer primary key
- `story_scene_id`: Foreign key to StoryScene table
- `text`: Scene narration text
- `audio_url`: S3 URL (e.g., `https://june_story.s3.us-east-1.amazonaws.com/stories/{story_id}/audio/scene_{scene_number}.opus`)
- `audio_type`: 'narration', 'background', 'effects'
- `duration`: Integer (seconds)
- `created_at`, `updated_at`: Timestamps

## S3 Storage

### Bucket Configuration
- **Bucket Name**: `june_story`
- **Region**: `us-east-1` (configurable via `AWS_REGION`)
- **Access**: Public read (ACL: `public-read`)

### File Paths
- **Story Audio**: `stories/{story_id}/audio/scene_{scene_number}.opus`
- **Story Images**: `stories/{story_id}/images/scene_{scene_number}_colored.jpg`
- **Story Thumbnail**: `stories/{story_id}/thumbnail.jpg`
- **User Profile**: `users/{user_id}/profile_image_{timestamp}.jpg`
- **User Voice**: `users/{user_id}/voice/voice_sample_{timestamp}.wav`

### Environment Variables
Add to `.env`:
```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
AWS_S3_BUCKET_NAME=june_story
```

## New Files Created

### 1. `src/story/story_persistence_service.py`
Comprehensive service for PostgreSQL story operations:

#### Methods:
- `save_complete_story(db, user_id, child_id, story_data)`: Save complete story with all scenes, images, and audio
- `get_story_with_scenes(db, story_id, user_id)`: Retrieve complete story manifest
- `get_user_stories(db, user_id, limit, offset)`: Get user stories with pagination
- `delete_story(db, story_id, user_id)`: Delete story and all related data (cascade)

#### Example Usage:
```python
from src.story.story_persistence_service import story_persistence_service

# Save complete story
story = await story_persistence_service.save_complete_story(
    db=db,
    user_id=123,  # integer user_id
    child_id=456,  # integer child_id
    story_data={
        "title": "Ben's Adventure",
        "genre": "adventure",
        "story_length": "medium",
        "morals": "kindness and courage",
        "art_style": "watercolor",
        "scenes": [
            {
                "scene_number": 1,
                "text": "Once upon a time...",
                "visual_prompt": "A boy in a backyard",
                "image_url": "https://june_story.s3.us-east-1.amazonaws.com/stories/123/images/scene_1.jpg",
                "audio_url": "https://june_story.s3.us-east-1.amazonaws.com/stories/123/audio/scene_1.opus",
                "includes_child": True,
                "emotion": "happy",
                "reference_image_ids": ["child_ref"],
                "duration": 10
            },
            # ... more scenes
        ],
        "thumbnail_url": "https://june_story.s3.us-east-1.amazonaws.com/stories/123/thumbnail.jpg"
    }
)
```

## Modified Files

### 1. `src/story/routes.py`

#### New Import:
```python
from src.story.story_persistence_service import story_persistence_service
```

#### Changes to `/stories/generate` (POST):
- Creates initial Story record in PostgreSQL with "Generating..." status
- Captures auto-generated `story_id` from PostgreSQL
- Saves to Firebase for backward compatibility (optional)

#### New Endpoint: `/stories/complete/{story_id}` (POST)
Lambda function calls this endpoint after story generation completes:
```python
POST /stories/complete/{story_id}
Body: {
    "firebase_user_id": "ABC123...",
    "child_id": 123,
    "title": "Story Title",
    "scenes": [...],
    "thumbnail_url": "https://..."
}
```

#### Modified Endpoints:
- `/stories/user/stories` (GET): Fetches from PostgreSQL Story table
- `/stories/details/{story_id}` (GET): Fetches complete story with all scenes from PostgreSQL
- `/stories/list/{user_token}` (GET): Uses PostgreSQL query

### 2. `src/common_function/storage_s3_service.py`

#### Changes:
- Updated `__init__` to use `june_story` bucket by default
- All S3 uploads now target `june_story` bucket

### 3. `.env`

#### Added AWS Configuration:
```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_ACCESS_KEY
AWS_S3_BUCKET_NAME=june_story
```

## Story Generation Flow

### 1. Frontend Calls `/stories/generate`
- User initiates story generation request
- Server validates authentication and account status
- **NEW**: Creates initial Story record in PostgreSQL with "processing" status
- Submits job to SQS queue for Lambda processing
- Returns `story_id` immediately

### 2. Lambda Function Generates Story
- Generates scenes, images, and audio
- Uploads all media to S3 `june_story` bucket
- Builds complete story manifest

### 3. Lambda Calls `/stories/complete/{story_id}`
- **NEW**: Lambda POSTs complete story data to this endpoint
- Server saves all Story, StoryScene, StorySceneImage, and StorySceneAudio records
- Frontend can now fetch complete story via `/stories/details/{story_id}`

### 4. Frontend Fetches Story
- Calls `/stories/user/stories` to list all stories
- Calls `/stories/details/{story_id}` to get complete story with scenes

## Migration Notes

### Backward Compatibility
- Old Firebase-based story retrieval still works (legacy support)
- New stories are saved to both PostgreSQL AND Firebase
- Gradual migration: can run both systems in parallel

### Data Migration
To migrate existing Firebase stories to PostgreSQL:
1. Create migration script to read from Firebase
2. Transform data to match PostgreSQL schema
3. Call `story_persistence_service.save_complete_story()` for each story
4. Verify data integrity

## API Response Format

### GET `/stories/user/stories`
```json
{
    "success": true,
    "firebase_user_id": "ABC123...",
    "stories": [
        {
            "story_id": 1,
            "title": "Ben's Adventure",
            "genre": "adventure",
            "thumbnail_url": "https://june_story.s3.../thumbnail.jpg",
            "duration": 120,
            "target_scenes": 8,
            "child_name": "Ben",
            "created_at": "2025-12-05T10:30:00Z",
            "total_scenes": 8
        }
    ],
    "total": 10,
    "limit": 20,
    "offset": 0
}
```

### GET `/stories/details/{story_id}`
```json
{
    "success": true,
    "story": {
        "story_id": 1,
        "title": "Ben's Adventure",
        "genre": "adventure",
        "story_length": "medium",
        "thumbnail_url": "https://...",
        "total_duration": 120,
        "scenes": [
            {
                "scene_number": 1,
                "text": "Once upon a time...",
                "visual_prompt": "A boy...",
                "image_url": "https://...",
                "audio_url": "https://...",
                "includes_child": true,
                "emotion": "happy",
                "duration": 10
            }
        ]
    }
}
```

## Testing

### 1. Test Story Generation
```bash
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{
    "firebase_token": "YOUR_TOKEN",
    "prompt": "A space adventure",
    "child_id": 2,
    "scene_count": 5
  }'
```

### 2. Test Story Completion (Lambda Callback)
```bash
curl -X POST http://localhost:8000/stories/complete/1 \
  -H "Content-Type: application/json" \
  -d @complete_story_payload.json
```

### 3. Test Story Retrieval
```bash
# List stories
curl http://localhost:8000/stories/user/stories \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get story details
curl http://localhost:8000/stories/details/1?firebase_token=YOUR_TOKEN
```

## Security Considerations

1. **S3 Bucket Permissions**: Ensure `june_story` bucket has proper CORS and public read access
2. **API Authentication**: All endpoints require Firebase token verification
3. **User Authorization**: Stories are filtered by user_id to prevent unauthorized access
4. **SQL Injection**: All queries use SQLAlchemy ORM with parameter binding

## Performance Optimizations

1. **Eager Loading**: Use `selectinload` for Story relationships to avoid N+1 queries
2. **Pagination**: All list endpoints support `limit` and `offset` parameters
3. **Caching**: Consider adding Redis cache for frequently accessed stories
4. **CDN**: S3 URLs can be fronted with CloudFront for faster global access

## Troubleshooting

### Issue: AWS credentials not found
**Solution**: Add AWS environment variables to `.env` file

### Issue: Story not found after generation
**Solution**: Check Lambda logs to ensure `/stories/complete/{story_id}` was called successfully

### Issue: Images/audio not loading
**Solution**: Verify S3 bucket permissions and CORS configuration

### Issue: User not found error
**Solution**: Ensure firebase_user_id exists in User table with valid user_id

## Next Steps

1. ✅ Create story persistence service
2. ✅ Update story generation route
3. ✅ Update story retrieval endpoints
4. ✅ Configure S3 bucket
5. 🔲 Update Lambda function to call `/stories/complete/{story_id}`
6. 🔲 Test end-to-end story generation and retrieval
7. 🔲 Monitor S3 usage and costs
8. 🔲 Implement data migration from Firebase to PostgreSQL
9. 🔲 Add CloudFront CDN for S3 media delivery

## Contact

For questions or issues, contact the development team.
