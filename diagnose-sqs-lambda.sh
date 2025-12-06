#!/bin/bash
# Diagnostic script for SQS/Lambda integration issues

set -e

echo "🔍 SQS/Lambda Queue Diagnostic Tool"
echo "===================================="
echo ""

# Configuration
FUNCTION_NAME="story-generation-worker"
QUEUE_URL="https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue"
AWS_REGION="us-east-1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "1️⃣  Checking AWS CLI configuration..."
if command -v aws &> /dev/null; then
    echo "   ✅ AWS CLI is installed"
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "ERROR")
    if [ "$ACCOUNT_ID" != "ERROR" ]; then
        echo "   ✅ AWS credentials configured (Account: $ACCOUNT_ID)"
    else
        echo "   ${RED}❌ AWS credentials not configured${NC}"
        echo "   Run: aws configure"
        exit 1
    fi
else
    echo "   ${RED}❌ AWS CLI is not installed${NC}"
    exit 1
fi
echo ""

echo "2️⃣  Checking Lambda function exists..."
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "   ✅ Lambda function exists: $FUNCTION_NAME"
    
    # Get function state
    FUNCTION_STATE=$(aws lambda get-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$AWS_REGION" \
        --query 'State' \
        --output text 2>/dev/null || echo "Unknown")
    
    FUNCTION_STATE_REASON=$(aws lambda get-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --region "$AWS_REGION" \
        --query 'StateReason' \
        --output text 2>/dev/null || echo "Unknown")
    
    if [ "$FUNCTION_STATE" == "Active" ]; then
        echo "   ✅ Function state: $FUNCTION_STATE"
    else
        echo "   ${YELLOW}⚠️  Function state: $FUNCTION_STATE${NC}"
        echo "   Reason: $FUNCTION_STATE_REASON"
    fi
else
    echo "   ${RED}❌ Lambda function not found: $FUNCTION_NAME${NC}"
    echo "   Deploy the function first using the deployment scripts"
    exit 1
fi
echo ""

echo "3️⃣  Checking SQS queue exists..."
if aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names QueueArn \
    --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "   ✅ SQS queue exists"
    
    # Get queue attributes
    QUEUE_ARN=$(aws sqs get-queue-attributes \
        --queue-url "$QUEUE_URL" \
        --attribute-names QueueArn \
        --region "$AWS_REGION" \
        --query 'Attributes.QueueArn' \
        --output text)
    
    echo "   Queue ARN: $QUEUE_ARN"
    
    # Check message counts
    VISIBLE=$(aws sqs get-queue-attributes \
        --queue-url "$QUEUE_URL" \
        --attribute-names ApproximateNumberOfMessages \
        --region "$AWS_REGION" \
        --query 'Attributes.ApproximateNumberOfMessages' \
        --output text 2>/dev/null || echo "0")
    
    IN_FLIGHT=$(aws sqs get-queue-attributes \
        --queue-url "$QUEUE_URL" \
        --attribute-names ApproximateNumberOfMessagesNotVisible \
        --region "$AWS_REGION" \
        --query 'Attributes.ApproximateNumberOfMessagesNotVisible' \
        --output text 2>/dev/null || echo "0")
    
    echo "   Messages visible: $VISIBLE"
    echo "   Messages in-flight: $IN_FLIGHT"
    
    if [ "$VISIBLE" -gt "0" ]; then
        echo "   ${YELLOW}⚠️  There are $VISIBLE messages waiting in queue${NC}"
    fi
    
    if [ "$IN_FLIGHT" -gt "0" ]; then
        echo "   ${YELLOW}⚠️  There are $IN_FLIGHT messages being processed${NC}"
    fi
else
    echo "   ${RED}❌ SQS queue not found: $QUEUE_URL${NC}"
    exit 1
fi
echo ""

echo "4️⃣  Checking SQS trigger (event source mapping)..."
MAPPINGS=$(aws lambda list-event-source-mappings \
    --function-name "$FUNCTION_NAME" \
    --region "$AWS_REGION" \
    --output json 2>/dev/null || echo "[]")

MAPPING_COUNT=$(echo "$MAPPINGS" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('EventSourceMappings', [])))" 2>/dev/null || echo "0")

if [ "$MAPPING_COUNT" -eq "0" ]; then
    echo "   ${RED}❌ No event source mapping found!${NC}"
    echo "   ${YELLOW}⚠️  This is likely why messages aren't being consumed${NC}"
    echo ""
    echo "   To fix this, run:"
    echo "   cd lambda-deployment"
    echo "   ./configure-sqs-trigger.sh"
    echo ""
else
    echo "   ✅ Found $MAPPING_COUNT event source mapping(s)"
    
    # Get mapping details
    MAPPING_UUID=$(echo "$MAPPINGS" | python3 -c "import sys, json; data=json.load(sys.stdin); mappings=data.get('EventSourceMappings', []); print(mappings[0]['UUID'] if mappings else '')" 2>/dev/null || echo "")
    
    if [ -n "$MAPPING_UUID" ]; then
        MAPPING_DETAILS=$(aws lambda get-event-source-mapping \
            --uuid "$MAPPING_UUID" \
            --region "$AWS_REGION" \
            --output json 2>/dev/null || echo "{}")
        
        STATE=$(echo "$MAPPING_DETAILS" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('State', 'Unknown'))" 2>/dev/null || echo "Unknown")
        STATE_REASON=$(echo "$MAPPING_DETAILS" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('StateTransitionReason', 'Unknown'))" 2>/dev/null || echo "Unknown")
        ENABLED=$(echo "$MAPPING_DETAILS" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('Enabled', False))" 2>/dev/null || echo "false")
        BATCH_SIZE=$(echo "$MAPPING_DETAILS" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('BatchSize', 1))" 2>/dev/null || echo "1")
        
        echo "   UUID: $MAPPING_UUID"
        echo "   State: $STATE"
        echo "   Enabled: $ENABLED"
        echo "   Batch Size: $BATCH_SIZE"
        
        if [ "$STATE" != "Enabled" ]; then
            echo "   ${YELLOW}⚠️  State is not 'Enabled': $STATE${NC}"
            echo "   Reason: $STATE_REASON"
            echo ""
            echo "   To enable, run:"
            echo "   aws lambda update-event-source-mapping \\"
            echo "     --uuid $MAPPING_UUID \\"
            echo "     --enabled \\"
            echo "     --region $AWS_REGION"
        fi
        
        if [ "$ENABLED" == "false" ]; then
            echo "   ${RED}❌ Event source mapping is DISABLED!${NC}"
            echo "   ${YELLOW}⚠️  This is why messages aren't being consumed${NC}"
            echo ""
            echo "   To enable, run:"
            echo "   aws lambda update-event-source-mapping \\"
            echo "     --uuid $MAPPING_UUID \\"
            echo "     --enabled \\"
            echo "     --region $AWS_REGION"
        fi
    fi
fi
echo ""

echo "5️⃣  Checking Lambda IAM permissions..."
# Get Lambda execution role
ROLE_ARN=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$AWS_REGION" \
    --query 'Role' \
    --output text 2>/dev/null || echo "")

if [ -n "$ROLE_ARN" ]; then
    echo "   Lambda execution role: $ROLE_ARN"
    ROLE_NAME=$(echo "$ROLE_ARN" | sed 's/.*\///')
    
    # Check if role has SQS permissions
    ATTACHED_POLICIES=$(aws iam list-attached-role-policies \
        --role-name "$ROLE_NAME" \
        --output json 2>/dev/null || echo "{}")
    
    POLICY_COUNT=$(echo "$ATTACHED_POLICIES" | python3 -c "import sys, json; data=json.load(sys.stdin); print(len(data.get('AttachedPolicies', [])))" 2>/dev/null || echo "0")
    
    echo "   Attached policies: $POLICY_COUNT"
    
    if echo "$ATTACHED_POLICIES" | grep -q "AWSLambdaSQSQueueExecutionRole"; then
        echo "   ✅ Has AWSLambdaSQSQueueExecutionRole policy (recommended)"
    else
        echo "   ${YELLOW}⚠️  May not have SQS execution permissions${NC}"
        echo "   Lambda needs permission to:"
        echo "     - sqs:ReceiveMessage"
        echo "     - sqs:DeleteMessage"
        echo "     - sqs:GetQueueAttributes"
    fi
else
    echo "   ${RED}❌ Could not get Lambda execution role${NC}"
fi
echo ""

echo "6️⃣  Checking recent Lambda invocations..."
# Cross-platform date calculation for "5 minutes ago"
if [[ "$OSTYPE" == "darwin"* ]]; then
    START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S)
else
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
    --region "$AWS_REGION" \
    --query 'Datapoints[0].Sum' \
    --output text 2>/dev/null || echo "0")

ERRORS=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Errors \
    --dimensions Name=FunctionName,Value=$FUNCTION_NAME \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --period 300 \
    --statistics Sum \
    --region "$AWS_REGION" \
    --query 'Datapoints[0].Sum' \
    --output text 2>/dev/null || echo "0")

if [ "$INVOCATIONS" != "None" ] && [ -n "$INVOCATIONS" ] && [ "$INVOCATIONS" != "0" ]; then
    echo "   ✅ Lambda has been invoked recently"
    echo "   Invocations (last 5 min): ${INVOCATIONS:-0}"
    echo "   Errors (last 5 min): ${ERRORS:-0}"
    
    if [ "$ERRORS" != "None" ] && [ -n "$ERRORS" ] && [ "$ERRORS" != "0" ]; then
        echo "   ${RED}❌ Lambda has errors! Check CloudWatch logs${NC}"
    fi
else
    echo "   ${YELLOW}⚠️  No Lambda invocations in the last 5 minutes${NC}"
    echo "   This confirms messages are not being consumed"
fi
echo ""

echo "7️⃣  Checking CloudWatch Logs (last 10 lines)..."
LOG_GROUP="/aws/lambda/$FUNCTION_NAME"
if aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --query 'logGroups[0].logGroupName' --output text 2>/dev/null | grep -q "$LOG_GROUP"; then
    echo "   ✅ Log group exists"
    echo "   Recent logs:"
    aws logs tail "$LOG_GROUP" --since 10m --format short 2>/dev/null | tail -10 || echo "   (No recent logs)"
else
    echo "   ${YELLOW}⚠️  Log group not found or empty${NC}"
fi
echo ""

echo "===================================="
echo "📋 Summary & Recommendations"
echo "===================================="
echo ""

if [ "$MAPPING_COUNT" -eq "0" ]; then
    echo "${RED}❌ CRITICAL: No SQS trigger configured${NC}"
    echo "   Run: cd lambda-deployment && ./configure-sqs-trigger.sh"
    echo ""
fi

if [ "$ENABLED" == "false" ] 2>/dev/null; then
    echo "${RED}❌ CRITICAL: Event source mapping is disabled${NC}"
    echo "   Enable it with the command shown above"
    echo ""
fi

if [ "$VISIBLE" -gt "0" ] 2>/dev/null; then
    echo "${YELLOW}⚠️  There are $VISIBLE messages waiting in queue${NC}"
    echo "   If trigger is configured, Lambda should process them automatically"
    echo ""
fi

echo "📝 Next steps:"
echo "   1. Ensure SQS trigger is configured: cd lambda-deployment && ./configure-sqs-trigger.sh"
echo "   2. Verify trigger is enabled: Check output above"
echo "   3. Test by sending a message: ./test-lambda.sh"
echo "   4. Monitor logs: aws logs tail /aws/lambda/$FUNCTION_NAME --follow"
echo ""

