"""
Local Lambda Worker - Simulates AWS Lambda processing SQS messages
Run this alongside your FastAPI server for local testing

Usage:
    python local_lambda_worker.py
"""
import asyncio
import json
import os
import sys
from datetime import datetime
import boto3
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))


async def process_story_generation(payload: dict):
    """Process story generation job (simulates Lambda handler)"""
    from src.user.service_pg import UserServicePostgreSQL
    from src.story.service import StoryService
    from src.common_function.media_service import MediaService
    from src.common_function.storage_s3_service import S3StorageService
    from src.background_process.parallel_story_service import ParallelStoryService
    from src.db import AsyncSessionLocal
    from openai import OpenAI
    
    story_id = payload['story_id']
    firebase_user_id = payload.get('firebase_user_id') or payload.get('user_id')
    parameters = payload['parameters']
    
    print(f"\n🎬 Starting story generation")
    print(f"   Story ID: {story_id}")
    print(f"   User: {firebase_user_id}")
    print(f"   Prompt: {parameters.get('user_prompt', 'N/A')[:60]}...")
    
    # Initialize OpenAI
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY not set in environment")
    
    openai_client = OpenAI(api_key=openai_api_key, timeout=60.0)
    
    # Initialize services
    async with AsyncSessionLocal() as db:
        user_service = UserServicePostgreSQL()
        storage_service = S3StorageService()
        media_service = MediaService(openai_client)
        story_service = StoryService(openai_client, user_service, db_session=db)
        
        parallel_service = ParallelStoryService(
            story_service,
            media_service,
            storage_service
        )
        
        try:
            # Generate story
            print(f"📖 Generating {parameters.get('target_scenes', 5)} story scenes...")
            
            manifest = await parallel_service.generate_story_parallel(
                story_id=story_id,
                user_prompt=parameters['user_prompt'],
                user_id=firebase_user_id,
                target_scenes=parameters.get('target_scenes', 5),
                child_id=parameters.get('child_id'),
                child_name=parameters.get('child_name'),
                child_age=parameters.get('child_age'),
                morals=parameters.get('morals', ['kindness']),
                story_length=parameters.get('story_length', 'medium'),
                art_style=parameters.get('art_style', 'watercolor'),
                voice_option=parameters.get('voice_option', 'female'),
                dimensions=parameters.get('dimensions', '1024x1024'),
                use_cloned_voice=parameters.get('use_cloned_voice', False),
                voice_clone_id=parameters.get('voice_clone_id'),
                language=parameters.get('language', 'english'),
                reference_image_urls=parameters.get('reference_image_urls', []),
                reference_images_metadata=parameters.get('reference_images_metadata', [])
            )
            
            print(f"✅ Story completed successfully!")
            print(f"   Title: {manifest.get('title', 'Untitled')}")
            print(f"   Scenes: {len(manifest.get('scenes', []))}")
            print(f"   Duration: {manifest.get('total_duration', 0)}s")
            
            return {
                "status": "completed",
                "story_id": story_id,
                "manifest": manifest
            }
            
        except Exception as e:
            print(f"❌ Story generation failed!")
            print(f"   Error: {str(e)}")
            
            # Update story status to failed
            try:
                await storage_service.update_story_status(
                    story_id,
                    "failed",
                    error_message=str(e)[:500]
                )
                print(f"   Updated story status to 'failed'")
            except Exception as status_error:
                print(f"   ⚠️ Could not update story status: {str(status_error)}")
            
            raise


async def poll_sqs_queue():
    """Poll SQS queue and process messages (simulates Lambda trigger)"""
    queue_url = os.getenv('AWS_SQS_QUEUE_URL')
    region = os.getenv('AWS_REGION', 'us-east-1')
    endpoint_url = os.getenv('AWS_ENDPOINT_URL')  # For LocalStack
    
    if not queue_url:
        print("❌ AWS_SQS_QUEUE_URL not set in environment")
        print("   Please set it in your .env file")
        return
    
    print(f"\n{'='*60}")
    print(f"🚀 Local Lambda Worker Started")
    print(f"{'='*60}")
    print(f"📡 Queue: {queue_url}")
    print(f"🌍 Region: {region}")
    if endpoint_url:
        print(f"🏠 Endpoint: {endpoint_url} (LocalStack)")
    else:
        print(f"☁️  Using AWS SQS")
    print(f"⏱️  Polling interval: 20 seconds")
    print(f"⚠️  Press Ctrl+C to stop")
    print(f"{'='*60}\n")
    
    # Create SQS client
    sqs = boto3.client(
        'sqs',
        region_name=region,
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )
    
    message_count = 0
    
    while True:
        try:
            # Poll for messages (long polling = 20 seconds)
            response = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            
            if not messages:
                # No messages - continue polling
                current_time = datetime.now().strftime('%H:%M:%S')
                print(f"⏳ [{current_time}] No messages in queue, polling again...")
                continue
            
            for message in messages:
                message_count += 1
                receipt_handle = message['ReceiptHandle']
                
                try:
                    # Parse message body
                    payload = json.loads(message['Body'])
                    
                    print(f"\n{'─'*60}")
                    print(f"📨 Message #{message_count} received")
                    print(f"   Story ID: {payload.get('story_id', 'unknown')}")
                    print(f"   Job ID: {payload.get('job_id', 'unknown')}")
                    print(f"{'─'*60}")
                    
                    # Process story generation
                    start_time = datetime.now()
                    result = await process_story_generation(payload)
                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    
                    print(f"\n⏱️  Processing time: {duration:.1f} seconds")
                    
                    # Delete message from queue (processed successfully)
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=receipt_handle
                    )
                    print(f"🗑️  Message deleted from queue")
                    print(f"{'─'*60}\n")
                    
                except json.JSONDecodeError as e:
                    print(f"❌ Invalid JSON in message: {str(e)}")
                    # Delete malformed message
                    sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
                    print(f"🗑️  Malformed message deleted\n")
                    
                except Exception as e:
                    print(f"❌ Failed to process message: {str(e)}")
                    print(f"⚠️  Message will return to queue after visibility timeout")
                    print(f"{'─'*60}\n")
                    # Don't delete - let it retry
        
        except KeyboardInterrupt:
            print(f"\n\n{'='*60}")
            print(f"👋 Shutting down worker...")
            print(f"   Processed {message_count} message(s) in this session")
            print(f"{'='*60}\n")
            break
            
        except Exception as e:
            print(f"❌ Error polling queue: {str(e)}")
            print(f"   Retrying in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(poll_sqs_queue())
    except Exception as e:
        print(f"\n❌ Fatal error: {str(e)}")
        sys.exit(1)
