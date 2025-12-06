"""
AWS SQS Queue Service for Story Generation
Replaces local background workers with cloud-based queue + Lambda processing
"""
import json
import uuid
import boto3
from typing import Dict, Any, Optional
from datetime import datetime
from src.core.config import settings
from src.common_function.logger import get_logger

logger = get_logger(__name__)


class SQSQueueService:
    """Service for managing story generation jobs via AWS SQS"""

    def __init__(self):
        """Initialize SQS client"""
        self.enabled = settings.aws.use_sqs_lambda

        if self.enabled:
            # Initialize boto3 SQS client
            # Use explicit credentials if provided, otherwise use default AWS credential chain
            client_kwargs = {'region_name': settings.aws.region}
            if settings.aws.access_key_id and settings.aws.secret_access_key:
                client_kwargs['aws_access_key_id'] = settings.aws.access_key_id
                client_kwargs['aws_secret_access_key'] = settings.aws.secret_access_key
                logger.info("Using explicit AWS credentials from settings")
            else:
                logger.info("Using default AWS credential chain (environment/IAM/config file)")

            self.sqs_client = boto3.client('sqs', **client_kwargs)
            self.queue_url = settings.aws.sqs_queue_url
            logger.info(f"✅ SQS Queue Service initialized - Queue: {self.queue_url}")
        else:
            self.sqs_client = None
            self.queue_url = None
            logger.info("ℹ️  SQS Queue Service disabled - using local background workers")

    async def submit_story_job(
        self,
        story_id: int,  # Now accepts integer from PostgreSQL
        parameters: Dict[str, Any],
        priority: int = 0
    ) -> str:
        """
        Submit a story generation job to SQS queue

        Args:
            story_id: Unique story identifier (PostgreSQL integer)
            parameters: Story generation parameters
            priority: Job priority (0-9, lower = higher priority)

        Returns:
            job_id: Unique job identifier
        """
        if not self.enabled:
            raise RuntimeError("SQS Queue Service is disabled. Set AWS_USE_SQS_LAMBDA=true to enable.")

        job_id = str(uuid.uuid4())

        # Convert child_id to string for Lambda/Firestore compatibility
        # Lambda uses Firestore which requires string document IDs
        lambda_parameters = parameters.copy()
        if "child_id" in lambda_parameters and lambda_parameters["child_id"] is not None:
            lambda_parameters["child_id"] = str(lambda_parameters["child_id"])

        # Prepare message payload
        message_body = {
            "job_id": job_id,
            "story_id": story_id,  # Integer story_id for PostgreSQL
            "user_id": parameters.get("user_id"),
            "parameters": lambda_parameters,  # Use converted parameters
            "created_at": datetime.utcnow().isoformat(),
            "priority": priority
        }

        # Message attributes for filtering/routing (all must be strings)
        message_attributes = {
            'Priority': {
                'StringValue': str(priority),
                'DataType': 'Number'
            },
            'StoryId': {
                'StringValue': str(story_id),  # Convert integer to string
                'DataType': 'String'
            },
            'UserId': {
                'StringValue': str(parameters.get("user_id", "unknown")),  # Ensure string
                'DataType': 'String'
            }
        }

        try:
            # Send message to SQS
            response = self.sqs_client.send_message(
                QueueUrl=self.queue_url,
                MessageBody=json.dumps(message_body),
                MessageAttributes=message_attributes,
                # Use MessageGroupId for FIFO queues (if applicable)
                # MessageGroupId=parameters.get("user_id", "default"),
                # MessageDeduplicationId=job_id  # For FIFO queues
            )

            message_id = response.get('MessageId')
            logger.info(f"📤 Story job submitted to SQS - Job: {job_id}, Story: {story_id}, MessageId: {message_id}")
            logger.info(f"📊 Queue: {self.queue_url}, Priority: {priority}")

            return job_id

        except Exception as e:
            logger.error(f"❌ Failed to submit job to SQS: {e}")
            raise RuntimeError(f"Failed to submit job to SQS: {str(e)}")

    def get_queue_attributes(self) -> Dict[str, Any]:
        """Get current queue statistics"""
        if not self.enabled:
            return {"enabled": False}

        try:
            response = self.sqs_client.get_queue_attributes(
                QueueUrl=self.queue_url,
                AttributeNames=['All']
            )

            attributes = response.get('Attributes', {})

            return {
                "enabled": True,
                "queue_url": self.queue_url,
                "approximate_messages": int(attributes.get('ApproximateNumberOfMessages', 0)),
                "approximate_messages_not_visible": int(attributes.get('ApproximateNumberOfMessagesNotVisible', 0)),
                "approximate_messages_delayed": int(attributes.get('ApproximateNumberOfMessagesDelayed', 0)),
                "created_timestamp": attributes.get('CreatedTimestamp'),
                "last_modified_timestamp": attributes.get('LastModifiedTimestamp')
            }
        except Exception as e:
            logger.error(f"❌ Failed to get queue attributes: {e}")
            return {"enabled": True, "error": str(e)}

    def delete_message(self, receipt_handle: str) -> bool:
        """Delete a message from the queue after processing"""
        if not self.enabled:
            return False

        try:
            self.sqs_client.delete_message(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle
            )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete message from SQS: {e}")
            return False

    def change_message_visibility(self, receipt_handle: str, visibility_timeout: int) -> bool:
        """
        Change visibility timeout for a message (useful for long-running jobs)

        Args:
            receipt_handle: Message receipt handle
            visibility_timeout: New visibility timeout in seconds (0-43200)
        """
        if not self.enabled:
            return False

        try:
            self.sqs_client.change_message_visibility(
                QueueUrl=self.queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout
            )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to change message visibility: {e}")
            return False


# Global instance
sqs_queue_service = SQSQueueService()
