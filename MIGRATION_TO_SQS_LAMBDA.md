# Migration to AWS SQS + Lambda

## Summary of Changes

This document summarizes the changes made to support AWS SQS + Lambda for background story generation, while maintaining backward compatibility with the existing local worker implementation.

## What Changed

### 1. New Files Created

#### `/app/services/sqs_queue_service.py`
- AWS SQS client wrapper
- Handles job submission to SQS queue
- Provides queue monitoring and management
- Gracefully degrades when disabled

#### `/lambda_handler.py`
- AWS Lambda entry point for SQS message processing
- Processes story generation jobs triggered by SQS
- Handles WebSocket notifications (if available)
- Includes local testing capability

#### `/docs/AWS_SQS_LAMBDA_DEPLOYMENT.md`
- Complete deployment guide for AWS infrastructure
- Step-by-step setup instructions
- Cost estimation and scaling considerations
- Troubleshooting and monitoring guidance

### 2. Modified Files

#### `/app/core/config.py`
**Added:**
- `AWSConfig` class with settings for SQS/Lambda integration:
  - `region`: AWS region (default: us-east-1)
  - `access_key_id`: AWS access key
  - `secret_access_key`: AWS secret key
  - `sqs_queue_url`: SQS queue URL
  - `lambda_function_name`: Lambda function name
  - `use_sqs_lambda`: Feature flag to toggle between local/cloud processing

**Impact:** Backward compatible - defaults to local workers (`use_sqs_lambda=false`)

#### `/app/routers/stories.py`
**Modified:** `generate_story_async()` endpoint

**Changes:**
- Imports both `enhanced_background_service` and `sqs_queue_service`
- Checks `settings.aws.use_sqs_lambda` feature flag
- Routes job submission based on flag:
  - `True` → Submit to AWS SQS
  - `False` → Submit to local background workers (current behavior)
- Returns `processing_engine` in response to indicate which system is used

**Backward Compatibility:** ✅ Complete
- When `AWS_USE_SQS_LAMBDA=false` (default), behavior is identical to before
- All existing code paths remain unchanged
- Can toggle between implementations via environment variable

### 3. Commented Code

#### `/app/routers/stories.py` (lines 432-444)
**Original code:**
```python
job_id = await enhanced_background_service.submit_story_job(
    story_id=story_id,
    parameters=job_params,
    services={
        "story_service": story_service,
        "media_service": media_service,
        "storage_service": storage_service
    },
    callbacks={
        "on_progress": on_progress,
        "on_completion": on_completion
    }
)
```

**Status:** Preserved in commented block (lines 468-481) for reference

**New implementation:**
```python
use_sqs = settings.aws.use_sqs_lambda

if use_sqs:
    # AWS SQS + Lambda
    job_id = await sqs_queue_service.submit_story_job(
        story_id=story_id,
        parameters=job_params,
        priority=0
    )
    tracking_method = "aws_sqs_lambda"
else:
    # Local background workers (original code)
    job_id = await enhanced_background_service.submit_story_job(
        story_id=story_id,
        parameters=job_params,
        services={...},
        callbacks={...}
    )
    tracking_method = "background_service_with_websocket_notifications"
```

## Configuration

### Environment Variables

Add to `.env` file:

```bash
# AWS Configuration (optional - only needed for SQS+Lambda)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789012/story-generation-queue
AWS_LAMBDA_FUNCTION_NAME=story-generation-worker

# Feature flag - toggle between implementations
AWS_USE_SQS_LAMBDA=false  # Set to 'true' to use SQS+Lambda
```

### Default Behavior

**Without any configuration changes:**
- `AWS_USE_SQS_LAMBDA` defaults to `false`
- System uses local background workers (existing behavior)
- No AWS credentials required
- Zero impact on current deployments

## How to Use

### Option 1: Keep Using Local Workers (Current Behavior)
**No action required!** The system continues to work as before.

```bash
# .env file
AWS_USE_SQS_LAMBDA=false  # or omit this line entirely
```

### Option 2: Migrate to AWS SQS + Lambda

1. **Set up AWS infrastructure** (see [AWS_SQS_LAMBDA_DEPLOYMENT.md](docs/AWS_SQS_LAMBDA_DEPLOYMENT.md)):
   - Create SQS queue
   - Deploy Lambda function
   - Configure IAM roles

2. **Update `.env` file**:
   ```bash
   AWS_USE_SQS_LAMBDA=true
   AWS_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/YOUR_ACCOUNT_ID/story-generation-queue
   AWS_ACCESS_KEY_ID=your_key
   AWS_SECRET_ACCESS_KEY=your_secret
   ```

3. **Restart the server**:
   ```bash
   uvicorn app.main:app --reload
   ```

4. **Verify** via API response:
   ```json
   {
     "success": true,
     "job_id": "...",
     "tracking_method": "aws_sqs_lambda",
     "processing_engine": "AWS Lambda + SQS"
   }
   ```

## Benefits of SQS + Lambda

### Scalability
- **Before:** Limited by server CPU cores (typically 4-8 workers)
- **After:** Auto-scales to 1000+ concurrent Lambda instances

### Reliability
- **Before:** Jobs lost if server crashes during processing
- **After:** Jobs persist in SQS queue, automatic retries

### Cost
- **Before:** Server runs 24/7 (~$50-200/month)
- **After:** Pay per execution (~$0.015/story, ~$15 for 1000 stories)

### Maintenance
- **Before:** Manual server management, scaling, monitoring
- **After:** Fully managed by AWS, auto-scaling, built-in monitoring

## Testing

### Test with Local Workers
```bash
# Ensure AWS_USE_SQS_LAMBDA=false or not set
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{"firebase_token": "...", "prompt": "test story", ...}'

# Response should show:
# "processing_engine": "Local Background Workers"
```

### Test with SQS + Lambda
```bash
# Set AWS_USE_SQS_LAMBDA=true and configure AWS credentials
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d '{"firebase_token": "...", "prompt": "test story", ...}'

# Response should show:
# "processing_engine": "AWS Lambda + SQS"

# Monitor Lambda execution
aws logs tail /aws/lambda/story-generation-worker --follow
```

## Rollback Plan

If issues occur with SQS + Lambda:

1. **Immediate rollback** (no code changes needed):
   ```bash
   # Update .env
   AWS_USE_SQS_LAMBDA=false

   # Restart server
   systemctl restart storyteller-api  # or your restart command
   ```

2. **System immediately reverts** to local background workers

3. **No data loss** - stories in SQS queue can be processed later or drained

## Migration Strategy

### Recommended Approach: Gradual Migration

1. **Phase 1: Setup (Week 1)**
   - Deploy AWS infrastructure in parallel
   - Test with `AWS_USE_SQS_LAMBDA=true` in development
   - Verify all functionality works

2. **Phase 2: Canary (Week 2)**
   - Route 10% of traffic to SQS+Lambda (A/B testing)
   - Monitor performance, errors, costs
   - Collect metrics and feedback

3. **Phase 3: Full Migration (Week 3)**
   - Set `AWS_USE_SQS_LAMBDA=true` for all traffic
   - Monitor for 7 days
   - Keep local workers ready for instant rollback

4. **Phase 4: Cleanup (Week 4)**
   - Remove local worker code (optional)
   - Update documentation
   - Archive old deployment guides

## Monitoring

### Key Metrics to Track

**Local Workers:**
- Active jobs count
- Queue size
- Worker utilization
- Memory usage

**SQS + Lambda:**
- SQS queue depth
- Lambda invocations
- Lambda errors
- Lambda duration
- Lambda memory usage
- Cost per story

### Alerts to Set Up

```bash
# CloudWatch Alarm for Lambda errors
aws cloudwatch put-metric-alarm \
  --alarm-name story-generation-lambda-errors \
  --alarm-description "Alert on Lambda errors" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1

# CloudWatch Alarm for SQS queue depth
aws cloudwatch put-metric-alarm \
  --alarm-name story-generation-queue-depth \
  --alarm-description "Alert on high queue depth" \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Average \
  --period 300 \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2
```

## FAQ

**Q: Will this break existing deployments?**
A: No, the default behavior is unchanged. Local workers remain active unless explicitly switched.

**Q: Can I switch back and forth?**
A: Yes, toggle `AWS_USE_SQS_LAMBDA` anytime and restart the server.

**Q: What happens to in-flight jobs during a switch?**
A: Local worker jobs complete normally. SQS jobs remain in queue and process when Lambda is ready.

**Q: Do I need to change my client code?**
A: No, the API contract is identical. Clients don't need any changes.

**Q: What about WebSocket notifications?**
A: Currently implemented for local workers. Lambda can send notifications via API Gateway WebSocket or third-party services (implementation pending).

**Q: How do I debug Lambda errors?**
A: Check CloudWatch logs: `/aws/lambda/story-generation-worker`

## Support

- **Deployment Guide:** [docs/AWS_SQS_LAMBDA_DEPLOYMENT.md](docs/AWS_SQS_LAMBDA_DEPLOYMENT.md)
- **Architecture Details:** See `lambda_handler.py` comments
- **Code Changes:** Review git diff for this migration

## Next Steps

1. Review deployment guide
2. Set up AWS infrastructure (dev environment first)
3. Test with sample stories
4. Monitor performance and costs
5. Plan production migration
6. Update runbooks and documentation
