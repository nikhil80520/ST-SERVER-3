#!/bin/bash
# Simple test script for API endpoint
# This script will help you test with a fresh token

echo "🧪 Testing Story Generation API Endpoint"
echo "=========================================="
echo ""

# Check if token file exists
if [ -f ".test_id_token" ]; then
    TOKEN=$(cat .test_id_token)
    echo "✅ Found token in .test_id_token"
else
    echo "⚠️  No token file found. Generating fresh token..."
    
    # Try to generate token
    if python3 scripts/get-id-token.py > /tmp/token_output.txt 2>&1; then
        TOKEN=$(grep -A 1 "ID Token" /tmp/token_output.txt | tail -1 | tr -d '\n' | tr -d ' ')
        
        if [ -z "$TOKEN" ]; then
            # Try to extract from JSON if script outputs JSON
            TOKEN=$(python3 -c "import json; data=json.load(open('/tmp/token_output.txt')); print(data.get('idToken', ''))" 2>/dev/null || echo "")
        fi
        
        if [ -n "$TOKEN" ]; then
            echo "$TOKEN" > .test_id_token
            echo "✅ Token generated and saved"
        else
            echo "❌ Could not extract token. Check /tmp/token_output.txt"
            echo ""
            echo "Manual steps:"
            echo "1. Run: python3 scripts/get-id-token.py"
            echo "2. Copy the token from output"
            echo "3. Save to .test_id_token: echo 'YOUR_TOKEN' > .test_id_token"
            exit 1
        fi
    else
        echo "❌ Token generation failed. Error:"
        cat /tmp/token_output.txt
        exit 1
    fi
fi

echo ""
echo "📡 Sending request to API..."
echo ""

# Make the API call
curl -X POST http://localhost:8000/stories/generate \
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
  }" | python3 -m json.tool

echo ""
echo "✅ Request sent!"
echo ""
echo "💡 Next steps:"
echo "   - Check server logs for SQS submission confirmation"
echo "   - Check SQS queue: aws sqs get-queue-attributes --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue --attribute-names ApproximateNumberOfMessages"
echo "   - Monitor Lambda: aws logs tail /aws/lambda/story-generation-worker --follow"

