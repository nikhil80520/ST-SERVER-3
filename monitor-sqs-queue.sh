#!/bin/bash
# Monitor SQS Queue and Lambda Metrics

set -e

QUEUE_URL="https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue"
FUNCTION_NAME="story-generation-worker"
REGION="us-east-1"
QUEUE_NAME="story-generation-queue"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "📊 SQS Queue & Lambda Monitoring"
echo "================================="
echo ""

# Function to get metric value
get_metric() {
    local namespace=$1
    local metric_name=$2
    local dimensions=$3
    local stat=$4
    local period=${5:-300}
    
    # Cross-platform date calculation for "5 minutes ago"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        START_TIME=$(date -u -v-5M +%Y-%m-%dT%H:%M:%S)
    else
        START_TIME=$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S)
    fi
    END_TIME=$(date -u +%Y-%m-%dT%H:%M:%S)
    
    aws cloudwatch get-metric-statistics \
        --namespace "$namespace" \
        --metric-name "$metric_name" \
        --dimensions $dimensions \
        --start-time "$START_TIME" \
        --end-time "$END_TIME" \
        --period "$period" \
        --statistics "$stat" \
        --region "$REGION" \
        --query 'Datapoints[0].'$stat \
        --output text 2>/dev/null || echo "0"
}

# 1. SQS Queue Status (Real-time)
echo "1️⃣  SQS Queue Status (Real-time)"
echo "--------------------------------"
VISIBLE=$(aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessages \
    --region "$REGION" \
    --query 'Attributes.ApproximateNumberOfMessages' \
    --output text 2>/dev/null || echo "0")

IN_FLIGHT=$(aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessagesNotVisible \
    --region "$REGION" \
    --query 'Attributes.ApproximateNumberOfMessagesNotVisible' \
    --output text 2>/dev/null || echo "0")

if [ "$VISIBLE" -gt "0" ]; then
    echo "   ${YELLOW}⚠️  Visible Messages: $VISIBLE${NC}"
else
    echo "   ${GREEN}✅ Visible Messages: $VISIBLE${NC}"
fi

if [ "$IN_FLIGHT" -gt "0" ]; then
    echo "   ${GREEN}🔄 In-Flight Messages: $IN_FLIGHT${NC}"
else
    echo "   📭 In-Flight Messages: $IN_FLIGHT"
fi
echo ""

# 2. SQS Metrics (Last 5 minutes)
echo "2️⃣  SQS Metrics (Last 5 minutes)"
echo "--------------------------------"

MESSAGES_SENT=$(get_metric "AWS/SQS" "NumberOfMessagesSent" "Name=QueueName,Value=$QUEUE_NAME" "Sum")
MESSAGES_RECEIVED=$(get_metric "AWS/SQS" "NumberOfMessagesReceived" "Name=QueueName,Value=$QUEUE_NAME" "Sum")
MESSAGES_DELETED=$(get_metric "AWS/SQS" "NumberOfMessagesDeleted" "Name=QueueName,Value=$QUEUE_NAME" "Sum")

echo "   📤 Messages Sent: ${MESSAGES_SENT:-0}"
echo "   📥 Messages Received: ${MESSAGES_RECEIVED:-0}"
echo "   ✅ Messages Deleted: ${MESSAGES_DELETED:-0}"

# Calculate success rate
MESSAGES_SENT_INT=${MESSAGES_SENT%.*}
MESSAGES_DELETED_INT=${MESSAGES_DELETED%.*}
if [ "${MESSAGES_SENT_INT:-0}" -gt "0" ] 2>/dev/null; then
    SUCCESS_RATE=$(echo "scale=2; ${MESSAGES_DELETED_INT:-0} * 100 / ${MESSAGES_SENT_INT:-0}" | bc 2>/dev/null || echo "0")
    echo "   📊 Success Rate: ${SUCCESS_RATE}%"
    
    if (( $(echo "$SUCCESS_RATE < 90" | bc -l 2>/dev/null || echo "0") )); then
        echo "   ${RED}⚠️  Success rate below 90%${NC}"
    fi
fi
echo ""

# 3. Lambda Metrics (Last 5 minutes)
echo "3️⃣  Lambda Metrics (Last 5 minutes)"
echo "-----------------------------------"

INVOCATIONS=$(get_metric "AWS/Lambda" "Invocations" "Name=FunctionName,Value=$FUNCTION_NAME" "Sum")
ERRORS=$(get_metric "AWS/Lambda" "Errors" "Name=FunctionName,Value=$FUNCTION_NAME" "Sum")
THROTTLES=$(get_metric "AWS/Lambda" "Throttles" "Name=FunctionName,Value=$FUNCTION_NAME" "Sum")
DURATION_AVG=$(get_metric "AWS/Lambda" "Duration" "Name=FunctionName,Value=$FUNCTION_NAME" "Average")
DURATION_P99=$(get_metric "AWS/Lambda" "Duration" "Name=FunctionName,Value=$FUNCTION_NAME" "p99")

echo "   🔄 Invocations: ${INVOCATIONS:-0}"

ERRORS_INT=${ERRORS%.*}
THROTTLES_INT=${THROTTLES%.*}

if [ "${ERRORS_INT:-0}" -gt "0" ] 2>/dev/null && [ "${ERRORS_INT}" != "None" ]; then
    echo "   ${RED}❌ Errors: ${ERRORS_INT}${NC}"
else
    echo "   ${GREEN}✅ Errors: ${ERRORS_INT:-0}${NC}"
fi

if [ "${THROTTLES_INT:-0}" -gt "0" ] 2>/dev/null && [ "${THROTTLES_INT}" != "None" ]; then
    echo "   ${RED}⚠️  Throttles: ${THROTTLES_INT}${NC}"
else
    echo "   ✅ Throttles: ${THROTTLES_INT:-0}"
fi

if [ -n "$DURATION_AVG" ] && [ "$DURATION_AVG" != "None" ] && [ "$DURATION_AVG" != "0" ]; then
    DURATION_SEC=$(echo "scale=2; ${DURATION_AVG} / 1000" | bc 2>/dev/null || echo "0")
    echo "   ⏱️  Avg Duration: ${DURATION_SEC}s (${DURATION_AVG}ms)"
    
    if [ -n "$DURATION_P99" ] && [ "$DURATION_P99" != "None" ] && [ "$DURATION_P99" != "0" ]; then
        P99_SEC=$(echo "scale=2; ${DURATION_P99} / 1000" | bc 2>/dev/null || echo "0")
        echo "   📊 P99 Duration: ${P99_SEC}s (${DURATION_P99}ms)"
    fi
else
    echo "   ⏱️  Duration: No recent executions"
fi
echo ""

# 4. Error Rate
INVOCATIONS_INT=${INVOCATIONS%.*}
ERRORS_INT=${ERRORS%.*}
if [ "${INVOCATIONS_INT:-0}" -gt "0" ] 2>/dev/null && [ "${INVOCATIONS_INT}" != "None" ]; then
    ERROR_RATE=$(echo "scale=2; ${ERRORS_INT:-0} * 100 / ${INVOCATIONS_INT:-0}" | bc 2>/dev/null || echo "0")
    echo "4️⃣  Error Analysis"
    echo "------------------"
    echo "   📊 Error Rate: ${ERROR_RATE}%"
    
    if (( $(echo "$ERROR_RATE > 10" | bc -l 2>/dev/null || echo "0") )); then
        echo "   ${RED}🚨 High error rate detected!${NC}"
    elif (( $(echo "$ERROR_RATE > 5" | bc -l 2>/dev/null || echo "0") )); then
        echo "   ${YELLOW}⚠️  Moderate error rate${NC}"
    else
        echo "   ${GREEN}✅ Error rate within acceptable range${NC}"
    fi
    echo ""
fi

# 5. Queue Age
echo "5️⃣  Queue Health"
echo "----------------"

OLDEST_AGE=$(get_metric "AWS/SQS" "ApproximateAgeOfOldestMessage" "Name=QueueName,Value=$QUEUE_NAME" "Maximum" "60")

OLDEST_AGE_INT=${OLDEST_AGE%.*}
if [ -n "$OLDEST_AGE" ] && [ "$OLDEST_AGE" != "None" ] && [ "${OLDEST_AGE_INT:-0}" -gt "0" ] 2>/dev/null; then
    AGE_SEC=$OLDEST_AGE
    AGE_MIN=$(echo "scale=1; $AGE_SEC / 60" | bc 2>/dev/null || echo "0")
    
    if [ "${OLDEST_AGE_INT}" -gt "600" ]; then
        echo "   ${RED}🚨 Oldest Message Age: ${AGE_MIN} minutes${NC}"
    elif [ "${OLDEST_AGE_INT}" -gt "300" ]; then
        echo "   ${YELLOW}⚠️  Oldest Message Age: ${AGE_MIN} minutes${NC}"
    else
        echo "   ${GREEN}✅ Oldest Message Age: ${AGE_MIN} minutes${NC}"
    fi
else
    echo "   ✅ No messages in queue"
fi
echo ""

# Summary
echo "================================="
echo "📋 Summary"
echo "================================="
echo ""
echo "Queue URL: $QUEUE_URL"
echo "Lambda Function: $FUNCTION_NAME"
echo ""
echo "💡 View detailed metrics:"
echo "   ./create-cloudwatch-dashboard.sh  # Create dashboard"
echo "   aws cloudwatch get-dashboard --dashboard-name Story-Generation-SQS-Lambda"
echo ""
echo "📊 View in AWS Console:"
echo "   https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=Story-Generation-SQS-Lambda"
echo ""

