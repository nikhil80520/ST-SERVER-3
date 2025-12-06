import boto3
import os
from botocore.config import Config
from src.core.config import settings

def get_s3_client():
    """
    Initialize and return a boto3 S3 client.
    Works with both explicit credentials (local) and IAM roles (Lambda).
    """
    try:
        # Check if running in Lambda environment
        is_lambda = os.getenv('AWS_LAMBDA_FUNCTION_NAME') or os.getenv('LAMBDA_TASK_ROOT')
        
        # Check if explicit credentials are provided and valid
        has_explicit_credentials = (
            settings.aws.access_key_id and 
            settings.aws.secret_access_key and
            settings.aws.access_key_id.strip() != "" and
            settings.aws.secret_access_key.strip() != "" and
            len(settings.aws.access_key_id) > 10  # Valid AWS key is at least 16 chars
        )
        
        if is_lambda:
            # Lambda: Always use IAM role (boto3 automatically uses execution role)
            print("🔑 Lambda environment detected - using IAM role for AWS credentials")
            s3_client = boto3.client(
                's3',
                region_name=settings.aws.region,
                config=Config(signature_version='s3v4')
            )
        elif has_explicit_credentials:
            # Local/development: Use explicit credentials
            print(f"🔑 Using explicit AWS credentials from environment (region: {settings.aws.region})")
            s3_client = boto3.client(
                's3',
                region_name=settings.aws.region,
                aws_access_key_id=settings.aws.access_key_id,
                aws_secret_access_key=settings.aws.secret_access_key,
                config=Config(signature_version='s3v4')
            )
        else:
            # Fallback: Try default credential chain (profile, instance metadata, etc.)
            print("🔑 No explicit credentials - trying default AWS credential chain")
            s3_client = boto3.client(
                's3',
                region_name=settings.aws.region,
                config=Config(signature_version='s3v4')
            )
        
        # Verify client works by checking credentials
        try:
            s3_client.list_buckets(MaxBuckets=1)
            print(f"✅ S3 client initialized successfully")
        except Exception as e:
            print(f"⚠️  S3 client created but credentials may be invalid: {e}")
        
        return s3_client
    except Exception as e:
        print(f"❌ Failed to initialize S3 client: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def get_s3_bucket_name():
    return settings.aws.s3_bucket_name
