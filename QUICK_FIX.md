# Quick Fix: API Endpoint Not Working

## Problem
Your `curl` command is failing because the Firebase token is **expired**.

## Solution

### Option 1: Use the Test Script (Recommended)
```bash
./test-api-simple.sh
```

This script will:
1. Generate a fresh Firebase token
2. Test the API endpoint
3. Show you the response

### Option 2: Generate Token Manually
```bash
# Generate a fresh token
python3 scripts/get-id-token.py

# Copy the token from output and use it in your curl command
```

### Option 3: Get Token from Your Mobile App
If you're using a React Native app, get the token from there:
```javascript
import auth from '@react-native-firebase/auth';
const token = await auth().currentUser.getIdToken();
console.log(token);
```

## Verify Everything Works

1. **Check SQS Queue** (after making API call with valid token):
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue \
  --attribute-names ApproximateNumberOfMessages
```

2. **Monitor Lambda Logs**:
```bash
aws logs tail /aws/lambda/story-generation-worker --follow
```

3. **Check Event Source Mapping**:
```bash
./diagnose-sqs-lambda.sh
```

## Why test-lambda.sh Works But curl Doesn't

- **test-lambda.sh**: Sends messages **directly to SQS** (bypasses server/auth)
- **curl**: Hits your **FastAPI endpoint** which requires **valid Firebase authentication**

## Current Status

✅ SQS trigger is configured and enabled  
✅ Server is configured to use SQS (`AWS_USE_SQS_LAMBDA: True`)  
✅ Lambda function is active  
❌ Your Firebase token is expired (need fresh one)

Once you use a fresh token, the API should work and messages will flow:
```
API Request → Server → SQS Queue → Lambda → Story Generation
```

