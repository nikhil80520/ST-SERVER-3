# Story Generation Complete Guide

## 🎯 Overview

This guide explains the complete story generation pipeline, how to fix all errors, and provides configuration options for both local and AWS Lambda processing.

---

## 🐛 Issues Fixed

### ✅ ISSUE #1: 'StoryService' object has no attribute 'save_story_mmetadata'

**Root Cause:**
- Line 459 in `src/story/routes.py` was calling `story_service.save_story_metadata()`
- But `story_service` in this context was the **OpenAI StoryService** (from `src/story/service.py`)
- The OpenAI StoryService only handles story generation logic - it doesn't have database methods
- The method exists in `src/story/service_pg.py` (PostgreSQL StoryService)

**Fix Applied:**
```python
# ❌ BEFORE (Wrong service)
await story_service.save_story_metadata(
    db, story_id, user_id, "Generating...", user_prompt, initial_manifest,
    child_id=child_id, child_snapshot=child_snapshot
)

# ✅ AFTER (Correct service)
from src.story.service_pg import story_service as pg_story_service
await pg_story_service.save_story_metadata(
    db, story_id, user_id, "Generating...", user_prompt, initial_manifest,
    child_id=child_id, child_snapshot=child_snapshot
)
```

**What This Method Does:**
- Saves initial story metadata to PostgreSQL database
- Creates/updates Firebase document for backward compatibility
- Converts `firebase_user_id` (string) to integer `user_id` for database foreign keys
- Stores story manifest, child snapshot, and generation parameters

---

### ✅ ISSUE #2: SQS Queue Service is disabled - Job submission fails

**Root Cause:**
- Code was hardcoded to ONLY use AWS SQS + Lambda (line 504)
- When `AWS_USE_SQS_LAMBDA=false`, the `sqs_queue_service.submit_story_job()` call would raise an exception
- No fallback to local background workers was implemented

**Fix Applied:**
```python
# ❌ BEFORE (Always fails when SQS disabled)
print(f"📤 Submitting job to AWS SQS for Lambda processing...")
job_id = await sqs_queue_service.submit_story_job(
    story_id=story_id,
    parameters=job_params,
    priority=0
)

# ✅ AFTER (Smart dispatch with fallback)
use_sqs = settings.aws.use_sqs_lambda if hasattr(settings, 'aws') else False

if use_sqs and sqs_queue_service.enabled:
    # AWS SQS + Lambda
    job_id = await sqs_queue_service.submit_story_job(...)
else:
    # Local background workers
    enhanced_background_service = EnhancedBackgroundTaskService(max_workers=3)
    if not enhanced_background_service.running:
        await enhanced_background_service.start(num_workers=3)
    
    job_id = await enhanced_background_service.submit_story_job(
        story_id=story_id,
        parameters=job_params,
        services={...},
        callbacks={...}
    )
```

---

## 🔧 Configuration Options

### Option A: Local Background Workers (Default)

**When to Use:**
- Development environment
- Testing
- No AWS infrastructure
- Lower latency (no network overhead)
- Simpler deployment

**How to Enable:**
```bash
# In .env file or environment variables
AWS_USE_SQS_LAMBDA=false
```

**How It Works:**
1. Client calls `/stories/generate` endpoint
2. FastAPI creates initial story record in PostgreSQL
3. Job submitted to local `EnhancedBackgroundTaskService`
4. Worker pool (default 3 workers) picks up job asynchronously
5. Worker executes `ParallelStoryService.generate_story_parallel()`:
   - Generates story structure via OpenAI
   - Creates scenes with images (DALL-E 3) and audio (TTS)
   - Uploads media to S3
   - Saves complete story to PostgreSQL
6. WebSocket notifications sent to client during processing
7. Client receives completion notification with story manifest

**Architecture:**
```
Client Request
    ↓
/stories/generate (FastAPI)
    ↓
Create PostgreSQL Story record
    ↓
Submit to EnhancedBackgroundTaskService (in-process)
    ↓
Worker Pool (3 async workers)
    ↓
ParallelStoryService.generate_story_parallel()
    ├─ StoryService: Generate narrative
    ├─ MediaService: Create images + audio
    ├─ S3StorageService: Upload media
    └─ StoryPersistenceService: Save to DB
    ↓
WebSocket: Send completion notification
```

**Advantages:**
- ✅ No AWS infrastructure required
- ✅ Lower latency (no SQS/Lambda cold starts)
- ✅ Easier debugging
- ✅ No additional costs

**Limitations:**
- ❌ Scales with server instance (not horizontally)
- ❌ Jobs lost if server restarts
- ❌ Limited by server resources

---

### Option B: AWS SQS + Lambda (Production)

**When to Use:**
- Production environment
- High traffic / many concurrent generations
- Horizontal scaling required
- Need job persistence across server restarts

**Environment Variables Required:**
```bash
# Required AWS Configuration
AWS_USE_SQS_LAMBDA=true
AWS_REGION=us-east-1
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/story-generation-queue

# AWS Credentials (if not using IAM roles)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=secret...

# S3 Configuration (already required)
AWS_S3_BUCKET_NAME=june_story
```

**AWS Infrastructure Setup:**

1. **Create SQS Queue:**
```bash
aws sqs create-queue \
    --queue-name story-generation-queue \
    --attributes VisibilityTimeout=1800,ReceiveMessageWaitTimeSeconds=20
```

2. **Create Lambda Function:**
```bash
# See lambda-deployment/ directory for complete setup
cd lambda-deployment
./deploy-docker-lambda.sh
```

3. **Configure SQS Trigger:**
```bash
aws lambda create-event-source-mapping \
    --function-name story-generation-lambda \
    --event-source-arn arn:aws:sqs:us-east-1:123456789:story-generation-queue \
    --batch-size 1
```

**How It Works:**
1. Client calls `/stories/generate` endpoint
2. FastAPI creates initial story record in PostgreSQL
3. Job payload sent to AWS SQS queue
4. SQS triggers Lambda function
5. Lambda executes story generation (same `ParallelStoryService`)
6. Lambda saves results to PostgreSQL + S3
7. Lambda sends WebSocket notification to API Gateway (optional)
8. Client receives completion via WebSocket or polling

**Lambda Payload Format:**
```json
{
  "job_id": "uuid",
  "story_id": "story_uuid",
  "user_id": "firebase_user_id",
  "parameters": {
    "user_prompt": "Create a story about...",
    "child_id": "child_uuid",
    "child_name": "Alex",
    "child_age": 7,
    "target_scenes": 7,
    "art_style": "magical",
    "reference_image_urls": ["https://s3..."],
    ...
  },
  "created_at": "2025-12-05T10:30:00Z",
  "priority": 0
}
```

**Advantages:**
- ✅ Horizontal scaling (Lambda auto-scales)
- ✅ Job persistence (SQS durability)
- ✅ Fault tolerance (automatic retries)
- ✅ Pay-per-use pricing

**Limitations:**
- ❌ Cold start latency (~1-5 seconds)
- ❌ More complex infrastructure
- ❌ AWS costs (Lambda + SQS)

---

## 🔄 Complete End-to-End Flow

### Request Flow
```
1. Client sends POST /stories/generate
   ├─ Request body: StoryPromptRequest
   ├─ Firebase token authentication
   └─ Account status validation

2. API validates request
   ├─ Verify firebase token
   ├─ Check account status (trial/subscription)
   ├─ Validate child_id
   ├─ Fetch reference images
   └─ Build job parameters

3. Create initial PostgreSQL record
   ├─ Story table: status="processing"
   ├─ Auto-generate story_id (UUID)
   └─ Store child_snapshot

4. Save to Firebase (backward compatibility)
   ├─ Using PostgreSQL StoryService
   └─ Non-critical (fails gracefully)

5. Dispatch job
   ├─ IF AWS_USE_SQS_LAMBDA=true
   │   └─ Submit to SQS queue
   └─ ELSE
       └─ Submit to local EnhancedBackgroundTaskService

6. Return response immediately
   {
     "success": true,
     "story_id": "uuid",
     "job_id": "job_uuid",
     "status": "processing",
     "websocket_endpoint": "/ws/stories/{token}"
   }
```

### Background Processing Flow
```
1. Worker picks up job
   ├─ Local: EnhancedBackgroundTaskService worker
   └─ AWS: Lambda function invoked by SQS

2. Execute story generation
   ├─ ParallelStoryService.generate_story_parallel()
   │   ├─ Generate story structure (OpenAI GPT-4)
   │   ├─ Create character references
   │   ├─ Generate scenes in parallel:
   │   │   ├─ Scene narrative
   │   │   ├─ Image generation (DALL-E 3)
   │   │   ├─ Audio generation (TTS)
   │   │   └─ Upload to S3
   │   └─ Build manifest
   └─ Send progress WebSocket notifications

3. Save complete story
   ├─ StoryPersistenceService.save_story_from_urls()
   │   ├─ Update Story record
   │   ├─ Create StoryScene records
   │   ├─ Create StorySceneImage records
   │   └─ Create StorySceneAudio records
   └─ Update story status="completed"

4. Send completion notification
   ├─ WebSocket: story_completed event
   └─ Include full manifest

5. Clean up
   ├─ Remove from active jobs
   └─ Log performance metrics
```

---

## 📊 Database Schema

### Story Table
```sql
CREATE TABLE stories (
    story_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(user_id),
    child_id UUID REFERENCES children(child_id),
    title VARCHAR(255) NOT NULL,
    genre VARCHAR(100),
    story_length VARCHAR(50),
    target_scenes INTEGER,
    age_group VARCHAR(50),
    child_name VARCHAR(100),
    child_age INTEGER,
    story_theme TEXT,
    moral_lesson TEXT,
    morals TEXT,
    target_emotion VARCHAR(100),
    art_style VARCHAR(100),
    thumbnail_url TEXT,
    status VARCHAR(50) DEFAULT 'processing',
    child_snapshot JSONB,
    manifest JSONB,
    scenes_data JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### StoryScene Table
```sql
CREATE TABLE story_scenes (
    scene_id SERIAL PRIMARY KEY,
    story_id UUID NOT NULL REFERENCES stories(story_id) ON DELETE CASCADE,
    scene_number INTEGER NOT NULL,
    scene_text TEXT NOT NULL,
    duration FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### StorySceneImage Table
```sql
CREATE TABLE story_scene_images (
    image_id SERIAL PRIMARY KEY,
    scene_id INTEGER NOT NULL REFERENCES story_scenes(scene_id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    image_type VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### StorySceneAudio Table
```sql
CREATE TABLE story_scene_audio (
    audio_id SERIAL PRIMARY KEY,
    scene_id INTEGER NOT NULL REFERENCES story_scenes(scene_id) ON DELETE CASCADE,
    audio_url TEXT NOT NULL,
    duration FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 🧪 Testing the Fixed Implementation

### Test Local Background Workers
```bash
# 1. Set environment variable
export AWS_USE_SQS_LAMBDA=false

# 2. Start FastAPI server
cd /path/to/STS-Server
source myenv/bin/activate  # or myenv\Scripts\activate on Windows
uvicorn src.main:app --reload

# 3. Call API
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{
    "firebase_token": "your_token",
    "prompt": "Create a magical adventure story",
    "child_id": "child_uuid",
    "scene_count": 5,
    "art_style": "watercolor",
    "should_use_voice_clone": true
  }'

# Expected logs:
# ✅ Created initial story record in PostgreSQL: story_id=...
# 🔧 Processing method: Local background workers
# 📤 Submitting job to local background service...
# 🚀 Starting enhanced background task service with 3 workers
# ✅ Job submitted to local background service: job_id
# 👷 worker-1 started
# 🔄 worker-1 processing job ...
# 🎬 Executing story generation job: ...
```

### Test AWS SQS + Lambda
```bash
# 1. Set environment variables
export AWS_USE_SQS_LAMBDA=true
export AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/.../story-queue
export AWS_REGION=us-east-1

# 2. Start server and call API (same as above)

# Expected logs:
# ✅ Created initial story record in PostgreSQL: story_id=...
# 🔧 Processing method: AWS SQS + Lambda
# 📤 Submitting job to AWS SQS for Lambda processing...
# ✅ Job submitted to SQS: job_id

# Check SQS queue
aws sqs get-queue-attributes \
  --queue-url $AWS_SQS_QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages

# Check Lambda logs
aws logs tail /aws/lambda/story-generation-lambda --follow
```

---

## 🚨 Error Handling

### Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `'StoryService' object has no attribute 'save_story_mmetadata'` | Using wrong service (OpenAI instead of PostgreSQL) | ✅ Fixed - now uses `pg_story_service` |
| `SQS Queue Service is disabled` | SQS disabled but code tries to use it | ✅ Fixed - falls back to local workers |
| `User not found in database` | Firebase user not in PostgreSQL | Auto-creates minimal user record |
| `Child profile not found` | Invalid child_id | Returns 404, prompts user to create profile |
| `Reference image not found` | Invalid reference_image_id | Returns 404 with missing IDs |
| `OpenAI API timeout` | API rate limit or slow response | Retries up to 2 times with exponential backoff |
| `S3 upload failed` | Network error or permissions | Retries upload, fails story generation if persistent |

---

## 📈 Performance Optimization

### Local Workers
```python
# Adjust worker count based on server CPU cores
enhanced_background_service = EnhancedBackgroundTaskService(max_workers=5)
await enhanced_background_service.start(num_workers=5)
```

### AWS Lambda
```bash
# Increase Lambda memory for faster processing
aws lambda update-function-configuration \
  --function-name story-generation-lambda \
  --memory-size 3008  # Max CPU at 3GB+
  --timeout 900  # 15 minutes max

# Use provisioned concurrency to avoid cold starts
aws lambda put-provisioned-concurrency-config \
  --function-name story-generation-lambda \
  --provisioned-concurrent-executions 2
```

---

## 🎉 Final Checklist

✅ **Issue #1 Fixed:** Correct service used for `save_story_metadata()` call  
✅ **Issue #2 Fixed:** Local workers used when SQS disabled  
✅ **Issue #3 Confirmed:** Async background workflow runs locally  
✅ **Issue #4 Documented:** Complete end-to-end flow explained  

### All Components Working:
- ✅ PostgreSQL story storage
- ✅ S3 media storage (bucket: `june_story`)
- ✅ Firebase backward compatibility
- ✅ Local async processing (when SQS disabled)
- ✅ AWS SQS + Lambda integration (when enabled)
- ✅ WebSocket real-time notifications
- ✅ Error handling and retries

---

## 📞 Support

For issues:
1. Check logs: `journalctl -u fastapi-app -f` or Lambda CloudWatch
2. Verify environment variables
3. Test database connectivity
4. Check S3 permissions
5. Validate OpenAI API key

Need help? Contact: devathub9 (GitHub)
