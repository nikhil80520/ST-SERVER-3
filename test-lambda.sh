#!/bin/bash
# Test Lambda function end-to-end

set -e

echo "🧪 Testing AWS Lambda Story Generation"
echo "======================================="

# Configuration
QUEUE_URL="https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue"
FUNCTION_NAME="story-generation-worker"

# Generate test IDs
TEST_JOB_ID="test-$(date +%s)"
TEST_STORY_ID="story-test-$(date +%s)"
TEST_USER_ID="test-user-123"

echo ""
echo "📋 Test Configuration:"
echo "   Job ID: $TEST_JOB_ID"
echo "   Story ID: $TEST_STORY_ID"
echo "   Queue: story-generation-queue"
echo ""

# Step 1: Check initial queue state
echo "1️⃣  Checking initial queue state..."
INITIAL_MESSAGES=$(aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)
echo "   Messages in queue: $INITIAL_MESSAGES"

# Step 2: Send test message to SQS
echo ""
echo "2️⃣  Sending test message to SQS..."

# Create test message payload
TEST_MESSAGE=$(cat <<EOF
{
  "job_id": "$TEST_JOB_ID",
  "story_id": "$TEST_STORY_ID",
  "user_id": "$TEST_USER_ID",
  "parameters": {
    "user_prompt": "A brave little fox who learns to share",
    "child_name": "TestChild",
    "child_age": 6,
    "target_scenes": 3,
    "morals": ["kindness", "sharing"],
    "story_length": "short",
    "art_style": "magical",
    "voice_option": "female",
    "dimensions": "1024x1024",
    "use_cloned_voice": false,
    "language": "english",
    "genre": ["Adventure"],
    "age_group": "6-8",
    "moral_lesson": "sharing",
    "emotion": "happiness"
  },
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "priority": 0
}
EOF
)

# Send message
MESSAGE_ID=$(aws sqs send-message \
  --queue-url $QUEUE_URL \
  --message-body "$TEST_MESSAGE" \
  --query 'MessageId' \
  --output text)

echo "   ✅ Message sent! ID: $MESSAGE_ID"

# Step 3: Wait for Lambda to pick up message
echo ""
echo "3️⃣  Waiting for Lambda to process (10 seconds)..."
sleep 10

# Check if message was consumed
VISIBLE=$(aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages \
  --query 'Attributes.ApproximateNumberOfMessages' \
  --output text)

NOT_VISIBLE=$(aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessagesNotVisible \
  --query 'Attributes.ApproximateNumberOfMessagesNotVisible' \
  --output text)

echo "   Messages visible: $VISIBLE"
echo "   Messages processing: $NOT_VISIBLE"

if [ "$NOT_VISIBLE" -gt "0" ]; then
    echo "   ✅ Lambda is processing the message!"
else
    echo "   ⚠️  Message may not have been picked up yet"
fi

# Step 4: Check Lambda logs
echo ""
echo "4️⃣  Checking Lambda logs..."
echo "   (Showing last 20 lines)"
echo ""

aws logs tail /aws/lambda/$FUNCTION_NAME --since 2m | tail -20

# Step 5: Check Lambda metrics
echo ""
echo "5️⃣  Checking Lambda metrics (last 5 minutes)..."

# Cross-platform date calculation for "5 minutes ago"
# macOS uses BSD date (needs -v), Linux uses GNU date (needs -d)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS BSD date
    START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S)
else
    # Linux GNU date
    START_TIME=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S)
fi
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)

INVOCATIONS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 300 \
  --statistics Sum \
  --query 'Datapoints[0].Sum' \
  --output text)

ERRORS=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=$FUNCTION_NAME \
  --start-time "$START_TIME" \
  --end-time "$END_TIME" \
  --period 300 \
  --statistics Sum \
  --query 'Datapoints[0].Sum' \
  --output text)

echo "   Invocations: ${INVOCATIONS:-0}"
echo "   Errors: ${ERRORS:-0}"

# Summary
echo ""
echo "======================================"
echo "✅ Test Message Submitted!"
echo "======================================"
echo ""
echo "📊 Summary:"
echo "   Story ID: $TEST_STORY_ID"
echo "   Job ID: $TEST_JOB_ID"
echo "   Message ID: $MESSAGE_ID"
echo ""
echo "📝 Monitor the Lambda function:"
echo "   aws logs tail /aws/lambda/$FUNCTION_NAME --follow"
echo ""
echo "🔍 Check story generation (wait 30-60 seconds):"
echo "   This is a test message with minimal parameters."
echo "   The Lambda function will process it, but story may fail"
echo "   if Firebase/API credentials are not properly configured."
echo ""
echo "💡 For production test with real story generation:"
echo "   1. Enable AWS in your server: AWS_USE_SQS_LAMBDA=true"
echo "   2. Use the /stories/generate API endpoint"
echo "   3. Submit a real story request with valid Firebase token"
echo ""
