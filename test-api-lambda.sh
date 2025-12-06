#!/bin/bash
# Test Lambda function through the FastAPI /stories/generate endpoint

set -e

echo "🧪 Testing Lambda Function via API"
echo "===================================="
echo ""

# Check if Firebase token is provided
if [ -z "$FIREBASE_TOKEN" ]; then
    echo "❌ Error: FIREBASE_TOKEN environment variable not set"
    echo ""
    echo "Usage:"
    echo "  export FIREBASE_TOKEN='your_firebase_id_token'"
    echo "  ./test-api-lambda.sh"
    echo ""
    echo "Or run with token inline:"
    echo "  FIREBASE_TOKEN='your_token' ./test-api-lambda.sh"
    exit 1
fi

echo "📋 Test Configuration:"
echo "   API Endpoint: http://localhost:8000/stories/generate"
echo "   Firebase Token: ${FIREBASE_TOKEN:0:20}..."
echo "   Expected Mode: AWS Lambda + SQS"
echo ""

# Step 1: Submit story generation request
echo "1️⃣  Submitting story generation request..."

RESPONSE=$(curl -s -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{
    "firebase_token": "'$FIREBASE_TOKEN'",
    "prompt": "A brave little fox who learns to share with friends in the forest",
    "child_name": "TestChild",
    "child_age": 6,
    "scene_count": 3,
    "art_style": "magical",
    "language": "english",
    "is_female_voice": true,
    "should_use_voice_clone": false,
    "dimensions": "1024x1024"
  }')

echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"

# Extract story_id and processing_engine
STORY_ID=$(echo "$RESPONSE" | jq -r '.story_id' 2>/dev/null)
PROCESSING_ENGINE=$(echo "$RESPONSE" | jq -r '.processing_engine' 2>/dev/null)

echo ""
if [ "$PROCESSING_ENGINE" == "AWS Lambda + SQS" ]; then
    echo "✅ Story submitted to AWS Lambda!"
    echo "   Story ID: $STORY_ID"
else
    echo "❌ Not using AWS Lambda!"
    echo "   Processing Engine: $PROCESSING_ENGINE"
    echo "   Check .env: AWS_USE_SQS_LAMBDA should be 'true'"
    exit 1
fi

# Step 2: Check SQS queue
echo ""
echo "2️⃣  Checking SQS queue..."
QUEUE_URL="https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue"

QUEUE_MESSAGES=$(aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible \
  --query 'Attributes' \
  --output json)

VISIBLE=$(echo $QUEUE_MESSAGES | jq -r '.ApproximateNumberOfMessages')
NOT_VISIBLE=$(echo $QUEUE_MESSAGES | jq -r '.ApproximateNumberOfMessagesNotVisible')

echo "   Messages in queue: $VISIBLE"
echo "   Messages processing: $NOT_VISIBLE"

if [ "$NOT_VISIBLE" -gt "0" ] || [ "$VISIBLE" -gt "0" ]; then
    echo "   ✅ Message is in SQS queue"
else
    echo "   ⚠️  No messages in queue (may have been processed already)"
fi

# Step 3: Monitor Lambda logs
echo ""
echo "3️⃣  Monitoring Lambda execution..."
echo "   (Waiting 5 seconds for Lambda to start...)"
sleep 5

echo ""
echo "📡 Recent Lambda Logs:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws logs tail /aws/lambda/story-generation-worker --since 30s | tail -50
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Step 4: Check story status
echo ""
echo "4️⃣  Checking story status..."
sleep 5

STATUS_RESPONSE=$(curl -s "http://localhost:8000/stories/$STORY_ID")
STORY_STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status' 2>/dev/null)

echo "   Story Status: $STORY_STATUS"

if [ "$STORY_STATUS" == "completed" ]; then
    echo "   ✅ Story completed successfully!"
    echo ""
    echo "📖 Story Details:"
    echo "$STATUS_RESPONSE" | jq '.manifest | {title, total_scenes, total_duration}' 2>/dev/null
elif [ "$STORY_STATUS" == "processing" ] || [ "$STORY_STATUS" == "generating_media" ]; then
    echo "   ⏳ Story is still processing..."
    echo ""
    echo "   Continue monitoring with:"
    echo "   aws logs tail /aws/lambda/story-generation-worker --follow"
    echo ""
    echo "   Check status with:"
    echo "   curl http://localhost:8000/stories/$STORY_ID | jq '.status'"
elif [ "$STORY_STATUS" == "failed" ]; then
    echo "   ❌ Story generation failed"
    echo "$STATUS_RESPONSE" | jq '.'
else
    echo "   ℹ️  Status: $STORY_STATUS"
fi

# Summary
echo ""
echo "======================================"
echo "✅ API Test Complete"
echo "======================================"
echo ""
echo "📊 Test Summary:"
echo "   Story ID: $STORY_ID"
echo "   Processing Engine: $PROCESSING_ENGINE"
echo "   Current Status: $STORY_STATUS"
echo ""
echo "📝 Next Steps:"
echo ""
echo "1. Monitor Lambda logs in real-time:"
echo "   aws logs tail /aws/lambda/story-generation-worker --follow"
echo ""
echo "2. Check story status:"
echo "   curl http://localhost:8000/stories/$STORY_ID | jq '.'"
echo ""
echo "3. View CloudWatch metrics:"
echo "   aws lambda get-function --function-name story-generation-worker"
echo ""
echo "4. Check SQS queue depth:"
echo "   aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names All"
echo ""
echo "💡 Estimated completion time: 30-60 seconds"
echo ""
