#!/bin/bash
# Test story generation API with real ID token through AWS Lambda

set -e

echo "🧪 Testing Story Generation API → SQS → Lambda"
echo "=============================================="
echo ""

# Read the ID token from file
if [ ! -f ".test_id_token" ]; then
    echo "❌ .test_id_token file not found. Run: python3 scripts/get-id-token.py"
    exit 1
fi

FIREBASE_TOKEN=$(cat .test_id_token)

echo "📋 Test Configuration:"
echo "   API Endpoint: http://localhost:8000/stories/generate"
echo "   Firebase Token: ${FIREBASE_TOKEN:0:30}..."
echo "   Expected Mode: AWS Lambda + SQS"
echo ""

echo "1️⃣  Submitting story generation request..."
RESPONSE=$(curl -s -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d "{
    \"firebase_token\": \"$FIREBASE_TOKEN\",
    \"prompt\": \"A brave little fox who learns to share with friends\",
    \"child_name\": \"TestChild\",
    \"child_age\": 6,
    \"scene_count\": 3,
    \"morals\": [\"sharing\"],
    \"art_style\": \"magical\"
  }")

echo "$RESPONSE" | python3 -m json.tool
echo ""

# Check if response contains processing_engine
PROCESSING_ENGINE=$(echo "$RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('processing_engine', 'null'))" 2>/dev/null || echo "null")

if [ "$PROCESSING_ENGINE" = "AWS Lambda + SQS" ]; then
    echo "✅ Using AWS Lambda!"
    echo "   Processing Engine: $PROCESSING_ENGINE"

    STORY_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('story_id', ''))" 2>/dev/null)
    JOB_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('job_id', ''))" 2>/dev/null)

    echo "   Story ID: $STORY_ID"
    echo "   Job ID: $JOB_ID"
    echo ""

    echo "2️⃣  Story submitted to SQS queue successfully!"
    echo ""
    echo "3️⃣  Monitor Lambda processing:"
    echo "   aws logs tail /aws/lambda/story-generation-worker --follow"
    echo ""
    echo "4️⃣  Check queue depth:"
    echo "   aws sqs get-queue-attributes --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue --attribute-names ApproximateNumberOfMessages"
    echo ""
    echo "5️⃣  Verify story completion (wait 60-90 seconds):"
    echo "   curl -H \"Authorization: Bearer $FIREBASE_TOKEN\" http://localhost:8000/stories/$STORY_ID"
    echo ""
else
    echo "❌ Not using AWS Lambda!"
    echo "   Processing Engine: $PROCESSING_ENGINE"
    echo "   Check .env: AWS_USE_SQS_LAMBDA should be 'true'"
    echo ""
fi
