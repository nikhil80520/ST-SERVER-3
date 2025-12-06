# Test Payloads and Lambda Handler Examples

## Test Payload for /stories/generate Endpoint

### Minimal Test Request
```json
{
  "firebase_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE...",
  "prompt": "Create a magical adventure story about a brave kitten",
  "child_id": "550e8400-e29b-41d4-a716-446655440000",
  "scene_count": 5,
  "art_style": "watercolor",
  "should_use_voice_clone": true
}
```

### Complete Test Request (All Fields)
```json
{
  "firebase_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6IjE...",
  "prompt": "Create a magical adventure story where the child learns about kindness",
  "child_id": "550e8400-e29b-41d4-a716-446655440000",
  "child_name": "Emma",
  "child_age": 7,
  "scene_count": 7,
  "morals": ["kindness", "friendship", "courage"],
  "story_length": "medium",
  "art_style": "watercolor",
  "language": "english",
  "age_group": "6-8",
  "moral_lesson": "Being kind to others makes the world better",
  "emotion": "happiness",
  "is_female_voice": true,
  "should_use_voice_clone": true,
  "voice_clone_id": "voice_660e8400-e29b-41d4-a716-446655440001",
  "voice_option": "female",
  "dimensions": "1024x1024",
  "genre": ["Adventure", "Fantasy"],
  "illustration_style": "watercolor",
  "reference_image_ids": [
    "ref_770e8400-e29b-41d4-a716-446655440002"
  ]
}
```

### Expected Response
```json
{
  "success": true,
  "message": "Story generation started! Connect via WebSocket to receive real-time updates.",
  "story_id": "story_fb8baf31-1234-5678-90ab-cdef12345678",
  "job_id": "e9109af5-1073-4776-93be-cd55141ca40e",
  "status": "processing",
  "estimated_completion_time": "30-60 seconds",
  "websocket_endpoint": "/ws/stories/eyJhbGciOiJSUzI1NiIsImtpZCI6IjE...",
  "tracking_method": "aws_sqs_lambda",
  "processing_engine": "AWS Lambda + SQS"
}
```

---

## SQS Message Payload (What Gets Sent to Queue)

### Complete SQS Payload Structure
```json
{
  "job_id": "e9109af5-1073-4776-93be-cd55141ca40e",
  "story_id": "story_fb8baf31-1234-5678-90ab-cdef12345678",
  "user_id": "GyqJ7OT8RaORyB4PQZZbi8nx6FE2",
  "firebase_user_id": "GyqJ7OT8RaORyB4PQZZbi8nx6FE2",
  "parameters": {
    "user_prompt": "Create a magical adventure story where the child learns about kindness",
    "user_id": "GyqJ7OT8RaORyB4PQZZbi8nx6FE2",
    "child_id": "550e8400-e29b-41d4-a716-446655440000",
    "child_name": "Emma",
    "child_age": 7,
    "morals": ["kindness", "friendship", "courage"],
    "story_length": "medium",
    "art_style": "watercolor",
    "language": "english",
    "target_scenes": 7,
    "voice_option": "female",
    "dimensions": "1024x1024",
    "use_cloned_voice": true,
    "voice_clone_id": "voice_660e8400-e29b-41d4-a716-446655440001",
    "reference_image_ids": ["ref_770e8400-e29b-41d4-a716-446655440002"],
    "reference_image_urls": ["https://s3.amazonaws.com/june_story/ref_images/emma_princess.png"],
    "reference_images_metadata": [
      {
        "reference_image_id": "ref_770e8400-e29b-41d4-a716-446655440002",
        "image_url": "https://s3.amazonaws.com/june_story/ref_images/emma_princess.png",
        "character_name": "Princess Luna",
        "description": "A cheerful princess with long blonde hair"
      }
    ],
    "genre": ["Adventure", "Fantasy"],
    "age_group": "6-8",
    "moral_lesson": "Being kind to others makes the world better",
    "emotion": "happiness",
    "is_female_voice": true
  },
  "created_at": "2025-12-05T16:45:50.123456Z",
  "priority": 0
}
```

### SQS Message Attributes
```json
{
  "StoryId": {
    "StringValue": "story_fb8baf31-1234-5678-90ab-cdef12345678",
    "DataType": "String"
  },
  "UserId": {
    "StringValue": "GyqJ7OT8RaORyB4PQZZbi8nx6FE2",
    "DataType": "String"
  },
  "Priority": {
    "StringValue": "0",
    "DataType": "Number"
  }
}
```

---

## Lambda Handler Implementation

### Complete Lambda Function (lambda_handler.py)

```python
"""
AWS Lambda Handler for Story Generation
Processes SQS messages and generates stories using ParallelStoryService
"""
import json
import asyncio
import traceback
from datetime import datetime
from typing import Dict, Any

# AWS Lambda Python 3.11 runtime
# Dependencies: openai, boto3, sqlalchemy, asyncpg, httpx


async def process_story_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process story generation from SQS payload.
    
    Args:
        payload: SQS message body parsed as dict
        
    Returns:
        Result dict with status and manifest
    """
    # Import services (lazy import to reduce cold start)
    from src.user.service_pg import UserService
    from src.story.service import StoryService
    from src.common_function.media_service import MediaService
    from src.common_function.storage_s3_service import S3StorageService
    from src.background_process.parallel_story_service import ParallelStoryService
    from src.db import get_async_session_context
    from openai import OpenAI
    from src.core.config import settings
    
    # Extract fields
    story_id = payload['story_id']
    firebase_user_id = payload['firebase_user_id']
    parameters = payload['parameters']
    
    print(f"🎬 Starting story generation - StoryId: {story_id}, User: {firebase_user_id}")
    
    # Initialize OpenAI client
    openai_client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0
    )
    
    # Initialize services with database session
    async with get_async_session_context() as db:
        user_service = UserService()
        storage_service = S3StorageService()
        media_service = MediaService(openai_client)
        
        # CRITICAL: Pass db_session to StoryService
        story_service = StoryService(openai_client, user_service, db_session=db)
        
        # Create parallel story service
        parallel_service = ParallelStoryService(
            story_service,
            media_service,
            storage_service
        )
        
        try:
            # Generate story using parallel processing
            print(f"📝 Generating story scenes...")
            manifest = await parallel_service.generate_story_parallel(
                story_id=story_id,
                user_prompt=parameters['user_prompt'],
                user_id=firebase_user_id,  # Pass firebase_user_id
                target_scenes=parameters.get('target_scenes', 7),
                child_id=parameters.get('child_id'),
                child_name=parameters.get('child_name'),
                child_age=parameters.get('child_age'),
                morals=parameters.get('morals', ['kindness', 'friendship']),
                story_length=parameters.get('story_length', 'medium'),
                art_style=parameters.get('art_style', 'watercolor'),
                voice_option=parameters.get('voice_option', 'female'),
                dimensions=parameters.get('dimensions', '1024x1024'),
                use_cloned_voice=parameters.get('use_cloned_voice', True),
                voice_clone_id=parameters.get('voice_clone_id'),
                language=parameters.get('language', 'english'),
                reference_image_urls=parameters.get('reference_image_urls', []),
                reference_images_metadata=parameters.get('reference_images_metadata', []),
                # Legacy parameters
                genre=parameters.get('genre', ['Adventure']),
                age_group=parameters.get('age_group', '6-8'),
                moral_lesson=parameters.get('moral_lesson', 'friendship'),
                emotion=parameters.get('emotion', 'happiness')
            )
            
            print(f"✅ Story generation completed successfully - StoryId: {story_id}")
            
            # Send WebSocket notification (optional - if API Gateway WebSocket configured)
            try:
                await send_websocket_notification(firebase_user_id, {
                    "event": "story_completed",
                    "story_id": story_id,
                    "title": manifest.get("title", "Untitled Story"),
                    "manifest": manifest,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as ws_error:
                print(f"⚠️ WebSocket notification failed (non-critical): {str(ws_error)}")
            
            return {
                "status": "completed",
                "story_id": story_id,
                "title": manifest.get("title"),
                "manifest": manifest
            }
            
        except Exception as e:
            # Handle story generation failure
            error_message = f"{type(e).__name__}: {str(e)}"
            print(f"❌ Story generation failed - StoryId: {story_id}")
            print(f"Error: {error_message}")
            print(f"Traceback: {traceback.format_exc()}")
            
            # Update story status with error message
            try:
                await storage_service.update_story_status(
                    story_id,
                    "failed",
                    error_message=error_message[:500]  # Limit error message length
                )
                print(f"✅ Story status updated to failed with error message")
            except Exception as status_error:
                print(f"⚠️ Failed to update story status: {str(status_error)}")
            
            # Send failure notification via WebSocket
            try:
                await send_websocket_notification(firebase_user_id, {
                    "event": "story_failed",
                    "story_id": story_id,
                    "error": error_message,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as ws_error:
                print(f"⚠️ WebSocket failure notification failed: {str(ws_error)}")
            
            # Re-raise to trigger SQS retry (message will be redelivered)
            raise


async def send_websocket_notification(user_id: str, message: Dict[str, Any]) -> None:
    """
    Send WebSocket notification via API Gateway.
    
    Note: Requires API Gateway WebSocket API with connection mapping table.
    """
    import boto3
    
    # Get connection ID from DynamoDB (example)
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('websocket-connections')
    
    try:
        response = table.get_item(Key={'userId': user_id})
        if 'Item' not in response:
            print(f"⚠️ No active WebSocket connection for user {user_id}")
            return
        
        connection_id = response['Item']['connectionId']
        
        # Send message via API Gateway Management API
        api_gateway = boto3.client(
            'apigatewaymanagementapi',
            endpoint_url=f"https://{settings.aws.api_gateway_id}.execute-api.{settings.aws.region}.amazonaws.com/production"
        )
        
        api_gateway.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(message).encode('utf-8')
        )
        
        print(f"✅ WebSocket notification sent to user {user_id}")
        
    except Exception as e:
        print(f"⚠️ WebSocket notification failed: {str(e)}")
        # Don't raise - this is non-critical


def lambda_handler(event, context):
    """
    AWS Lambda entry point.
    
    Event structure (SQS):
    {
      "Records": [
        {
          "messageId": "...",
          "receiptHandle": "...",
          "body": "{...}",
          "attributes": {...},
          "messageAttributes": {...}
        }
      ]
    }
    """
    print(f"🚀 Lambda invoked - Records: {len(event.get('Records', []))}")
    
    results = []
    
    for record in event['Records']:
        try:
            # Parse SQS message body
            payload = json.loads(record['body'])
            
            print(f"📦 Processing message - StoryId: {payload.get('story_id')}")
            
            # Process story generation (run async)
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(process_story_generation(payload))
            
            results.append({
                "messageId": record['messageId'],
                "status": "success",
                "result": result
            })
            
        except Exception as e:
            # Log error and mark as failed
            error_message = f"{type(e).__name__}: {str(e)}"
            print(f"❌ Lambda processing failed for message {record.get('messageId')}")
            print(f"Error: {error_message}")
            print(f"Traceback: {traceback.format_exc()}")
            
            results.append({
                "messageId": record['messageId'],
                "status": "failed",
                "error": error_message
            })
            
            # Return error to trigger SQS retry
            # SQS will redeliver message after visibility timeout
            raise RuntimeError(f"Story generation failed: {error_message}")
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "processed": len(results),
            "results": results
        })
    }


# Helper function for database session (add to src/db/__init__.py)
"""
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

@asynccontextmanager
async def get_async_session_context():
    # Create async session from your engine
    from src.db import AsyncSessionLocal
    
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
"""
```

---

## Test Using AWS CLI

### Send Test Message to SQS
```bash
# Create test payload file
cat > test_payload.json << 'EOF'
{
  "job_id": "test-job-123",
  "story_id": "test-story-456",
  "user_id": "test-user-789",
  "firebase_user_id": "test-user-789",
  "parameters": {
    "user_prompt": "Create a test story",
    "child_id": "test-child-111",
    "child_name": "Test Child",
    "child_age": 7,
    "target_scenes": 3,
    "morals": ["kindness"],
    "story_length": "short",
    "art_style": "cartoon",
    "language": "english",
    "voice_option": "female",
    "dimensions": "1024x1024",
    "use_cloned_voice": false,
    "reference_image_urls": [],
    "reference_images_metadata": []
  },
  "created_at": "2025-12-05T10:00:00Z",
  "priority": 0
}
EOF

# Send to SQS
aws sqs send-message \
    --queue-url https://sqs.us-east-1.amazonaws.com/123456789/story-generation-queue \
    --message-body file://test_payload.json \
    --message-attributes \
        'StoryId={StringValue=test-story-456,DataType=String}' \
        'UserId={StringValue=test-user-789,DataType=String}' \
        'Priority={StringValue=0,DataType=Number}'

# Expected output:
{
  "MessageId": "abc123...",
  "MD5OfMessageBody": "def456..."
}
```

### Monitor Lambda Logs
```bash
# Tail Lambda logs in real-time
aws logs tail /aws/lambda/story-generation-lambda --follow

# Expected output:
# 🚀 Lambda invoked - Records: 1
# 📦 Processing message - StoryId: test-story-456
# 🎬 Starting story generation - StoryId: test-story-456, User: test-user-789
# 📝 Generating story scenes...
# ✅ Story generation completed successfully - StoryId: test-story-456
```

### Check SQS Queue Status
```bash
# Get queue attributes
aws sqs get-queue-attributes \
    --queue-url https://sqs.us-east-1.amazonaws.com/123456789/story-generation-queue \
    --attribute-names All

# Expected output:
{
  "Attributes": {
    "ApproximateNumberOfMessages": "0",
    "ApproximateNumberOfMessagesNotVisible": "1",
    "ApproximateNumberOfMessagesDelayed": "0"
  }
}
```

---

## Python Test Script (Local Testing)

```python
"""
Local test script to validate SQS integration
Run this to test without actually calling the API
"""
import asyncio
import json
from src.background_process.sqs_helper import send_job_to_sqs, validate_sqs_payload


async def test_sqs_submission():
    """Test SQS job submission with mock payload."""
    
    # Test payload
    payload = {
        "job_id": "local-test-123",
        "story_id": "local-story-456",
        "user_id": "local-user-789",
        "firebase_user_id": "local-user-789",
        "parameters": {
            "user_prompt": "Create a local test story",
            "child_id": "local-child-111",
            "child_name": "Local Test",
            "child_age": 6,
            "target_scenes": 3,
            "morals": ["test"],
            "story_length": "short",
            "art_style": "cartoon",
            "language": "english",
            "voice_option": "female",
            "dimensions": "1024x1024",
            "use_cloned_voice": False,
            "reference_image_urls": [],
            "reference_images_metadata": []
        },
        "created_at": "2025-12-05T10:00:00Z",
        "priority": 0
    }
    
    # Queue URL from environment
    import os
    queue_url = os.getenv('AWS_SQS_QUEUE_URL')
    
    if not queue_url:
        print("❌ AWS_SQS_QUEUE_URL not set")
        return
    
    print("🧪 Testing SQS submission...")
    print(f"Queue: {queue_url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Validate payload first
        validate_sqs_payload(payload)
        print("✅ Payload validation passed")
        
        # Send to SQS
        message_id = await send_job_to_sqs(payload, queue_url)
        print(f"✅ Message sent successfully - MessageId: {message_id}")
        
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_sqs_submission())
```

Run test:
```bash
python test_sqs_local.py
```

---

## cURL Examples

### Test Story Generation Endpoint
```bash
# Get Firebase token first (use your auth method)
TOKEN="eyJhbGciOiJSUzI1NiIsImtpZCI6IjE..."

# Send story generation request
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "firebase_token": "'"$TOKEN"'",
    "prompt": "Create a magical adventure about a brave kitten who helps a lost puppy find its way home",
    "child_id": "550e8400-e29b-41d4-a716-446655440000",
    "scene_count": 5,
    "art_style": "watercolor",
    "should_use_voice_clone": true
  }'
```

### Test Error Response (Missing SQS Config)
```bash
# Temporarily disable SQS
export AWS_USE_SQS_LAMBDA=false

# Send request - should get 503
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{...}'

# Expected response:
{
  "detail": "Story generation service not available. AWS SQS Lambda integration is required..."
}
```

---

## Summary

This document provides:
- ✅ Complete test payloads for API endpoint
- ✅ SQS message format specification
- ✅ Lambda handler implementation with corrected signatures
- ✅ Test scripts for local validation
- ✅ AWS CLI commands for monitoring
- ✅ cURL examples for integration testing

Use these to validate all fixes are working correctly before deploying to production.
