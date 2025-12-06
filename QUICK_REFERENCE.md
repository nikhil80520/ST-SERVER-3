# AWS SQS + Lambda - Quick Reference Card

## 🚀 Enable AWS Processing

```bash
# Edit .env
AWS_USE_SQS_LAMBDA=true

# Restart server
uvicorn app.main:app --reload
```

## 📊 Monitor in Real-Time

```bash
# Watch Lambda logs
aws logs tail /aws/lambda/story-generation-worker --follow

# Check queue depth
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue \
  --attribute-names ApproximateNumberOfMessages
```

## 🧪 Test the System

```bash
# Submit test story
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{"firebase_token":"TOKEN","prompt":"A brave fox","child_name":"Test","child_age":6,"scene_count":3}'

# Should return: "processing_engine": "AWS Lambda + SQS"
```

## ⚡ Quick Commands

```bash
# Function status
aws lambda get-function --function-name story-generation-worker | jq '.Configuration.State'

# Recent errors
aws logs tail /aws/lambda/story-generation-worker --since 10m --filter-pattern ERROR

# Queue stats
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue \
  --attribute-names All | jq '.Attributes | {Messages, MessagesNotVisible, MessagesDelayed}'

# Lambda metrics (last hour)
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=story-generation-worker \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum
```

## 🔄 Rollback to Local Workers

```bash
# Edit .env
AWS_USE_SQS_LAMBDA=false

# Restart
uvicorn app.main:app --reload
```

## 🛠️ Update Lambda Code

```bash
cd lambda-deployment
./deploy-via-s3.sh
```

## 💰 Cost Calculator

| Stories | Daily Cost | Monthly Cost |
|---------|-----------|--------------|
| 10 | $0.15 | $4.50 |
| 50 | $0.75 | $22.50 |
| 100 | $1.50 | $45.00 |
| 500 | $7.50 | $225.00 |

Formula: `stories × $0.015`

## 🆘 Troubleshooting

**Messages not processing?**
```bash
aws lambda list-event-source-mappings --function-name story-generation-worker
```

**Lambda timing out?**
```bash
aws lambda update-function-configuration \
  --function-name story-generation-worker \
  --timeout 900
```

**Out of memory?**
```bash
aws lambda update-function-configuration \
  --function-name story-generation-worker \
  --memory-size 5120
```

## 📚 Full Documentation

- [AWS_DEPLOYMENT_COMPLETE.md](AWS_DEPLOYMENT_COMPLETE.md) - Deployment summary
- [docs/AWS_SQS_LAMBDA_DEPLOYMENT.md](docs/AWS_SQS_LAMBDA_DEPLOYMENT.md) - Full guide
- [docs/AWS_TROUBLESHOOTING.md](docs/AWS_TROUBLESHOOTING.md) - Problem solutions
- [MIGRATION_TO_SQS_LAMBDA.md](MIGRATION_TO_SQS_LAMBDA.md) - Migration strategy

## 📝 Key Info

- **Function**: `story-generation-worker`
- **Queue**: `story-generation-queue`
- **Region**: `us-east-1`
- **Account**: `296291473328`
- **Memory**: 3008 MB
- **Timeout**: 900s (15 min)
- **Cost/Story**: ~$0.015

## ✅ Status

✅ IAM Role created
✅ SQS Queue created
✅ Lambda deployed (62MB via S3)
✅ Trigger configured
✅ Ready for production
