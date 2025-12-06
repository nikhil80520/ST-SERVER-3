#!/bin/bash
# Test API endpoint with fresh Firebase token

set -e

echo "🔐 Generating Fresh Firebase Token & Testing API"
echo "================================================"
echo ""

# Step 1: Generate fresh token
echo "1️⃣  Generating fresh Firebase ID token..."
TOKEN=$(python3 scripts/get-id-token.py 2>/dev/null | grep -A 1 "ID Token" | tail -1 | tr -d '\n' || echo "")

if [ -z "$TOKEN" ] || [ "$TOKEN" == "" ]; then
    echo "   ❌ Failed to generate token"
    echo "   Trying alternative method..."
    
    # Try reading from saved token file
    if [ -f ".test_id_token" ]; then
        TOKEN=$(cat .test_id_token)
        echo "   ✅ Using token from .test_id_token file"
    else
        echo "   ❌ No token available"
        echo ""
        echo "   To generate a token manually:"
        echo "   python3 scripts/get-id-token.py"
        exit 1
    fi
else
    echo "   ✅ Token generated"
fi

echo ""

# Step 2: Test the API endpoint
echo "2️⃣  Testing /stories/generate endpoint..."
echo ""

RESPONSE=$(curl -s -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d "{
    \"firebase_token\": \"$TOKEN\",
    \"prompt\": \"Create a short story about a brave little fox who learns to share with friends\",
    \"child_name\": \"Alex\",
    \"child_age\": 6,
    \"scene_count\": 3,
    \"morals\": [\"sharing\", \"kindness\"],
    \"story_length\": \"short\",
    \"art_style\": \"magical\",
    \"language\": \"english\",
    \"is_female_voice\": true,
    \"should_use_voice_clone\": false,
    \"dimensions\": \"1024x1024\"
  }" 2>&1)

# Check if response contains error
if echo "$RESPONSE" | grep -q '"detail"'; then
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('detail', 'Unknown error'))" 2>/dev/null || echo "$RESPONSE")
    echo "   ❌ API Error: $ERROR"
    echo ""
    echo "   Full response:"
    echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
else
    # Check if it's a success response
    if echo "$RESPONSE" | grep -q '"success"'; then
        SUCCESS=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('success', False))" 2>/dev/null || echo "false")
        if [ "$SUCCESS" == "True" ] || [ "$SUCCESS" == "true" ]; then
            echo "   ✅ API call successful!"
            echo ""
            echo "   Response:"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
            
            # Extract story_id and job_id
            STORY_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('story_id', ''))" 2>/dev/null || echo "")
            JOB_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('job_id', ''))" 2>/dev/null || echo "")
            
            if [ -n "$STORY_ID" ]; then
                echo ""
                echo "📊 Job Details:"
                echo "   Story ID: $STORY_ID"
                echo "   Job ID: $JOB_ID"
                echo ""
                echo "📤 Message should be in SQS queue now"
                echo "   Check queue: aws sqs get-queue-attributes --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue --attribute-names ApproximateNumberOfMessages"
            fi
        else
            echo "   ⚠️  API returned success=false"
            echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
        fi
    else
        echo "   ⚠️  Unexpected response format"
        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"
    fi
fi

echo ""
echo "================================================"
echo "✅ Test Complete"
echo "================================================"

