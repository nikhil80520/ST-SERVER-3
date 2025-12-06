# Story Generation Pipeline - Complete Fix Summary

## Overview
This document provides exact patches for all fixes to make the story-generation pipeline use **AWS SQS only** and resolve all runtime errors.

---

## Issue #1: UserService.get_user_profile() Missing Argument

### Root Cause
`StoryService.generate_story_scenes()` calls `self.user_service.get_user_profile(user_id)` but `UserService` (from `service_pg.py`) requires `get_user_profile(db, firebase_user_id)`.

**Error:**
```
TypeError: UserService.get_user_profile() missing 1 required positional argument: 'firebase_user_id'
```

### Fix Applied

**File:** `src/story/service.py`

#### Patch 1: Add db_session to constructor
```python
# BEFORE
class StoryService:
    def __init__(self, openai_client: OpenAI, user_service):
        self.openai_client = openai_client
        self.user_service = user_service

# AFTER
class StoryService:
    def __init__(self, openai_client: OpenAI, user_service, db_session=None):
        self.openai_client = openai_client
        self.user_service = user_service
        self.db_session = db_session  # Database session for user profile queries
```

#### Patch 2: Fix get_user_profile call (line ~88)
```python
# BEFORE
user_profile = await self.user_service.get_user_profile(user_id)

# AFTER
# user_id here is firebase_user_id (string)
if not self.db_session:
    raise HTTPException(status_code=500, detail="Database session not available for user profile fetch")

user_profile = await self.user_service.get_user_profile(self.db_session, user_id)
```

**File:** `src/story/routes.py`

#### Patch 3: Update dependency injection (line ~68)
```python
# BEFORE
def get_story_service(
    openai_client: OpenAI = Depends(get_openai_client),
    user_service_dep = Depends(get_user_service)
):
    return StoryService(openai_client, user_service_dep)

# AFTER
def get_story_service(
    openai_client: OpenAI = Depends(get_openai_client),
    user_service_dep = Depends(get_user_service),
    db: AsyncSession = Depends(get_session)
):
    return StoryService(openai_client, user_service_dep, db)
```

---

## Issue #2: StorageService.update_story_status() Unexpected Keyword Argument

### Root Cause
`enhanced_background_service.py` calls `update_story_status(story_id, "failed", error_message="...")` but `StorageService.update_story_status(story_id, status)` doesn't accept `error_message` parameter.

**Error:**
```
StorageService.update_story_status() got an unexpected keyword argument 'error_message'
```

### Fix Applied

**File:** `src/common_function/storage_service.py`

#### Patch: Update method signature (line ~1773)
```python
# BEFORE
async def update_story_status(self, story_id: str, status: str):
    """Update story playback status"""
    try:
        if not self.db:
            print("⚠️ Firestore not available - skipping status update")
            return
        
        # Run update in thread pool
        loop = get_or_create_event_loop()
        
        def update_status_sync():
            doc_ref = self.db.collection('stories').document(story_id)
            doc_ref.update({
                'playback_status': status,
                'last_played': datetime.utcnow()
            })
        
        await loop.run_in_executor(None, update_status_sync)

# AFTER
async def update_story_status(self, story_id: str, status: str, error_message: Optional[str] = None):
    """Update story playback status and optionally record error message"""
    try:
        if not self.db:
            print("⚠️ Firestore not available - skipping status update")
            return
        
        # Run update in thread pool
        loop = get_or_create_event_loop()
        
        def update_status_sync():
            doc_ref = self.db.collection('stories').document(story_id)
            update_data = {
                'playback_status': status,
                'last_played': datetime.utcnow()
            }
            if error_message:
                update_data['error_message'] = error_message
                update_data['failed_at'] = datetime.utcnow()
            doc_ref.update(update_data)
        
        await loop.run_in_executor(None, update_status_sync)
```

**Import Addition (top of file):**
```python
from typing import Dict, Any, List, Tuple, Optional  # Add Optional
```

---

## Issue #3: Force SQS-Only Mode (No Local Fallback)

### Requirements
- Fail fast with clear error if SQS not configured
- No local worker fallback
- Return HTTP 503 with actionable message

### Fix Applied

**File:** `src/story/routes.py`

#### Patch: Replace local fallback with SQS enforcement (line ~506)
```python
# BEFORE (had local worker fallback)
if use_sqs and sqs_queue_service.enabled:
    # AWS SQS + Lambda
    job_id = await sqs_queue_service.submit_story_job(...)
else:
    # Local background workers (REMOVED)
    enhanced_background_service = EnhancedBackgroundTaskService(max_workers=3)
    ...

# AFTER (SQS-only enforcement)
# ===== AWS SQS + Lambda ONLY - NO LOCAL FALLBACK =====
# Enforce SQS-only mode for production reliability and scalability

# Validate SQS configuration
if not use_sqs or not sqs_queue_service.enabled:
    error_msg = (
        "Story generation service not available. "
        "AWS SQS Lambda integration is required. "
        "Configuration missing: Set AWS_USE_SQS_LAMBDA=true and configure "
        "AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SQS_QUEUE_URL"
    )
    print(f"❌ {error_msg}")
    raise HTTPException(
        status_code=503,
        detail=error_msg
    )

# Submit job to AWS SQS (cloud processing)
print(f"📤 Submitting job to AWS SQS for Lambda processing...")
try:
    job_id = await sqs_queue_service.submit_story_job(
        story_id=story_id,
        parameters=job_params,
        priority=0
    )
    tracking_method = "aws_sqs_lambda"
    print(f"✅ Job submitted to SQS: {job_id}")
except Exception as e:
    print(f"❌ Failed to submit job to SQS: {str(e)}")
    raise HTTPException(
        status_code=503,
        detail=f"Failed to submit story generation job to SQS: {str(e)}"
    )
```

---

## New File: SQS Helper with Retry Logic

**File:** `src/background_process/sqs_helper.py` (NEW FILE)

```python
"""
SQS Helper - Robust job submission with exponential backoff retry
"""
import json
import time
import boto3
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
from src.core.config import settings
from src.common_function.logger import get_logger

logger = get_logger(__name__)


async def send_job_to_sqs(
    payload: Dict[str, Any],
    queue_url: str,
    max_retries: int = 3,
    initial_backoff: float = 1.0
) -> str:
    """
    Send story generation job to AWS SQS with exponential backoff retry.
    
    Retries on: ServiceUnavailable, ThrottlingException, RequestLimitExceeded, etc.
    Fails immediately on: AccessDenied, InvalidParameterValue, etc.
    """
    # Validate payload
    validate_sqs_payload(payload)
    
    # Initialize SQS client
    sqs_client = boto3.client(
        'sqs',
        region_name=settings.aws.region,
        aws_access_key_id=settings.aws.access_key_id,
        aws_secret_access_key=settings.aws.secret_access_key
    )
    
    # Message attributes
    message_attributes = {
        'StoryId': {'StringValue': payload['story_id'], 'DataType': 'String'},
        'UserId': {'StringValue': payload.get('firebase_user_id', 'unknown'), 'DataType': 'String'},
        'Priority': {'StringValue': str(payload.get('priority', 0)), 'DataType': 'Number'}
    }
    
    # Retry loop
    last_error = None
    for attempt in range(max_retries):
        try:
            response = sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(payload, default=str),
                MessageAttributes=message_attributes
            )
            return response.get('MessageId')
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            # Non-retryable errors
            if error_code not in ['ServiceUnavailable', 'ThrottlingException', 'RequestLimitExceeded', 'InternalError', 'RequestTimeout']:
                raise RuntimeError(f"SQS submission failed [{error_code}]: {str(e)}")
            
            # Retry with backoff
            last_error = e
            backoff_delay = initial_backoff * (2 ** attempt)
            if attempt < max_retries - 1:
                time.sleep(backoff_delay)
    
    raise RuntimeError(f"Failed to submit job to SQS after {max_retries} attempts: {str(last_error)}")


def validate_sqs_payload(payload: Dict[str, Any]) -> None:
    """Validate SQS job payload contains all required fields."""
    required_fields = {
        'story_id': str,
        'user_id': str,
        'firebase_user_id': str,
        'parameters': dict
    }
    
    for field, expected_type in required_fields.items():
        if field not in payload:
            raise ValueError(f"Missing required field: {field}")
        if not isinstance(payload[field], expected_type):
            raise ValueError(f"Invalid type for {field}")
    
    # Validate parameters
    params = payload['parameters']
    required_params = ['user_prompt', 'child_id', 'target_scenes']
    missing_params = [p for p in required_params if p not in params]
    if missing_params:
        raise ValueError(f"Missing required parameters: {missing_params}")
```

---

## Environment Variables Required

### Minimum Configuration
```bash
# Enable SQS mode (REQUIRED)
AWS_USE_SQS_LAMBDA=true

# AWS Credentials (REQUIRED)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# SQS Queue (REQUIRED)
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/story-generation-queue

# Database (REQUIRED)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db

# OpenAI (REQUIRED)
OPENAI_API_KEY=sk-...

# S3 Storage (REQUIRED)
AWS_S3_BUCKET_NAME=june_story
```

---

## Testing

### Run Unit Tests
```bash
cd C:\Users\asus\Desktop\STServer\STS-Server
.\myenv\Scripts\activate
pytest tests/test_story_generation_fixes.py -v
```

### Local Integration Test
```bash
# 1. Set environment variables
export AWS_USE_SQS_LAMBDA=true
export AWS_REGION=us-east-1
export AWS_SQS_QUEUE_URL=https://sqs...
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# 2. Start server
uvicorn src.main:app --reload

# 3. Send test request
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{
    "firebase_token": "YOUR_TOKEN",
    "prompt": "Create a magical adventure",
    "child_id": "child_uuid",
    "scene_count": 3
  }'

# 4. Expected response
{
  "success": true,
  "story_id": "...",
  "job_id": "...",
  "processing_engine": "AWS Lambda + SQS"
}

# 5. Verify SQS message
aws sqs receive-message --queue-url YOUR_QUEUE_URL
```

### Test Error Scenarios

**Test 1: Missing SQS config**
```bash
unset AWS_USE_SQS_LAMBDA
# OR
export AWS_USE_SQS_LAMBDA=false

# Request → Expected: HTTP 503 with clear error message
```

**Test 2: Invalid AWS credentials**
```bash
export AWS_ACCESS_KEY_ID=invalid
# Request → Expected: HTTP 503 "Failed to submit job to SQS"
```

---

## Files Changed Summary

| File | Lines Changed | Type |
|------|---------------|------|
| `src/story/service.py` | ~15 | Modified |
| `src/story/routes.py` | ~35 | Modified |
| `src/common_function/storage_service.py` | ~12 | Modified |
| `src/background_process/sqs_helper.py` | ~150 | New file |
| `tests/test_story_generation_fixes.py` | ~350 | New file |
| `AWS_SQS_CONFIGURATION_GUIDE.md` | ~500 | New doc |

---

## Verification Checklist

After applying patches:

- [ ] No `UserService.get_user_profile() missing argument` errors
- [ ] No `update_story_status() got unexpected keyword argument` errors
- [ ] SQS-only mode enforced (no local fallback)
- [ ] HTTP 503 returned when SQS not configured
- [ ] Unit tests passing
- [ ] Integration test successful
- [ ] SQS messages visible in queue
- [ ] Error messages recorded in Firestore with `error_message` field

---

## Rollback Instructions

If issues occur:

```bash
# Quick disable (makes API return 503 - safe state)
export AWS_USE_SQS_LAMBDA=false

# OR revert code
git revert <commit-hash>
```

---

## Next Steps

1. Apply all patches
2. Run unit tests: `pytest tests/test_story_generation_fixes.py -v`
3. Configure AWS environment variables
4. Test locally
5. Deploy to staging
6. Monitor CloudWatch logs
7. Deploy to production

---

## Support

For issues:
- Check CloudWatch Logs: `/aws/lambda/story-generation-lambda`
- Check application logs: `journalctl -u your-app -f`
- Verify SQS queue status: `aws sqs get-queue-attributes`
- Test SQS connection: Use `sqs_helper.send_job_to_sqs()` directly

Contact: devathub9 (GitHub)
