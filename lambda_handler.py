"""
AWS Lambda Handler for Story Generation
Processes SQS messages and generates stories using the parallel story service

Deployment:
1. Package this file with all dependencies (see deployment docs)
2. Deploy to AWS Lambda with appropriate IAM role
3. Configure SQS trigger
4. Set environment variables (Firebase credentials, API keys, etc.)
"""
import json
import os
import asyncio
from datetime import datetime
from typing import Dict, Any


def lambda_handler(event, context):
    """
    AWS Lambda entry point for SQS message processing

    Args:
        event: SQS event containing message(s)
        context: Lambda context object

    Returns:
        Response with processing results
    """
    print(f"🚀 Lambda invoked - RequestId: {context.aws_request_id}")
    print(f"📦 Received {len(event.get('Records', []))} message(s)")

    results = []

    # Process each SQS message
    for record in event.get('Records', []):
        try:
            # Parse message body
            message_body = json.loads(record['body'])
            job_id = message_body.get('job_id')
            story_id = message_body.get('story_id')
            user_id = message_body.get('user_id')
            parameters = message_body.get('parameters', {})

            print(f"📝 Processing job {job_id} for story {story_id}")

            # Run async story generation
            result = asyncio.run(
                process_story_generation(
                    job_id=job_id,
                    story_id=story_id,
                    user_id=user_id,
                    parameters=parameters
                )
            )

            results.append({
                'job_id': job_id,
                'story_id': story_id,
                'status': 'success',
                'result': result
            })

            print(f"✅ Completed job {job_id}")

        except Exception as e:
            error_msg = str(e)
            print(f"❌ Error processing message: {error_msg}")

            results.append({
                'job_id': message_body.get('job_id', 'unknown'),
                'story_id': message_body.get('story_id', 'unknown'),
                'status': 'error',
                'error': error_msg
            })

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': f'Processed {len(results)} job(s)',
            'results': results
        })
    }


async def process_story_generation(
    job_id: str,
    story_id: str,
    user_id: str,
    parameters: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Process a single story generation job

    This function initializes the required services and calls the parallel story service
    """
    print(f"🎬 Starting story generation for {story_id}")

    # Import services (lazy import to avoid cold start overhead)
    from app.services.story_service import StoryService
    from app.services.media_service import MediaService
    from app.services.storage_service import StorageService
    from app.services.parallel_story_service import ParallelStoryService
    from openai import OpenAI
    from app.config import settings

    # Initialize OpenAI client
    openai_client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=60.0
    )

    # Initialize services
    from app.services.user_service import UserService
    user_service = UserService()
    story_service = StoryService(openai_client, user_service)
    media_service = MediaService(openai_client)
    storage_service = StorageService()

    # Create parallel story service
    parallel_service = ParallelStoryService(
        story_service,
        media_service,
        storage_service
    )

    # Update story status to processing
    await storage_service.update_story_status_and_title(story_id, "processing")

    # Send WebSocket notification (if user is connected)
    await send_websocket_notification(user_id, {
        "event": "story_progress",
        "story_id": story_id,
        "status": "processing",
        "progress": 10,
        "message": "Starting story generation...",
        "timestamp": datetime.utcnow().isoformat()
    })

    try:
        # Generate story using parallel processing
        manifest = await parallel_service.generate_story_parallel(
            story_id=story_id,
            user_prompt=parameters.get("user_prompt"),
            user_id=user_id,
            target_scenes=parameters.get("target_scenes", 7),
            child_id=parameters.get("child_id"),
            child_name=parameters.get("child_name"),
            child_age=parameters.get("child_age"),
            morals=parameters.get("morals", ["kindness", "friendship"]),
            story_length=parameters.get("story_length", "medium"),
            art_style=parameters.get("art_style", "magical"),
            voice_option=parameters.get("voice_option", "female"),
            dimensions=parameters.get("dimensions", "1024x1024"),
            use_cloned_voice=parameters.get("use_cloned_voice", True),
            voice_clone_id=parameters.get("voice_clone_id"),
            language=parameters.get("language", "english"),
            reference_image_urls=parameters.get("reference_image_urls", []),
            reference_images_metadata=parameters.get("reference_images_metadata", []),
            # Legacy parameters
            genre=parameters.get("genre", ["Adventure"]),
            age_group=parameters.get("age_group", "6-8"),
            moral_lesson=parameters.get("moral_lesson", "friendship"),
            emotion=parameters.get("emotion", "happiness")
        )

        print(f"✅ Story generation completed for {story_id}")

        # Send completion notification
        await send_websocket_notification(user_id, {
            "event": "story_completed",
            "story_id": story_id,
            "title": manifest.get("title", "Untitled Story"),
            "message": f"Your story '{manifest.get('title', 'Untitled Story')}' is ready!",
            "manifest": manifest,
            "timestamp": datetime.utcnow().isoformat()
        })

        return {
            "story_id": story_id,
            "title": manifest.get("title", "Generated Story"),
            "status": "completed",
            "manifest": manifest
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Story generation failed: {error_msg}")

        # Update story status to failed
        await storage_service.update_story_status_and_title(story_id, "failed")
        
        # Store error message in story document if needed
        # The error is already logged and sent via WebSocket notification

        # Send failure notification
        await send_websocket_notification(user_id, {
            "event": "story_failed",
            "story_id": story_id,
            "message": f"Story generation failed: {error_msg}",
            "error": error_msg,
            "timestamp": datetime.utcnow().isoformat()
        })

        raise


async def send_websocket_notification(user_id: str, message: Dict[str, Any]):
    """
    Send WebSocket notification to user (if connected)

    Note: This requires a WebSocket connection manager that can handle
    notifications from Lambda. You may need to use:
    - API Gateway WebSocket API
    - AWS AppSync
    - Third-party service (Pusher, Ably, etc.)
    """
    try:
        from app.services.story_websocket_manager import story_websocket_manager

        # Check if WebSocket manager is available
        if hasattr(story_websocket_manager, 'broadcast_to_user'):
            await story_websocket_manager.broadcast_to_user(user_id, message)
            print(f"📡 WebSocket notification sent to user {user_id}")
        else:
            print(f"⚠️  WebSocket manager not available in Lambda environment")

    except Exception as e:
        # Non-critical error - log and continue
        print(f"⚠️  Failed to send WebSocket notification: {e}")


# For local testing
if __name__ == "__main__":
    # Sample test event
    test_event = {
        "Records": [
            {
                "messageId": "test-message-id",
                "receiptHandle": "test-receipt-handle",
                "body": json.dumps({
                    "job_id": "test-job-123",
                    "story_id": "story-test-456",
                    "user_id": "test-user-789",
                    "parameters": {
                        "user_prompt": "Create a story about a brave little fox",
                        "child_name": "Alex",
                        "child_age": 6,
                        "target_scenes": 5,
                        "art_style": "magical",
                        "language": "english"
                    },
                    "created_at": datetime.utcnow().isoformat(),
                    "priority": 0
                }),
                "attributes": {},
                "messageAttributes": {},
                "md5OfBody": "",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:story-generation-queue",
                "awsRegion": "us-east-1"
            }
        ]
    }

    # Mock context
    class MockContext:
        aws_request_id = "test-request-id"
        function_name = "story-generation-worker"
        memory_limit_in_mb = 3008
        invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:story-generation-worker"

    # Run test
    print("🧪 Running local test...")
    result = lambda_handler(test_event, MockContext())
    print(f"📊 Result: {json.dumps(result, indent=2)}")
