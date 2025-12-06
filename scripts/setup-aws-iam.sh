#!/bin/bash
# Setup AWS IAM Role for Story Generation Lambda
# This script automates the IAM role creation for the Lambda function

set -e  # Exit on error

echo "🚀 Setting up AWS IAM Role for Story Generation Lambda"
echo "=================================================="

# Get AWS account ID
echo "📋 Getting AWS account ID..."
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo "❌ Failed to get AWS account ID. Make sure AWS CLI is configured."
    exit 1
fi
echo "✅ AWS Account ID: $AWS_ACCOUNT_ID"

# Set variables
ROLE_NAME="StoryGenerationLambdaRole"
QUEUE_NAME="story-generation-queue"
REGION="${AWS_REGION:-us-east-1}"

echo ""
echo "📝 Configuration:"
echo "   Role Name: $ROLE_NAME"
echo "   Queue Name: $QUEUE_NAME"
echo "   Region: $REGION"
echo ""

# Create trust policy file
echo "📄 Creating trust policy..."
cat > /tmp/lambda-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create execution policy file with dynamic account ID
echo "📄 Creating execution policy..."
cat > /tmp/lambda-execution-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:${REGION}:${AWS_ACCOUNT_ID}:${QUEUE_NAME}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "execute-api:ManageConnections",
        "execute-api:Invoke"
      ],
      "Resource": "arn:aws:execute-api:*:*:*"
    }
  ]
}
EOF

# Check if role already exists
echo ""
echo "🔍 Checking if role already exists..."
if aws iam get-role --role-name $ROLE_NAME &>/dev/null; then
    echo "⚠️  Role $ROLE_NAME already exists."
    read -p "   Do you want to update the policies? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "♻️  Updating policies..."
        aws iam put-role-policy \
          --role-name $ROLE_NAME \
          --policy-name StoryGenerationLambdaPolicy \
          --policy-document file:///tmp/lambda-execution-policy.json
        echo "✅ Policies updated successfully"
    else
        echo "⏭️  Skipping policy update"
    fi
else
    # Create role
    echo "🏗️  Creating IAM role..."
    aws iam create-role \
      --role-name $ROLE_NAME \
      --assume-role-policy-document file:///tmp/lambda-trust-policy.json

    echo "✅ Role created successfully"

    # Wait a moment for role to propagate
    echo "⏳ Waiting for role to propagate..."
    sleep 3

    # Attach execution policy
    echo "📎 Attaching execution policy..."
    aws iam put-role-policy \
      --role-name $ROLE_NAME \
      --policy-name StoryGenerationLambdaPolicy \
      --policy-document file:///tmp/lambda-execution-policy.json

    echo "✅ Policy attached successfully"
fi

# Get role ARN
echo ""
echo "🔗 Getting role ARN..."
ROLE_ARN=$(aws iam get-role --role-name $ROLE_NAME --query 'Role.Arn' --output text)

# Cleanup temp files
rm -f /tmp/lambda-trust-policy.json /tmp/lambda-execution-policy.json

echo ""
echo "=================================================="
echo "✅ IAM Role Setup Complete!"
echo "=================================================="
echo ""
echo "📋 Role Details:"
echo "   Role Name: $ROLE_NAME"
echo "   Role ARN:  $ROLE_ARN"
echo ""
echo "📝 Next Steps:"
echo "   1. Use this Role ARN when creating your Lambda function"
echo "   2. Run: ./scripts/deploy-lambda.sh"
echo ""
echo "💾 Save this Role ARN for later:"
echo "   export LAMBDA_ROLE_ARN=\"$ROLE_ARN\""
echo ""

# Export for current session
export LAMBDA_ROLE_ARN="$ROLE_ARN"
echo "✅ Role ARN exported to \$LAMBDA_ROLE_ARN"
