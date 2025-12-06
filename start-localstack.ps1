# LocalStack Setup for Local SQS Testing
# Run this script to set up LocalStack with SQS queue

# Check if LocalStack is installed
if (!(Get-Command localstack -ErrorAction SilentlyContinue)) {
    Write-Host "❌ LocalStack not found. Installing..."
    pip install localstack awscli-local
}

Write-Host "`n============================"
Write-Host "🚀 Starting LocalStack"
Write-Host "============================`n"

# Start LocalStack (you can also use Docker)
Write-Host "Starting LocalStack services (SQS, Lambda)..."
Write-Host "Press Ctrl+C to stop LocalStack when done testing`n"

# Option 1: Using Docker (recommended)
Write-Host "Starting LocalStack with Docker..."
docker run --rm -it -p 4566:4566 -p 4571:4571 `
    -e SERVICES=sqs,lambda `
    -e DEBUG=1 `
    localstack/localstack

# If you don't have Docker, use:
# localstack start

# Note: Run the following commands in a separate PowerShell window
# after LocalStack is running:

<#
# Create SQS queue
awslocal sqs create-queue --queue-name story-generation-queue

# Get queue URL
$queueUrl = awslocal sqs get-queue-url --queue-name story-generation-queue --query 'QueueUrl' --output text
Write-Host "✅ Queue URL: $queueUrl"

# Update your .env file with:
# AWS_ENDPOINT_URL=http://localhost:4566
# AWS_SQS_QUEUE_URL=http://localhost:4566/000000000000/story-generation-queue
# AWS_REGION=us-east-1
# AWS_ACCESS_KEY_ID=test
# AWS_SECRET_ACCESS_KEY=test
#>
