#!/bin/bash
# Setup LocalStack SQS Queue for Local Testing

echo ""
echo "===================================="
echo "🏗️  Setting Up LocalStack SQS Queue"
echo "===================================="
echo ""

# Check if awslocal is installed
if ! command -v awslocal &> /dev/null; then
    echo "❌ awslocal not found. Installing..."
    pip install awscli-local
fi

# Create SQS queue
echo "📦 Creating SQS queue: story-generation-queue"
awslocal sqs create-queue --queue-name story-generation-queue

# Get queue URL
QUEUE_URL=$(awslocal sqs get-queue-url --queue-name story-generation-queue --query 'QueueUrl' --output text)

echo ""
echo "✅ Queue created successfully!"
echo "   Queue URL: $QUEUE_URL"
echo ""

# Get queue attributes
echo "📊 Queue attributes:"
awslocal sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names All \
    --query 'Attributes' \
    --output table

echo ""
echo "===================================="
echo "🎯 Configuration for .env file:"
echo "===================================="
echo "AWS_USE_SQS_LAMBDA=true"
echo "AWS_ENDPOINT_URL=http://localhost:4566"
echo "AWS_SQS_QUEUE_URL=$QUEUE_URL"
echo "AWS_REGION=us-east-1"
echo "AWS_ACCESS_KEY_ID=test"
echo "AWS_SECRET_ACCESS_KEY=test"
echo ""

echo "===================================="
echo "✅ Setup Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Update your .env file with the above configuration"
echo "2. Run: python test_sqs_connection.py"
echo "3. Run: python local_lambda_worker.py"
echo ""
