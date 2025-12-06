#!/bin/bash
# Create CloudWatch Dashboard for SQS/Lambda Story Generation Monitoring

set -e

DASHBOARD_NAME="Story-Generation-SQS-Lambda"
REGION="us-east-1"
DASHBOARD_FILE="cloudwatch-dashboard.json"

echo "📊 Creating CloudWatch Dashboard"
echo "================================="
echo ""
echo "Dashboard Name: $DASHBOARD_NAME"
echo "Region: $REGION"
echo ""

# Check if dashboard file exists
if [ ! -f "$DASHBOARD_FILE" ]; then
    echo "❌ Dashboard file not found: $DASHBOARD_FILE"
    exit 1
fi

# Check if AWS CLI is available
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

# Create/Update the dashboard
echo "🚀 Creating/Updating CloudWatch Dashboard..."

aws cloudwatch put-dashboard \
    --dashboard-name "$DASHBOARD_NAME" \
    --dashboard-body file://"$DASHBOARD_FILE" \
    --region "$REGION" \
    --output json > /tmp/dashboard-output.json

if [ $? -eq 0 ]; then
    echo "✅ Dashboard created/updated successfully!"
    echo ""
    
    # Extract dashboard URL
    DASHBOARD_URL="https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${DASHBOARD_NAME}"
    
    echo "📊 Dashboard Details:"
    cat /tmp/dashboard-output.json | python3 -m json.tool 2>/dev/null || cat /tmp/dashboard-output.json
    echo ""
    echo "🌐 View Dashboard:"
    echo "   $DASHBOARD_URL"
    echo ""
    echo "💡 To view in AWS Console:"
    echo "   1. Go to AWS CloudWatch Console"
    echo "   2. Navigate to Dashboards"
    echo "   3. Click on '$DASHBOARD_NAME'"
    echo ""
else
    echo "❌ Failed to create dashboard"
    exit 1
fi

