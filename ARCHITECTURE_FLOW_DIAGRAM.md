# Story Generation Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CLIENT APPLICATION                                  │
│  (Mobile App / Web Frontend)                                                │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                             │ POST /stories/generate
                             │ { firebase_token, prompt, child_id, ... }
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        FASTAPI SERVER (routes.py)                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 1. Authentication & Validation                                      │   │
│  │    ✓ Verify Firebase token                                         │   │
│  │    ✓ Check account status (trial/subscription)                     │   │
│  │    ✓ Validate child_id                                             │   │
│  │    ✓ Fetch reference images                                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 2. Create Initial Story Record                                      │   │
│  │    PostgreSQL: INSERT INTO stories (...)                            │   │
│  │    Status: "processing"                                             │   │
│  │    Auto-generate: story_id (UUID)                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 3. Firebase Backward Compatibility (Optional)                       │   │
│  │    pg_story_service.save_story_metadata()                           │   │
│  │    Note: Uses correct PostgreSQL service now ✓                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ 4. Smart Job Dispatch                                               │   │
│  │                                                                      │   │
│  │    IF AWS_USE_SQS_LAMBDA = true:                                    │   │
│  │       ├─► Submit to AWS SQS Queue                                   │   │
│  │       └─► Return job_id to client                                   │   │
│  │                                                                      │   │
│  │    ELSE (Default):                                                  │   │
│  │       ├─► Submit to Local Background Workers                        │   │
│  │       └─► Return job_id to client                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                               │
│  Return: {                                                                  │
│    success: true,                                                           │
│    story_id: "uuid",                                                        │
│    job_id: "job_uuid",                                                      │
│    websocket_endpoint: "/ws/stories/{token}"                                │
│  }                                                                           │
└────────────────────────────┬────────────────────────────────────────────────┘
                             │
                ┌────────────┴───────────┐
                │                        │
                ▼                        ▼
┌───────────────────────────┐  ┌────────────────────────────┐
│   LOCAL WORKERS PATH      │  │    AWS LAMBDA PATH         │
│   (Development)           │  │    (Production)            │
└───────────────────────────┘  └────────────────────────────┘
                │                        │
                ▼                        ▼
┌───────────────────────────┐  ┌────────────────────────────┐
│ EnhancedBackgroundTask    │  │    AWS SQS Queue           │
│ Service                   │  │                            │
│                           │  │  ┌──────────────────────┐  │
│ Worker Pool (3 workers)   │  │  │ Message Payload:     │  │
│  ├─ worker-1              │  │  │  {                   │  │
│  ├─ worker-2              │  │  │    job_id,           │  │
│  └─ worker-3              │  │  │    story_id,         │  │
│                           │  │  │    parameters,       │  │
│ Picks job from queue      │  │  │    ...               │  │
│ Executes in async task    │  │  │  }                   │  │
│                           │  │  └──────────────────────┘  │
└────────────┬──────────────┘  └────────────┬───────────────┘
             │                              │
             │                              ▼
             │                  ┌────────────────────────────┐
             │                  │   AWS Lambda Function      │
             │                  │   (Triggered by SQS)       │
             │                  │                            │
             │                  │   Receives message payload │
             │                  │   Executes story generation│
             │                  └────────────┬───────────────┘
             │                               │
             └───────────────┬───────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   PARALLEL STORY SERVICE                                     │
│  (ParallelStoryService.generate_story_parallel)                             │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ Step 1: Generate Story Structure                                   │    │
│  │  StoryService (OpenAI GPT-4)                                        │    │
│  │   └─► Create narrative outline, character list, scene descriptions │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                              │                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ Step 2: Character Reference Creation                               │    │
│  │   IF reference_image_urls provided:                                 │    │
│  │      └─► Use user's reference images                                │    │
│  │   ELSE:                                                             │    │
│  │      └─► Generate character reference with DALL-E 3                 │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                              │                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ Step 3: Parallel Scene Generation (asyncio.gather)                 │    │
│  │                                                                      │    │
│  │  For each scene (1 to N):                                          │    │
│  │    ┌──────────────────────────────────────────────────────────┐   │    │
│  │    │ Scene Text Generation (OpenAI)                            │   │    │
│  │    │  └─► Generate detailed scene description                  │   │    │
│  │    └──────────────────────────────────────────────────────────┘   │    │
│  │                        │                                            │    │
│  │    ┌──────────────────────────────────────────────────────────┐   │    │
│  │    │ Image Generation (DALL-E 3)                               │   │    │
│  │    │  ├─► Create prompt with character references              │   │    │
│  │    │  ├─► Generate 1024x1024 image                             │   │    │
│  │    │  └─► Upload to S3 (june_story/images/)                    │   │    │
│  │    └──────────────────────────────────────────────────────────┘   │    │
│  │                        │                                            │    │
│  │    ┌──────────────────────────────────────────────────────────┐   │    │
│  │    │ Audio Generation (OpenAI TTS)                             │   │    │
│  │    │  ├─► Convert scene text to speech                         │   │    │
│  │    │  ├─► Use voice clone if specified                         │   │    │
│  │    │  └─► Upload to S3 (june_story/audio/)                     │   │    │
│  │    └──────────────────────────────────────────────────────────┘   │    │
│  │                                                                      │    │
│  │  All scenes processed in parallel → 3-5x faster than sequential    │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                              │                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ Step 4: Build Complete Manifest                                    │    │
│  │  {                                                                  │    │
│  │    story_id, title, scenes: [                                      │    │
│  │      { text, image_url, audio_url, duration },                     │    │
│  │      ...                                                            │    │
│  │    ],                                                               │    │
│  │    total_duration, thumbnail_url, status: "completed"              │    │
│  │  }                                                                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  STORY PERSISTENCE SERVICE                                   │
│  (StoryPersistenceService.save_story_from_urls)                             │
│                                                                              │
│  Database Transactions (PostgreSQL):                                        │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ 1. UPDATE stories                                                   │    │
│  │    SET status = 'completed',                                        │    │
│  │        manifest = {...},                                            │    │
│  │        thumbnail_url = '...'                                        │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ 2. INSERT INTO story_scenes (for each scene)                        │    │
│  │    (story_id, scene_number, scene_text, duration)                   │    │
│  │    Returns: scene_id                                                │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ 3. INSERT INTO story_scene_images                                   │    │
│  │    (scene_id, image_url, image_type)                                │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │ 4. INSERT INTO story_scene_audio                                    │    │
│  │    (scene_id, audio_url, duration)                                  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  All operations in single transaction → Atomic save                         │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    WEBSOCKET NOTIFICATION                                    │
│  (story_websocket_manager.broadcast_to_user)                                │
│                                                                              │
│  Send to client:                                                            │
│  {                                                                           │
│    event: "story_completed",                                                │
│    story_id: "uuid",                                                        │
│    title: "Story Title",                                                    │
│    manifest: { ... },                                                       │
│    timestamp: "2025-12-05T10:30:00Z"                                        │
│  }                                                                           │
└──────────────────────────────┬───────────────────────────────────────────────┘
                               │
                               ▼
                         ┌─────────────┐
                         │   CLIENT    │
                         │  Receives   │
                         │  Complete   │
                         │   Story     │
                         └─────────────┘


═══════════════════════════════════════════════════════════════════════════════
                            DATA FLOW SUMMARY
═══════════════════════════════════════════════════════════════════════════════

1. Client Request → FastAPI (validate, create DB record)
2. Job Dispatch → Local Workers OR AWS Lambda
3. Background Processing:
   ├─ Generate story structure (GPT-4)
   ├─ Generate scenes in parallel:
   │  ├─ Scene text
   │  ├─ Image (DALL-E 3) → S3
   │  └─ Audio (TTS) → S3
   └─ Build manifest
4. Save to Database:
   ├─ Story (metadata)
   ├─ StoryScene (text, duration)
   ├─ StorySceneImage (S3 URLs)
   └─ StorySceneAudio (S3 URLs)
5. WebSocket Notification → Client
6. Client displays complete story with images and audio

═══════════════════════════════════════════════════════════════════════════════
                         STORAGE ARCHITECTURE
═══════════════════════════════════════════════════════════════════════════════

PostgreSQL Database:
  ├─ stories (metadata, manifest, status)
  ├─ story_scenes (scene text, duration)
  ├─ story_scene_images (S3 URLs)
  └─ story_scene_audio (S3 URLs)

S3 Bucket (june_story):
  ├─ images/
  │  ├─ thumbnails/{story_id}_thumbnail.png
  │  └─ scenes/{story_id}_scene_{n}.png
  └─ audio/
     └─ scenes/{story_id}_scene_{n}.mp3

Firebase (Legacy - Backward Compatibility):
  └─ users/{user_id}/stories/{story_id}

═══════════════════════════════════════════════════════════════════════════════
