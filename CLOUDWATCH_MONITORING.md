# CloudWatch Dashboard for SQS/Lambda Monitoring

Complete guide for tracking SQS queue jobs and Lambda function performance using CloudWatch.

## Quick Start

### 1. Create the Dashboard
```bash
./create-cloudwatch-dashboard.sh
```

This will create a CloudWatch dashboard named `Story-Generation-SQS-Lambda` with comprehensive metrics.

### 2. Monitor Queue Status
```bash
./monitor-sqs-queue.sh
```

This script provides real-time monitoring of:
- SQS queue depth (visible/in-flight messages)
- Message throughput (sent/received/deleted)
- Lambda invocations, errors, and throttles
- Processing duration and error rates
- Queue health metrics

## Dashboard Metrics

The dashboard includes **12 widgets** tracking:

### SQS Queue Metrics
1. **Message Flow**: Messages sent, received, and deleted
2. **Queue Depth**: Visible, in-flight, and delayed messages (with warning thresholds)
3. **Message Age**: Age of oldest message in queue (warns at 5min, critical at 10min)
4. **Message Size**: Average and maximum message sizes
5. **Throughput**: Messages sent over 5min, 1hr, and 24hr periods
6. **Empty Receives**: Tracks when Lambda polls but finds no messages

### Lambda Function Metrics
7. **Invocations**: Total invocations with errors and throttles
8. **Duration**: Average, min, max, and P99 execution times
9. **Concurrent Executions**: Real-time concurrent execution count
10. **Error & Throttle Rates**: Percentage of failed/throttled invocations
11. **Invocations Over Time**: 5min, 1hr, and 24hr trends
12. **Log Insights**: Story processing activity from CloudWatch Logs

## Monitoring Script

The `monitor-sqs-queue.sh` script provides:

### Real-time Queue Status
- Visible messages count
- In-flight messages count
- Color-coded warnings (green/yellow/red)

### 5-Minute Metrics
- Messages sent/received/deleted
- Success rate calculation
- Lambda invocations/errors/throttles
- Average and P99 duration
- Error rate analysis
- Queue age monitoring

### Health Indicators
- ✅ Green: Healthy
- ⚠️ Yellow: Warning (needs attention)
- 🚨 Red: Critical (immediate action needed)

## Accessing the Dashboard

### Via AWS Console
1. Go to [CloudWatch Console](https://us-east-1.console.aws.amazon.com/cloudwatch/)
2. Navigate to **Dashboards**
3. Click on **Story-Generation-SQS-Lambda**

Or use direct URL:
```
https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=Story-Generation-SQS-Lambda
```

### Via AWS CLI
```bash
# Get dashboard details
aws cloudwatch get-dashboard \
    --dashboard-name Story-Generation-SQS-Lambda \
    --region us-east-1

# List all dashboards
aws cloudwatch list-dashboards --region us-east-1
```

## Manual Metric Queries

### Check SQS Queue Metrics
```bash
# Messages in queue (real-time)
aws sqs get-queue-attributes \
    --queue-url https://sqs.us-east-1.amazonaws.com/296291473328/story-generation-queue \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible

# Messages sent (last hour)
aws cloudwatch get-metric-statistics \
    --namespace AWS/SQS \
    --metric-name NumberOfMessagesSent \
    --dimensions Name=QueueName,Value=story-generation-queue \
    --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum \
    --region us-east-1
```

### Check Lambda Metrics
```bash
# Lambda invocations (last hour)
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Invocations \
    --dimensions Name=FunctionName,Value=story-generation-worker \
    --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum \
    --region us-east-1

# Lambda errors (last hour)
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Errors \
    --dimensions Name=FunctionName,Value=story-generation-worker \
    --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Sum \
    --region us-east-1

# Lambda duration (last hour)
aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name Duration \
    --dimensions Name=FunctionName,Value=story-generation-worker \
    --start-time $(date -u -v-1H +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 \
    --statistics Average,Maximum,p99 \
    --region us-east-1
```

## Setting Up Alarms

### Create Alarm for High Queue Depth
```bash
aws cloudwatch put-metric-alarm \
    --alarm-name sqs-queue-depth-high \
    --alarm-description "Alert when SQS queue has more than 50 visible messages" \
    --metric-name ApproximateNumberOfMessagesVisible \
    --namespace AWS/SQS \
    --statistic Average \
    --period 300 \
    --threshold 50 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions Name=QueueName,Value=story-generation-queue \
    --region us-east-1
```

### Create Alarm for Lambda Errors
```bash
aws cloudwatch put-metric-alarm \
    --alarm-name lambda-error-rate-high \
    --alarm-description "Alert when Lambda error rate exceeds 10%" \
    --metric-name ErrorRate \
    --namespace AWS/Lambda \
    --statistic Average \
    --period 300 \
    --threshold 0.1 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions Name=FunctionName,Value=story-generation-worker \
    --region us-east-1
```

### Create Alarm for Old Messages
```bash
aws cloudwatch put-metric-alarm \
    --alarm-name sqs-message-age-high \
    --alarm-description "Alert when messages are older than 10 minutes" \
    --metric-name ApproximateAgeOfOldestMessage \
    --namespace AWS/SQS \
    --statistic Maximum \
    --period 60 \
    --threshold 600 \
    --comparison-operator GreaterThanThreshold \
    --evaluation-periods 2 \
    --dimensions Name=QueueName,Value=story-generation-queue \
    --region us-east-1
```

## Log Insights Queries

### Story Processing Activity
```
SOURCE '/aws/lambda/story-generation-worker' 
| fields @timestamp, @message
| filter @message like /story_id/
| stats count() by bin(5m)
```

### Error Analysis
```
SOURCE '/aws/lambda/story-generation-worker'
| fields @timestamp, @message
| filter @message like /error/i or @message like /Error/i or @message like /ERROR/
| stats count() by bin(5m)
```

### Processing Time
```
SOURCE '/aws/lambda/story-generation-worker'
| fields @timestamp, @message, @duration
| filter @message like /Completed job/
| stats avg(@duration), max(@duration), min(@duration) by bin(5m)
```

## Best Practices

1. **Regular Monitoring**: Run `monitor-sqs-queue.sh` every 5-15 minutes during active periods
2. **Set Up Alarms**: Create CloudWatch alarms for critical metrics
3. **Review Logs**: Check CloudWatch Logs for detailed error messages
4. **Trend Analysis**: Use dashboard to identify patterns and optimize
5. **Capacity Planning**: Monitor concurrent executions and duration trends

## Troubleshooting

### High Queue Depth
- Check Lambda function is running and processing messages
- Verify event source mapping is enabled
- Check for Lambda errors or throttles
- Review Lambda logs for processing issues

### High Error Rate
- Check CloudWatch Logs for error details
- Verify Lambda has proper IAM permissions
- Check for API quota limits (OpenAI, Firebase, etc.)
- Review Lambda function code for bugs

### Slow Processing
- Check Lambda duration metrics
- Review concurrent execution limits
- Check for external API timeouts
- Consider increasing Lambda memory/timeout

## Dashboard Customization

Edit `cloudwatch-dashboard.json` to:
- Add custom metrics
- Adjust time periods
- Change chart types
- Add annotations and thresholds

Then redeploy:
```bash
./create-cloudwatch-dashboard.sh
```

