"""
SQS Helper - Robust job submission with exponential backoff retry
"""
import json
import time
import boto3
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
from src.core.config import settings
from src.common_function.logger import get_logger

logger = get_logger(__name__)


async def send_job_to_sqs(
    payload: Dict[str, Any],
    queue_url: str,
    max_retries: int = 3,
    initial_backoff: float = 1.0
) -> str:
    """
    Send a story generation job to AWS SQS with exponential backoff retry.
    
    Args:
        payload: Job payload containing story_id, user_id, firebase_user_id, parameters, etc.
        queue_url: AWS SQS queue URL
        max_retries: Maximum number of retry attempts (default: 3)
        initial_backoff: Initial backoff delay in seconds (default: 1.0)
        
    Returns:
        message_id: AWS SQS Message ID
        
    Raises:
        RuntimeError: If all retries are exhausted or non-retryable error occurs
    """
    # Validate required payload fields
    required_fields = ['story_id', 'user_id', 'firebase_user_id', 'parameters']
    missing_fields = [f for f in required_fields if f not in payload]
    if missing_fields:
        raise ValueError(f"Missing required payload fields: {missing_fields}")
    
    # Initialize SQS client
    sqs_client = boto3.client(
        'sqs',
        region_name=settings.aws.region,
        aws_access_key_id=settings.aws.access_key_id,
        aws_secret_access_key=settings.aws.secret_access_key
    )
    
    # Prepare message attributes for filtering/routing
    message_attributes = {
        'StoryId': {
            'StringValue': payload['story_id'],
            'DataType': 'String'
        },
        'UserId': {
            'StringValue': payload.get('firebase_user_id', 'unknown'),
            'DataType': 'String'
        },
        'Priority': {
            'StringValue': str(payload.get('priority', 0)),
            'DataType': 'Number'
        }
    }
    
    # Retry loop with exponential backoff
    last_error = None
    for attempt in range(max_retries):
        try:
            response = sqs_client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(payload, default=str),
                MessageAttributes=message_attributes
            )
            
            message_id = response.get('MessageId')
            logger.info(
                f"✅ SQS message sent successfully - "
                f"MessageId: {message_id}, "
                f"StoryId: {payload['story_id']}, "
                f"Attempt: {attempt + 1}/{max_retries}"
            )
            return message_id
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = e.response.get('Error', {}).get('Message', str(e))
            
            # Determine if error is retryable
            retryable_errors = [
                'ServiceUnavailable',
                'ThrottlingException',
                'RequestLimitExceeded',
                'InternalError',
                'RequestTimeout'
            ]
            
            if error_code not in retryable_errors:
                # Non-retryable error - fail immediately
                logger.error(f"❌ Non-retryable SQS error [{error_code}]: {error_msg}")
                raise RuntimeError(f"SQS submission failed [{error_code}]: {error_msg}")
            
            # Retryable error - log and retry with backoff
            last_error = e
            backoff_delay = initial_backoff * (2 ** attempt)
            
            logger.warning(
                f"⚠️ SQS submission failed (attempt {attempt + 1}/{max_retries}) "
                f"[{error_code}]: {error_msg}. "
                f"Retrying in {backoff_delay:.1f}s..."
            )
            
            if attempt < max_retries - 1:
                time.sleep(backoff_delay)
            
        except Exception as e:
            # Unexpected error
            logger.error(f"❌ Unexpected error during SQS submission: {str(e)}")
            raise RuntimeError(f"SQS submission failed with unexpected error: {str(e)}")
    
    # All retries exhausted
    error_details = str(last_error) if last_error else "Unknown error"
    logger.error(f"❌ SQS submission failed after {max_retries} attempts: {error_details}")
    raise RuntimeError(f"Failed to submit job to SQS after {max_retries} attempts: {error_details}")


def validate_sqs_payload(payload: Dict[str, Any]) -> None:
    """
    Validate SQS job payload contains all required fields.
    
    Args:
        payload: Job payload to validate
        
    Raises:
        ValueError: If required fields are missing or invalid
    """
    required_fields = {
        'story_id': str,
        'user_id': str,  # firebase_user_id
        'firebase_user_id': str,
        'parameters': dict
    }
    
    for field, expected_type in required_fields.items():
        if field not in payload:
            raise ValueError(f"Missing required field: {field}")
        if not isinstance(payload[field], expected_type):
            raise ValueError(f"Invalid type for {field}: expected {expected_type.__name__}, got {type(payload[field]).__name__}")
    
    # Validate parameters sub-structure
    params = payload['parameters']
    required_params = ['user_prompt', 'child_id', 'target_scenes']
    missing_params = [p for p in required_params if p not in params]
    if missing_params:
        raise ValueError(f"Missing required parameters: {missing_params}")
