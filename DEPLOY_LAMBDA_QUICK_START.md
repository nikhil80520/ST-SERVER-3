# Quick Start: Deploy and Test AWS Lambda

## Your Setup

✅ You have a complete Lambda deployment folder with:
- Lambda handler code
- Deployment scripts
- SQS queue: `https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue`
- AWS Account ID: `296291473328`

## Step 1: Deploy Lambda Function

```powershell
cd lambda-deployment

# Deploy using Docker (recommended)
bash deploy-docker-lambda.sh

# Or deploy via S3
bash deploy-via-s3.sh
```

This will:
- Package your code with dependencies
- Create/update Lambda function: `story-generation-worker`
- Configure environment variables
- Set up execution role

## Step 2: Configure SQS Trigger

```powershell
# Connect SQS queue to Lambda
bash configure-sqs-trigger.sh
```

This creates the event source mapping so Lambda automatically processes SQS messages.

## Step 3: Test the Integration

### Option A: Test via Your API (End-to-End)

```powershell
# 1. Make sure .env has:
# AWS_USE_SQS_LAMBDA=true
# AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue

# 2. Restart your server
cd ..
uvicorn src.main:app --reload

# 3. Send story generation request via your frontend/API
# The flow will be:
# FastAPI → SQS → Lambda → Story Generated
```

### Option B: Test Lambda Directly

```powershell
cd lambda-deployment

# Test Lambda function directly
bash test-lambda.sh

# Or use Python script
python test-lambda-api.py
```

## Step 4: Monitor Execution

```powershell
# Watch Lambda logs in real-time
aws logs tail /aws/lambda/story-generation-worker --follow

# Check SQS queue status
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue \
  --attribute-names All
```

## Expected Flow

```
1. Your App (FastAPI)
   ↓ POST /stories/generate
   ↓
2. Sends message to SQS
   ✅ Message: {"story_id": 10, "parameters": {...}}
   ↓
3. AWS SQS Queue
   📦 story-generation-queue
   ↓
4. Lambda Trigger (automatic)
   ⚡ story-generation-worker invoked
   ↓
5. Lambda Processes Story
   📖 Generates scenes, images, audio
   💾 Saves to PostgreSQL + S3
   ↓
6. Lambda Completes
   🗑️ Deletes message from queue
   ✅ Done!
```

## Test with Python Script

```powershell
# First, verify SQS is working
python test_sqs_connection.py

# Expected output:
# ✅ Queue exists!
# ✅ Test message sent successfully!
```

## Troubleshooting

### Check Lambda exists
```powershell
aws lambda get-function --function-name story-generation-worker
```

### Check SQS trigger is configured
```powershell
aws lambda list-event-source-mappings --function-name story-generation-worker
```

### View Lambda logs
```powershell
aws logs tail /aws/lambda/story-generation-worker --follow
```

### Check environment variables
```powershell
aws lambda get-function-configuration --function-name story-generation-worker
```

## Quick Deploy Command

If Lambda is already deployed and you just need to update code:

```powershell
cd lambda-deployment
bash force-update.sh
```

---

## Summary

**You have everything ready!** Just run:

```powershell
# 1. Deploy Lambda
cd lambda-deployment
bash deploy-docker-lambda.sh

# 2. Configure SQS trigger
bash configure-sqs-trigger.sh

# 3. Test
cd ..
python test_sqs_connection.py

# 4. If test passes, restart your server and test via API!
```

Your `.env` is already configured with the correct queue URL! 🎉
