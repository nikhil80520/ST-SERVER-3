import boto3
import json
from datetime import datetime, timedelta

# Initialize CloudWatch Logs client
logs_client = boto3.client('logs', region_name='us-east-1')

# Get the latest log stream
response = logs_client.describe_log_streams(
    logGroupName='/aws/lambda/story-generation-worker',
    orderBy='LastEventTime',
    descending=True,
    limit=1
)

if not response['logStreams']:
    print("❌ No log streams found")
    exit(1)

log_stream_name = response['logStreams'][0]['logStreamName']
print(f"📋 Latest log stream: {log_stream_name}")

# Get log events
events_response = logs_client.get_log_events(
    logGroupName='/aws/lambda/story-generation-worker',
    logStreamName=log_stream_name,
    limit=500
)

print(f"\n📊 Total events: {len(events_response['events'])}")
print("\n" + "="*80)
print("LAMBDA EXECUTION LOGS")
print("="*80 + "\n")

# Print all log messages
for event in events_response['events']:
    timestamp = datetime.fromtimestamp(event['timestamp'] / 1000.0)
    message = event['message'].rstrip('\n')
    print(f"[{timestamp}] {message}")

# Search for key indicators
print("\n" + "="*80)
print("KEY INDICATORS")
print("="*80)

phase_5_found = False
story_18_found = False
postgres_found = False

for event in events_response['events']:
    msg = event['message']
    if 'Phase 5' in msg or 'PostgreSQL' in msg:
        phase_5_found = True
        print(f"✅ PHASE 5/PostgreSQL: {msg[:150]}")
    if 'story_id=18' in msg or 'story_id": 18' in msg:
        story_18_found = True
        print(f"✅ STORY_ID=18: {msg[:150]}")
    if 'StoryPersistence' in msg:
        postgres_found = True
        print(f"✅ PERSISTENCE: {msg[:150]}")

if not phase_5_found:
    print("❌ No Phase 5 or PostgreSQL logs found")
if not story_18_found:
    print("❌ No story_id=18 logs found")
if not postgres_found:
    print("❌ No StoryPersistence logs found")
