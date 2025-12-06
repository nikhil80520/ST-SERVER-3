# STS-Server API Documentation

Complete API reference for the ESP32 Storytelling Server - FastAPI backend with AI-powered story generation, voice synthesis, and IoT device management.

**Base URL:** `http://localhost:8000` (Development) | `https://your-domain.com` (Production)

**API Docs:**
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Table of Contents

1. [Authentication](#authentication)
2. [Story Generation & Management](#story-generation--management)
3. [User Management](#user-management)
4. [Children Management](#children-management)
5. [Voice Cloning](#voice-cloning)
6. [Reference Images](#reference-images)
7. [Story Sharing](#story-sharing)
8. [IoT Device Management](#iot-device-management)
9. [Conversational AI (WebRTC)](#conversational-ai-webrtc)
10. [Analytics](#analytics)

---

## Authentication

All authenticated endpoints require a Firebase ID token passed via:
- **Header:** `Authorization: Bearer <firebase_token>`
- **Body field:** `firebase_token` (for some endpoints)

### Sign Up

**Endpoint:** `POST /auth/signup`

**Description:** Create a new Firebase user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!",
  "display_name": "John Doe"
}
```

**Response:**
```json
{
  "success": true,
  "message": "User account created successfully",
  "firebase_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "AMf-vBwQQ...",
  "expires_in": 3600,
  "user_info": {
    "uid": "abc123",
    "email": "user@example.com",
    "display_name": "John Doe",
    "email_verified": false,
    "created_at": 1699457890000
  }
}
```

### Sign In

**Endpoint:** `POST /auth/signin`

**Description:** Sign in an existing Firebase user and get authentication tokens.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123!"
}
```

**Response:** Same as Sign Up response.

**How It Works:**
1. Uses Firebase REST API to authenticate user
2. Returns ID token (expires in 1 hour) and refresh token
3. Optionally loads user profile from Firestore
4. Sends login notification email

### Refresh Token

**Endpoint:** `POST /auth/refresh-token`

**Description:** Refresh expired ID token using refresh token.

**Request Body:**
```json
{
  "refresh_token": "AMf-vBwQQ..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "firebase_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "AMf-vBwQQ...",
  "expires_in": 3600
}
```

### Password Reset

**Endpoint:** `POST /auth/password-reset`

**Description:** Initiate password reset flow (sends 6-digit OTP via email).

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response:**
```json
{
  "success": true,
  "message": "If an account with this email exists, you will receive a 6-digit verification code."
}
```

**How It Works:**
1. Generates 6-digit OTP code
2. Stores OTP in Firestore with 10-minute expiration
3. Sends OTP via email using configured SMTP server
4. Returns success regardless of email existence (security)

### Validate OTP

**Endpoint:** `POST /auth/validate-otp`

**Request Body:**
```json
{
  "email": "user@example.com",
  "otp": "123456"
}
```

**Response:**
```json
{
  "success": true,
  "message": "OTP verified successfully",
  "valid": true,
  "otp_verified": true,
  "next_step": "call_reset_password_endpoint",
  "email": "user@example.com"
}
```

### Reset Password with OTP

**Endpoint:** `POST /auth/reset-password`

**Request Body:**
```json
{
  "email": "user@example.com",
  "otp": "123456",
  "new_password": "NewSecurePass123!"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Password reset successfully"
}
```

---

## Story Generation & Management

### Generate Story (Async)

**Endpoint:** `POST /stories/generate`

**Description:** Start async story generation with parallel audio and image processing. Returns immediately with story_id while generation continues in background.

**Request Body:**
```json
{
  "firebase_token": "...",
  "prompt": "A magical adventure about friendship",
  "child_name": "Emma",
  "child_age": 7,
  "child_id": "child_abc123",
  "morals": ["kindness", "sharing", "friendship"],
  "story_length": "medium",
  "art_style": "magical",
  "language": "english",
  "scene_count": 7,
  "is_female_voice": true,
  "should_use_voice_clone": true,
  "voice_clone_id": "vc_xyz789",
  "dimensions": "1024x1024",
  "reference_image_ids": ["ref_img_001", "ref_img_002"]
}
```

**Parameters:**
- `prompt`: Story theme/topic (required if no structured parameters)
- `child_name`: Child's name (auto-populated from profile if not provided)
- `child_age`: Child's age
- `child_id`: Specific child profile to use (defaults to user's default child)
- `morals`: Array of moral lessons to include
- `story_length`: "short" (3-5 scenes), "medium" (5-7 scenes), "long" (7-10 scenes)
- `art_style`: "magical", "realistic", "cartoon", "watercolor", "anime"
- `language`: "english", "spanish", "french", etc.
- `scene_count`: Target number of scenes (default: 7)
- `is_female_voice`: Use female narrator voice
- `should_use_voice_clone`: Use cloned voice if available
- `voice_clone_id`: Specific voice clone to use
- `reference_image_ids`: Reference images for character consistency (max 2)

**Response:**
```json
{
  "success": true,
  "message": "Story generation started! Connect via WebSocket to receive real-time updates.",
  "story_id": "story_uuid_123",
  "job_id": "job_uuid_456",
  "status": "processing",
  "estimated_completion_time": "30-60 seconds",
  "websocket_endpoint": "/ws/stories/{firebase_token}",
  "tracking_method": "background_service_with_websocket_notifications"
}
```

**How It Works:**
1. **Validation**: Verifies Firebase token and checks account status (subscription/trial)
2. **User Profile**: Fetches user profile and resolves child information
3. **Reference Images**: Resolves reference image URLs from IDs (max 2 per story)
4. **Job Creation**: Creates background job with all parameters
5. **Initial Manifest**: Saves initial story document in Firestore with status "processing"
6. **Background Processing**:
   - **Phase 1**: GPT-4 generates story structure with scenes
   - **Phase 2**: Parallel media generation (audio via Cartesia + images via SeeDream)
   - **Phase 3**: Parallel upload to Firebase Storage
   - **Phase 4**: Final manifest creation with all URLs
7. **WebSocket Updates**: Real-time progress notifications to connected clients
8. **Completion**: Updates Firestore with complete manifest

**Performance:**
- Sequential (old): ~3-5 minutes
- Parallel (current): ~45 seconds
- Uses `asyncio.gather()` for concurrent operations

### Get Story Status

**Endpoint:** `GET /stories/{story_id}`

**Description:** Get current status of story generation.

**Response (Processing):**
```json
{
  "status": "processing",
  "message": "Story status: processing"
}
```

**Response (Completed):**
```json
{
  "status": "completed",
  "message": "Story 'The Magical Forest Adventure' completed successfully!",
  "manifest": {
    "story_id": "story_uuid_123",
    "title": "The Magical Forest Adventure",
    "user_prompt": "A magical adventure about friendship",
    "total_scenes": 7,
    "total_duration": 215.5,
    "thumbnail_url": "https://storage.googleapis.com/...",
    "scenes": [
      {
        "scene_number": 0,
        "text": "Once upon a time...",
        "visual_prompt": "A sunny forest clearing...",
        "audio_url": "https://storage.googleapis.com/scene_0_audio.ogg",
        "image_url": "https://storage.googleapis.com/scene_0_image.png",
        "start_time": 0,
        "duration": 30.5,
        "includes_child": true
      }
    ],
    "generation_method": "async_background_service_with_websocket_notifications",
    "optimizations": ["parallel_processing", "batch_audio", "parallel_uploads"]
  }
}
```

### Get User Stories

**Endpoint:** `GET /stories/user/stories`

**Description:** Get all stories for authenticated user (recommended method using Authorization header).

**Headers:**
```
Authorization: Bearer <firebase_token>
```

**Query Parameters:**
- `limit`: Number of stories to return (1-100, default: 20)
- `offset`: Number of stories to skip (default: 0)
- `filter`: Filter type - "owned", "shared", "copied", "all" (default: "owned")

**Response:**
```json
{
  "success": true,
  "user_id": "user_123",
  "filter": "owned",
  "stories": [
    {
      "story_id": "story_001",
      "title": "The Magical Forest",
      "thumbnail_url": "https://...",
      "total_scenes": 7,
      "total_duration": 215.5,
      "created_at": "2025-11-27T10:30:00Z",
      "status": "completed"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "has_more": false
  },
  "summary": {
    "total_stories_in_filter": 15,
    "newest_story": {...},
    "stories_this_page": 15
  }
}
```

**How It Works:**
1. Extracts token from `Authorization` header or `firebase_token` query param
2. Fetches user document from Firestore
3. Uses `story_ids` array for efficient querying
4. Supports filtering by story type (owned/shared/copied)
5. Returns paginated results with metadata

### Delete Story

**Endpoint:** `DELETE /stories/delete/{story_id}`

**Request Body:**
```json
{
  "firebase_token": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Story 'The Magical Forest' has been deleted",
  "story_id": "story_001",
  "deleted_at": "now"
}
```

---

## User Management

### Get User Profile

**Endpoint:** `GET /users/profile?firebase_token=...`

**Response:**
```json
{
  "success": true,
  "profile": {
    "user_id": "user_123",
    "email": "user@example.com",
    "parent": {
      "name": "John Doe",
      "avatar_seed": "abc123",
      "avatar_style": "avataaars"
    },
    "child": {
      "name": "Emma",
      "age": 7,
      "interests": ["reading", "animals", "science"],
      "avatar_seed": "xyz789",
      "voice_clone_id": "vc_123"
    },
    "default_child_id": "child_abc123",
    "story_ids": ["story_001", "story_002"],
    "reference_images": [
      {
        "reference_image_id": "ref_001",
        "image_url": "https://...",
        "person_name": "Emma",
        "description": "Young girl with brown hair..."
      }
    ],
    "created_at": "2025-01-15T10:00:00Z"
  }
}
```

### Update User Profile

**Endpoint:** `PUT /users/profile`

**Request Body:**
```json
{
  "firebase_token": "...",
  "parent": {
    "name": "John Updated",
    "avatar_seed": "new_seed"
  },
  "child": {
    "name": "Emma",
    "age": 8,
    "interests": ["reading", "math"]
  }
}
```

---

## Children Management

### Create Child Profile

**Endpoint:** `POST /children`

**Request Body:**
```json
{
  "firebase_token": "...",
  "name": "Sophie",
  "age": 6,
  "interests": ["art", "music", "dancing"],
  "image_base64": "...",
  "avatar_seed": "sophie_seed",
  "avatar_style": "avataaars",
  "system_prompt": "Custom storytelling instructions..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Child profile created successfully",
  "child": {
    "child_id": "child_xyz789",
    "name": "Sophie",
    "age": 6,
    "interests": ["art", "music", "dancing"],
    "avatar_seed": "sophie_seed",
    "image_url": "https://...",
    "story_count": 0,
    "created_at": "2025-11-27T10:00:00Z"
  }
}
```

**How It Works:**
1. Verifies parent authentication
2. Uploads child image to Firebase Storage (if provided)
3. Creates child document in Firestore subcollection
4. Generates unique `child_id`
5. Initializes stats (story_count, reference_image_count)

### Get All Children

**Endpoint:** `GET /children`

**Headers or Query:**
```
Authorization: Bearer <firebase_token>
OR
?firebase_token=...
```

**Response:**
```json
{
  "success": true,
  "children": [
    {
      "child_id": "child_001",
      "name": "Emma",
      "age": 7,
      "story_count": 15,
      "reference_image_count": 2,
      "voice_clone_id": "vc_123"
    },
    {
      "child_id": "child_002",
      "name": "Sophie",
      "age": 6,
      "story_count": 8,
      "reference_image_count": 1
    }
  ],
  "default_child_id": "child_001",
  "total_count": 2
}
```

### Get Child Stories

**Endpoint:** `GET /children/{child_id}/stories?firebase_token=...&limit=20&offset=0`

**Response:**
```json
{
  "success": true,
  "child_id": "child_001",
  "child_name": "Emma",
  "stories": [...],
  "total_count": 15,
  "has_more": false
}
```

### Set Default Child

**Endpoint:** `POST /children/{child_id}/select`

**Request Body:**
```json
{
  "firebase_token": "..."
}
```

**Response:**
```json
{
  "success": true,
  "message": "Child selected successfully",
  "default_child_id": "child_001"
}
```

---

## Voice Cloning

### Create Voice Clone (Multipart - Recommended)

**Endpoint:** `POST /users/voice-clone/create-multipart`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `firebase_token`: Authentication token
- `voice_name`: Name for the voice clone
- `description`: Optional description
- `audio_file`: Audio file (WAV, MP3, M4A, FLAC, OGG, max 25MB)
- `labels`: Optional JSON string (e.g., `{"age": "child", "language": "english"}`)
- `remove_background_noise`: "true" or "false" (default: "true")

**Response:**
```json
{
  "success": true,
  "message": "Voice clone created successfully",
  "voice_clone": {
    "voice_clone_id": "vc_abc123",
    "voice_id": "cartesia_voice_xyz",
    "voice_name": "Mom's Voice",
    "description": "Mother's voice for storytelling",
    "is_active": true,
    "created_at": "2025-11-27T10:00:00Z"
  },
  "audio_format": "wav",
  "audio_size_bytes": 512000
}
```

**How It Works:**
1. Validates audio file format and size
2. Detects actual audio format (doesn't trust client)
3. Uploads to Cartesia API for voice training
4. Creates Firestore document with voice metadata
5. Automatically sets as active voice clone
6. Returns voice_clone_id for future use

### List User Voice Clones

**Endpoint:** `POST /users/voice-clones/list`

**Request Body:**
```json
{
  "firebase_token": "..."
}
```

**Response:**
```json
{
  "user_id": "user_123",
  "voice_clones": [
    {
      "voice_clone_id": "vc_001",
      "voice_id": "cartesia_voice_001",
      "voice_name": "Mom's Voice",
      "description": "Mother's voice",
      "is_active": true,
      "created_at": "2025-10-20T12:00:00Z"
    },
    {
      "voice_clone_id": "vc_002",
      "voice_id": "cartesia_voice_002",
      "voice_name": "Dad's Voice",
      "description": "Father's voice",
      "is_active": false,
      "created_at": "2025-10-21T14:00:00Z"
    }
  ],
  "active_voice_clone_id": "vc_001",
  "default_voice": {
    "voice_id": "79a125e8-cd45-4c13-8a67-188112f4dd22",
    "voice_name": "British Lady (Default)",
    "description": "Professional female narrator voice",
    "is_default": true
  }
}
```

### Set Active Voice Clone

**Endpoint:** `POST /users/voice-clones/set-active`

**Request Body:**
```json
{
  "firebase_token": "...",
  "voice_clone_id": "vc_001"  // or "default" for default voice
}
```

### Delete Voice Clone

**Endpoint:** `POST /users/voice-clones/delete`

**Request Body:**
```json
{
  "firebase_token": "...",
  "voice_clone_id": "vc_002"
}
```

### Preview Voice

**Endpoint:** `POST /users/voice-clones/preview`

**Request Body:**
```json
{
  "firebase_token": "...",
  "voice_clone_id": "vc_001",
  "preview_text": "Hello! This is a preview of my voice."
}
```

**Response:** Binary audio file (audio/mpeg)

---

## Reference Images

Reference images ensure character consistency across all story scenes.

### Upload Reference Image

**Endpoint:** `POST /reference-images/upload`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `file`: Image file (max 10MB)
- `person_name`: Name of person in image
- `relation`: Relationship (e.g., "daughter", "son")
- `firebase_token`: Authentication token

**Response:**
```json
{
  "success": true,
  "message": "Reference image uploaded successfully",
  "reference_image": {
    "reference_image_id": "ref_img_001",
    "image_url": "https://storage.googleapis.com/...",
    "person_name": "Emma",
    "relation": "daughter",
    "ai_description": "Young girl with brown hair, blue eyes, wearing a red dress...",
    "created_at": "2025-11-27T10:00:00Z"
  }
}
```

**How It Works:**
1. Validates image file (max 10MB, min 1KB)
2. Checks user hasn't exceeded limit (5 images max)
3. Uploads to Firebase Storage
4. Generates AI description using LLaVA model (Replicate API)
5. Stores metadata in Firestore
6. Returns reference_image_id for use in story generation

### List Reference Images

**Endpoint:** `GET /reference-images?firebase_token=...`

**Response:**
```json
{
  "success": true,
  "reference_images": [
    {
      "reference_image_id": "ref_img_001",
      "image_url": "https://...",
      "person_name": "Emma",
      "relation": "daughter",
      "ai_description": "...",
      "created_at": "2025-11-27T10:00:00Z"
    }
  ],
  "total_count": 2,
  "max_allowed": 5
}
```

### Delete Reference Image

**Endpoint:** `DELETE /reference-images/{reference_image_id}?firebase_token=...`

---

## Story Sharing

### Enable Story Sharing

**Endpoint:** `POST /stories/share/enable/{story_id}`

**Headers:**
```
Authorization: Bearer <firebase_token>
```

**Request Body (Optional):**
```json
{
  "settings": {
    "allow_copy": true,
    "show_creator": true,
    "track_analytics": true
  },
  "expires_at": "2025-12-31T23:59:59Z"
}
```

**Response:**
```json
{
  "share_url": "storymagic://share/abc123xyz",
  "qr_code_url": "https://storage.googleapis.com/qr_codes/...",
  "share_token": "abc123xyz",
  "expires_at": "2025-12-31T23:59:59Z"
}
```

**How It Works:**
1. Generates unique share token
2. Creates deep link with custom app scheme (`storymagic://`)
3. Generates QR code image and uploads to Firebase Storage
4. Stores sharing settings in Firestore
5. Returns shareable URL that opens directly in app

### View Shared Story

**Endpoint:** `GET /stories/share/view/{share_token}`

**Description:** Anyone with the share token can view story details (no auth required).

**Response:**
```json
{
  "story": {
    "story_id": "story_001",
    "title": "The Magical Forest",
    "thumbnail_url": "https://...",
    "total_scenes": 7,
    "creator_name": "John Doe",
    "created_at": "2025-11-20T10:00:00Z"
  },
  "settings": {
    "allow_copy": true,
    "show_creator": true
  }
}
```

### Copy Shared Story

**Endpoint:** `POST /stories/share/copy/{share_token}`

**Headers:**
```
Authorization: Bearer <firebase_token>
```

**Description:** Copies shared story to authenticated user's "Shared with me" collection.

**Response:**
```json
{
  "success": true,
  "message": "Story copied successfully",
  "story_id": "story_001",
  "copied_to_user": "user_456"
}
```

---

## IoT Device Management

### Claim Device

**Endpoint:** `POST /iot/claim`

**Request Body:**
```json
{
  "claim_token": "abc123xyz456",
  "device_name": "Emma's Storyteller"
}
```

**Response:**
```json
{
  "status": "claimed",
  "user_id": "user_123",
  "device_id": "device_001",
  "device_name": "Emma's Storyteller",
  "device_type": "storyteller"
}
```

**How It Works:**
1. Validates claim token (10-minute TTL)
2. Verifies user authentication
3. Associates device with user account
4. Updates device status to "claimed"
5. Generates device JWT for future authentication

### Get Device Session

**Endpoint:** `POST /iot/session`

**Headers:**
```
Authorization: HMAC {timestamp}:{signature}
```

**Description:** IoT device authenticates using HMAC and receives JWT token.

**Response:**
```json
{
  "device_jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 14400,
  "device_id": "device_001"
}
```

**HMAC Authentication:**
1. Device calculates: `HMAC-SHA256(device_secret, timestamp)`
2. Sends: `Authorization: HMAC {timestamp}:{signature}`
3. Server verifies signature and timestamp (5-minute tolerance)
4. Issues JWT token valid for 4 hours

### Device Heartbeat

**Endpoint:** `POST /iot/heartbeat`

**Headers:**
```
Authorization: Bearer <device_jwt>
```

**Request Body:**
```json
{
  "local_ip": "192.168.1.100",
  "bssid": "AA:BB:CC:DD:EE:FF",
  "rssi": -45,
  "firmware_version": "1.2.0"
}
```

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-11-27T10:30:00Z"
}
```

### List User Devices

**Endpoint:** `GET /iot/devices?firebase_token=...`

**Response:**
```json
{
  "devices": [
    {
      "device_id": "device_001",
      "device_name": "Emma's Storyteller",
      "device_type": "storyteller",
      "status": "claimed",
      "firmware_version": "1.2.0",
      "last_seen_at": "2025-11-27T10:25:00Z",
      "presence": {
        "last_local_ip": "192.168.1.100",
        "last_bssid": "AA:BB:CC:DD:EE:FF",
        "last_rssi": -45
      }
    }
  ],
  "total_count": 1
}
```

---

## Conversational AI (WebRTC)

Real-time voice conversations using Pipecat framework with Deepgram (STT), OpenAI (LLM), and Cartesia (TTS).

### Start Conversation Session

**Endpoint:** `POST /conversation/start-session`

**Request Body:**
```json
{
  "firebase_token": "...",
  "story_id": "story_001",
  "voice_option": "cloned"
}
```

**Response:**
```json
{
  "session_id": "session_abc123",
  "rtc_config": {
    "ice_servers": [
      {"urls": "stun:stun.l.google.com:19302"},
      {"urls": "turn:global.turn.twilio.com:3478", "username": "...", "credential": "..."}
    ]
  },
  "sdp_offer": "v=0\r\no=- ...",
  "expires_at": "2025-11-27T11:30:00Z"
}
```

**How It Works:**
1. Creates WebRTC transport (SmallWebRTC or Daily)
2. Configures STT (Deepgram Nova 2), LLM (GPT-4), TTS (Cartesia Sonic)
3. Sets up VAD (Voice Activity Detection) and smart turn-taking
4. Loads story context into LLM system prompt
5. Generates SDP offer for WebRTC connection
6. Returns ICE servers for NAT traversal

### Send ICE Candidate

**Endpoint:** `POST /conversation/{session_id}/ice-candidate`

**Request Body:**
```json
{
  "candidate": "candidate:...",
  "sdpMid": "0",
  "sdpMLineIndex": 0
}
```

**Architecture:**
```
Mobile App (WebRTC) ←→ Server (Pipecat Pipeline) ←→ AI Services
                                                        ├─ Deepgram (STT)
                                                        ├─ OpenAI (LLM)
                                                        └─ Cartesia (TTS)
```

---

## Analytics

### Get Story Analytics

**Endpoint:** `GET /analytics/story/{story_id}?firebase_token=...`

**Response:**
```json
{
  "story_id": "story_001",
  "view_count": 42,
  "unique_viewers": 15,
  "copy_count": 3,
  "qr_scans": 8,
  "last_viewed_at": "2025-11-27T09:00:00Z"
}
```

### Get User Dashboard

**Endpoint:** `GET /analytics/dashboard?firebase_token=...`

**Response:**
```json
{
  "total_stories": 25,
  "total_views": 350,
  "total_shares": 12,
  "shared_stories": [...],
  "popular_stories": [...]
}
```

---

## Error Codes

| Status Code | Description |
|------------|-------------|
| 200 | Success |
| 201 | Created successfully |
| 204 | No content (successful deletion) |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (invalid/missing token) |
| 402 | Payment required (subscription/trial expired) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not found |
| 409 | Conflict (duplicate resource) |
| 429 | Too many requests (rate limited) |
| 500 | Internal server error |
| 503 | Service unavailable |

---

## WebSocket Events

**Connect:** `ws://localhost:8000/ws/stories/{firebase_token}`

**Events Received:**

```json
{
  "event": "story_progress",
  "story_id": "story_001",
  "status": "generating_audio",
  "progress": 45,
  "message": "Generating scene audio...",
  "timestamp": "2025-11-27T10:15:00Z"
}
```

```json
{
  "event": "story_completed",
  "story_id": "story_001",
  "title": "The Magical Forest",
  "message": "Your story 'The Magical Forest' is ready!",
  "manifest": {...},
  "timestamp": "2025-11-27T10:16:00Z"
}
```

```json
{
  "event": "story_failed",
  "story_id": "story_001",
  "message": "Story generation failed: OpenAI API error",
  "error": "Rate limit exceeded",
  "timestamp": "2025-11-27T10:16:00Z"
}
```

---

## Rate Limiting

- **Story Generation**: 10 requests/minute per user
- **Voice Clone Creation**: 3 requests/hour per user
- **Reference Image Upload**: 5 images total per user
- **IoT Device Claims**: 10 devices total per user

---

## Best Practices

1. **Use Authorization Header**: Prefer `Authorization: Bearer <token>` over body/query params
2. **Handle Token Expiration**: Implement refresh token flow
3. **WebSocket for Real-time**: Connect to WebSocket for story generation progress
4. **Parallel Operations**: Generate multiple stories concurrently (respects rate limits)
5. **Error Handling**: Always check `success` field and handle errors gracefully
6. **Voice Cloning**: Use multipart format for best reliability
7. **Reference Images**: Provide 1-2 images for best character consistency
8. **Story Filters**: Use filter parameter to separate owned/shared/copied stories

---

## Support

- **API Documentation**: http://localhost:8000/docs
- **GitHub Issues**: https://github.com/anthropics/claude-code/issues
- **Email**: support@storymagic.app
