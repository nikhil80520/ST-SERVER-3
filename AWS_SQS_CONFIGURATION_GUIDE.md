# AWS SQS Story Generation - Configuration Guide

## Required Environment Variables

### Core AWS SQS Configuration (REQUIRED)
```bash
# Enable SQS-only mode (no local worker fallback)
AWS_USE_SQS_LAMBDA=true

# AWS Credentials
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# SQS Queue Configuration
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/story-generation-queue

# Alternative: Queue name (will construct URL automatically)
# AWS_SQS_QUEUE_NAME=story-generation-queue
# AWS_ACCOUNT_ID=123456789
```

### Database Configuration
```bash
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database
```

### OpenAI API
```bash
OPENAI_API_KEY=sk-...
```

### S3 Storage (for media files)
```bash
AWS_S3_BUCKET_NAME=june_story
```

### Optional Firebase (for backward compatibility)
```bash
FIREBASE_CREDENTIALS_PATH=./firebase-credentials.json
FIREBASE_STORAGE_BUCKET=your-bucket.appspot.com
```

---

## AWS Infrastructure Setup

### 1. Create SQS Queue

```bash
aws sqs create-queue \
    --queue-name story-generation-queue \
    --attributes VisibilityTimeout=1800,ReceiveMessageWaitTimeSeconds=20,MessageRetentionPeriod=345600

# Output: Note the QueueUrl
```

### 2. Create IAM Policy for SQS Access

**File:** `sqs-story-policy.json`
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:us-east-1:123456789:story-generation-queue"
    }
  ]
}
```

```bash
aws iam create-policy \
    --policy-name StoryGenerationSQSPolicy \
    --policy-document file://sqs-story-policy.json
```

### 3. Create IAM User or Role

```bash
# Create user
aws iam create-user --user-name story-generation-worker

# Attach policy
aws iam attach-user-policy \
    --user-name story-generation-worker \
    --policy-arn arn:aws:iam::123456789:policy/StoryGenerationSQSPolicy

# Create access keys
aws iam create-access-key --user-name story-generation-worker
# Note: Save AccessKeyId and SecretAccessKey
```

### 4. Lambda Function Setup (Optional - for AWS processing)

If using Lambda to process SQS messages:

```bash
# Create Lambda execution role
aws iam create-role \
    --role-name story-generation-lambda-role \
    --assume-role-policy-document file://lambda-trust-policy.json

# Attach policies
aws iam attach-role-policy \
    --role-name story-generation-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam attach-role-policy \
    --role-name story-generation-lambda-role \
    --policy-arn arn:aws:iam::123456789:policy/StoryGenerationSQSPolicy

# Create Lambda function (see lambda-deployment/ directory)
```

### 5. Configure SQS Trigger for Lambda

```bash
aws lambda create-event-source-mapping \
    --function-name story-generation-lambda \
    --event-source-arn arn:aws:sqs:us-east-1:123456789:story-generation-queue \
    --batch-size 1 \
    --maximum-batching-window-in-seconds 0
```

---

## SQS Message Schema

### Expected Payload Structure

```json
{
  "job_id": "uuid-v4",
  "story_id": "story_uuid",
  "user_id": "firebase_user_id_string",
  "firebase_user_id": "firebase_user_id_string",
  "parameters": {
    "user_prompt": "Create a magical adventure story",
    "child_id": "child_uuid",
    "child_name": "Alex",
    "child_age": 7,
    "target_scenes": 7,
    "art_style": "watercolor",
    "morals": ["kindness", "friendship"],
    "story_length": "medium",
    "language": "english",
    "voice_option": "female",
    "use_cloned_voice": true,
    "voice_clone_id": "voice_uuid",
    "reference_image_urls": ["https://s3.../image1.png"],
    "reference_images_metadata": [
      {
        "reference_image_id": "ref_uuid",
        "image_url": "https://s3.../image1.png",
        "character_name": "Princess Luna"
      }
    ]
  },
  "created_at": "2025-12-05T10:30:00Z",
  "priority": 0
}
```

### Message Attributes

```json
{
  "StoryId": {
    "StringValue": "story_uuid",
    "DataType": "String"
  },
  "UserId": {
    "StringValue": "firebase_user_id",
    "DataType": "String"
  },
  "Priority": {
    "StringValue": "0",
    "DataType": "Number"
  }
}
```

---

## Lambda Worker Implementation

### Lambda Handler Contract

The Lambda function receives SQS events in this format:

```python
def lambda_handler(event, context):
    """
    Process SQS messages for story generation.
    
    event structure:
    {
      "Records": [
        {
          "messageId": "...",
          "receiptHandle": "...",
          "body": "{...}",  # JSON payload as string
          "attributes": {...},
          "messageAttributes": {...}
        }
      ]
    }
    """
    for record in event['Records']:
        # Parse message body
        payload = json.loads(record['body'])
        
        # Extract fields
        story_id = payload['story_id']
        firebase_user_id = payload['firebase_user_id']
        parameters = payload['parameters']
        
        # Process story generation
        try:
            # Initialize services with database session
            async with get_db_session() as db:
                user_service = UserService()
                story_service = StoryService(openai_client, user_service, db)
                
                # Generate story
                scenes, title, art_style, child_id = await story_service.generate_story_scenes(
                    user_prompt=parameters['user_prompt'],
                    user_id=firebase_user_id,  # Pass firebase_user_id
                    target_scenes=parameters['target_scenes'],
                    child_id=parameters.get('child_id'),
                    # ... other parameters
                )
                
                # Save to database and S3
                # ...
                
        except Exception as e:
            # Update story status with error
            await storage_service.update_story_status(
                story_id,
                "failed",
                error_message=str(e)
            )
            
            # Re-raise to trigger SQS retry
            raise
```

---

## Local Development Setup

### 1. Install Dependencies

```bash
cd C:\Users\asus\Desktop\STServer\STS-Server
.\myenv\Scripts\activate

pip install boto3 moto pytest pytest-asyncio
```

### 2. Update requirements.txt

Add:
```
boto3>=1.28.0
moto>=4.2.0  # For SQS mocking in tests
pytest>=7.4.0
pytest-asyncio>=0.21.0
```

### 3. Configure Environment

Create `.env` file:
```bash
# Copy from template
cp .env.example .env

# Edit .env and add AWS credentials
AWS_USE_SQS_LAMBDA=true
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=YOUR_KEY
AWS_SECRET_ACCESS_KEY=YOUR_SECRET
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT/story-generation-queue
```

### 4. Test SQS Connection

```python
import boto3

sqs = boto3.client(
    'sqs',
    region_name='us-east-1',
    aws_access_key_id='YOUR_KEY',
    aws_secret_access_key='YOUR_SECRET'
)

# List queues
queues = sqs.list_queues()
print(queues)

# Get queue attributes
attrs = sqs.get_queue_attributes(
    QueueUrl='YOUR_QUEUE_URL',
    AttributeNames=['All']
)
print(attrs)
```

---

## Testing Checklist

### Unit Tests
```bash
# Run unit tests
pytest tests/test_story_generation_fixes.py -v

# Expected output:
# ✓ test_get_user_profile_with_firebase_user_id
# ✓ test_story_service_calls_user_profile_correctly
# ✓ test_update_story_status_with_error_message
# ✓ test_validate_sqs_payload_valid
# ✓ test_send_job_to_sqs_success
```

### Integration Test (Local)

1. **Start FastAPI server:**
```bash
uvicorn src.main:app --reload --port 8000
```

2. **Send test request:**
```bash
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{
    "firebase_token": "YOUR_TEST_TOKEN",
    "prompt": "Create a magical adventure story",
    "child_id": "child_uuid",
    "scene_count": 3,
    "art_style": "watercolor"
  }'
```

3. **Expected response:**
```json
{
  "success": true,
  "story_id": "story_uuid",
  "job_id": "job_uuid",
  "status": "processing",
  "websocket_endpoint": "/ws/stories/{token}",
  "tracking_method": "aws_sqs_lambda",
  "processing_engine": "AWS Lambda + SQS"
}
```

4. **Verify SQS message:**
```bash
aws sqs receive-message \
    --queue-url YOUR_QUEUE_URL \
    --max-number-of-messages 1

# Expected: Message with story generation payload
```

### Error Scenarios

1. **Missing SQS configuration:**
```bash
unset AWS_USE_SQS_LAMBDA
# OR
export AWS_USE_SQS_LAMBDA=false

# Send request → Should return 503 with clear error message
```

Expected error:
```json
{
  "detail": "Story generation service not available. AWS SQS Lambda integration is required..."
}
```

2. **Invalid AWS credentials:**
```bash
export AWS_ACCESS_KEY_ID=invalid
# Send request → Should return 503 with SQS submission error
```

---

## Monitoring

### CloudWatch Metrics

Monitor these SQS metrics:
- `ApproximateNumberOfMessagesVisible` - Queued jobs
- `ApproximateNumberOfMessagesNotVisible` - In-flight jobs
- `NumberOfMessagesSent` - Job submission rate
- `NumberOfMessagesReceived` - Processing rate
- `ApproximateAgeOfOldestMessage` - Queue backlog

### Lambda Metrics (if using Lambda)

- `Invocations` - Number of executions
- `Errors` - Failed executions
- `Duration` - Processing time
- `Throttles` - Rate limiting

### Application Logs

Search for:
- `✅ Job submitted to SQS` - Successful submissions
- `❌ Failed to submit job to SQS` - Submission failures
- `❌ Story generation failed` - Processing failures
- `StorageService.update_story_status() got an unexpected keyword argument` - Should not appear after fix

---

## Rollback Plan

If issues occur:

1. **Emergency disable:**
```bash
# Set in production environment
export AWS_USE_SQS_LAMBDA=false

# Result: API will return 503 with clear message
# No broken state, just unavailable until fixed
```

2. **Revert code changes:**
```bash
git revert HEAD
git push
```

3. **Drain SQS queue:**
```bash
# Purge queue (careful - deletes all messages)
aws sqs purge-queue --queue-url YOUR_QUEUE_URL
```

---

## Production Deployment

### Pre-deployment Checklist

- [ ] AWS credentials configured
- [ ] SQS queue created and accessible
- [ ] Environment variables set in production
- [ ] Unit tests passing
- [ ] Integration test successful
- [ ] Lambda function deployed (if using)
- [ ] CloudWatch alarms configured
- [ ] Database migrations applied (if needed)

### Deployment Steps

1. Deploy code to production
2. Set environment variables
3. Restart application
4. Monitor logs for successful SQS submissions
5. Test with low-traffic endpoint
6. Gradually increase traffic
7. Monitor CloudWatch metrics

### Post-deployment Validation

```bash
# 1. Check application health
curl https://your-domain.com/health

# 2. Test story generation
curl -X POST https://your-domain.com/stories/generate \
  -H "Content-Type: application/json" \
  -d '{...}'

# 3. Verify SQS queue
aws sqs get-queue-attributes \
    --queue-url YOUR_QUEUE_URL \
    --attribute-names ApproximateNumberOfMessages

# 4. Check CloudWatch logs
aws logs tail /aws/lambda/story-generation-lambda --follow
```

---

## Support

For issues, check:
1. CloudWatch Logs for detailed error traces
2. SQS Dead Letter Queue (if configured)
3. Application logs: `journalctl -u your-app -f`
4. Database connection pool status

Contact: devathub9 (GitHub)
