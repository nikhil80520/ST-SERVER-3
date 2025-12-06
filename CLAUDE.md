# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ESP32 Storytelling Server - An AI-powered personalized storytelling platform with voice synthesis, conversational AI, and IoT device support. FastAPI backend that generates children's stories with synchronized audio, images, and real-time voice conversations via WebRTC.

## Essential Commands

### Development
```bash
# Start development server with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Activate virtual environment (if using venv)
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/test_queue_management.py

# Run specific test markers
pytest -m smoke       # smoke tests only
pytest -m integration # integration tests only
pytest -m unit        # unit tests only
```

### Utility Scripts
```bash
# Generate Firebase ID token for testing
python scripts/generate-firebase-token.py

# Get user ID token
python scripts/get-id-token.py

# Test responsiveness during story generation
export FIREBASE_TOKEN="<token>"
python scripts/responsiveness_probe.py --host http://localhost:8000 --duration 45
```

## Architecture

### Core Service Layer Pattern

The codebase follows **strict dependency injection** - services MUST receive dependencies via constructor, never instantiate them internally:

```python
# CORRECT ✅
class StoryService:
    def __init__(self, storage_service: StorageService, media_service: MediaService):
        self.storage = storage_service
        self.media = media_service

# INCORRECT ❌
class StoryService:
    def __init__(self):
        self.storage = StorageService()  # Don't do this!
```

### Request Flow
```
Client → Router (routers/) → Service Layer (services/) → External APIs/Firebase → Response
         └─ Middleware (auth, CORS) applied first
```

### Key Architectural Patterns

1. **Router Layer** (`app/routers/`): HTTP request handling only, no business logic
2. **Service Layer** (`app/services/`): All business logic, orchestrates operations
3. **Models** (`app/models/`): Pydantic data models for validation
4. **Core** (`app/core/`): Application initialization, config, middleware, error handling
5. **Utils** (`app/utils/`): Reusable helpers (Firebase init, logging, security)

### Critical Services

- **`parallel_story_service.py`**: Orchestrates parallel story generation (text → audio+images concurrently)
- **`enhanced_background_service.py`**: Queue management with priority, failover, and heartbeat monitoring
- **`story_websocket_manager.py`**: Real-time progress updates to clients
- **`cartesia_service.py`**: Text-to-speech with voice cloning support
- **`storage_service.py`**: Firebase Storage operations with parallel uploads
- **`iot_device_service_firestore.py`**: ESP32 device claiming and management

## Configuration System

Configuration lives in `app/core/config.py` with grouped settings:

```python
from app.core.config import settings

# Access nested config groups
settings.firebase.credentials_path
settings.ai_services.openai_api_key
settings.performance.max_concurrent_scenes
settings.audio.enable_ambient_persistence
settings.story.max_scenes

# Or use legacy flat fields (backward compatible)
settings.firebase_credentials_path
settings.openai_api_key
settings.max_concurrent_scenes
```

### Important Config Flags

**Performance Tuning**:
- `max_concurrent_scenes`: Parallel scene processing (default: 4)
- `enable_batch_audio`: Batch audio generation (default: true)
- `enable_parallel_uploads`: Parallel Firebase uploads (default: true)
- `background_workers`: Async worker pool size (default: 8)

**Audio Enhancement**:
- `enable_ambient_persistence`: Cache ambient sounds to disk (default: false)
- `ambient_cache_dir`: Cache directory path (default: ./cache/ambient)
- `reuse_single_ambient_bed`: Reuse first ambient across all scenes (default: false)
- `enable_audio_enhancement`: Post-processing (reverb, compression) (default: true)

## Story Generation Pipeline

The system uses **parallel processing** to minimize generation time (~45 seconds):

1. **Text Generation** (sequential): GPT-4 generates story structure with 5-10 scenes
2. **Media Generation** (parallel): Audio (Cartesia TTS) + Images (SeeDream) run concurrently per scene
3. **Upload** (parallel): All media files upload to Firebase Storage simultaneously
4. **Manifest Creation**: Firestore document with URLs, durations, metadata

Progress updates flow via WebSocket to connected clients in real-time.

## Database & Storage

- **Firestore Collections**:
  - `users`: User profiles and preferences
  - `children`: Child profiles linked to parent users
  - `stories`: Story metadata, status, and manifests
  - `iot_devices`: ESP32 device registrations and claims
  - `shared_stories`: Story sharing between users
  - `reference_images`: Character reference images for consistency

- **Firebase Storage Structure**:
  ```
  /stories/{story_id}/
    ├── scene_0_audio.ogg
    ├── scene_0_image.png
    ├── scene_1_audio.ogg
    └── ...
  /voice_clones/{user_id}/
    └── samples/
  /reference_images/{child_id}/
    └── {image_id}.png
  ```

## Authentication & Security

### User Authentication (Firebase Auth)
- JWT tokens validated via Firebase Admin SDK
- Tokens extracted from `Authorization: Bearer <token>` header
- Current user dependency: `get_current_user()` in `app/core/dependencies.py`

### IoT Device Authentication
- **Device Claiming**: QR code with time-limited claim token (10 min TTL)
- **HMAC Authentication**: Timestamp + signature validation (5 min tolerance)
- **Device JWT**: Long-lived tokens (4 hours) for claimed devices
- Security config in `app/core/config.py` → `iot_security` group

## WebRTC Conversational AI

Uses **Pipecat framework** for real-time voice conversations:

- **Transport**: SmallWebRTC (lightweight, mobile-friendly)
- **STT**: Deepgram Nova 2
- **LLM**: OpenAI GPT-4
- **TTS**: Cartesia Sonic (ultra-low latency)
- **Integration**: See `app/routers/conversation.py` and docs/features/CONVERSATIONAL_AI_DOCS.md

## Common Patterns

### Adding a New API Endpoint

1. Define Pydantic model in `app/models/`
2. Create service class in `app/services/` with dependency injection
3. Add router endpoint in `app/routers/`
4. Register router in `app/core/app_init.py` → `register_routers()`
5. Add dependency provider in `app/core/dependencies.py` if needed

### Error Handling

Use `@error_handler` decorator from `app/core/error_decorator.py` for automatic error logging:

```python
from app.core.error_decorator import error_handler

@error_handler("Story generation failed")
async def generate_story(params):
    # Errors automatically logged with context
    pass
```

### Async Operations

Always use `asyncio.gather()` for parallel operations:

```python
# CORRECT ✅ - Parallel execution
audio_tasks = [generate_audio(scene) for scene in scenes]
image_tasks = [generate_image(scene) for scene in scenes]
audios, images = await asyncio.gather(*audio_tasks, *image_tasks)

# INCORRECT ❌ - Sequential execution
for scene in scenes:
    audio = await generate_audio(scene)  # Slow!
    image = await generate_image(scene)
```

## Important Notes

- **No `requirements.txt`**: Dependencies appear to be managed differently - check with user if needed
- **Multiple `main.py` files**: Current entry point is `app/main.py`, others are legacy (`main_old.py`, `main_new.py`)
- **Config files**: Both `app/config.py` (backward compat wrapper) and `app/core/config.py` (actual config) exist
- **Testing**: Async tests use `@pytest.mark.asyncio` decorator (configured in pytest.ini)
- **Logging**: Use `app.utils.logger` for structured logging; verbose mode controlled by `VERBOSE_LOGGING` env var
- **Ambient Audio**: Cache system can persist downloaded ambient sounds across stories to reduce API calls

## Documentation

Comprehensive docs in `docs/`:
- `DEVELOPER_GUIDE.md` - Setup, workflow, testing, deployment
- `FRONTEND_API_GUIDE.md` - Complete REST API reference
- `PROJECT_OVERVIEW.md` - High-level architecture and features
- `IMPLEMENTATION_DETAILS.md` - Technical deep dives
- `docs/features/` - Feature-specific guides (WebRTC, voice cloning, etc.)
- `docs/guides/QUEUE_MANAGEMENT.md` - Queue system architecture

## API Documentation

Interactive docs available when server is running:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health
