# ===== app/utils/firebase_init.py - App Runner Compatible =====
import os
import json
import firebase_admin
from firebase_admin import credentials, storage, firestore
from pathlib import Path
from src.core.config import settings

# Global Firebase clients (initialized lazily)
_firestore_client = None
_storage_bucket = None
_firebase_initialized = False

def _get_firebase_credentials():
    """
    Get Firebase credentials from multiple sources:
    1. JSON string from environment (App Runner/Production)
    2. File path from settings (Local development)
    
    Returns:
        credentials.Certificate or None
    """
    # Option 1: Try JSON string from environment variable (App Runner)
    credentials_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
    if credentials_json:
        try:
            cred_dict = json.loads(credentials_json)
            print("🔧 Loading Firebase credentials from environment variable")
            return credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            print(f"⚠️ Invalid FIREBASE_CREDENTIALS_JSON format: {e}")
    
    # Option 2: Try file path (Local development)
    credentials_path = settings.firebase_credentials_path
    if credentials_path:
        path = Path(credentials_path)
        if path.exists():
            print(f"🔧 Loading Firebase credentials from file: {credentials_path}")
            return credentials.Certificate(str(path))
        else:
            print(f"⚠️ Firebase credentials file not found: {credentials_path}")
    
    raise ValueError(
        "Firebase credentials not configured. Set either:\n"
        "- FIREBASE_CREDENTIALS_JSON (for App Runner/production)\n"
        "- FIREBASE_CREDENTIALS_PATH (for local development)"
    )

def initialize_firebase():
    """Initialize Firebase Admin SDK with proper bucket configuration"""
    global _firebase_initialized
    
    if _firebase_initialized:
        return True
        
    if not firebase_admin._apps:
        try:
            # Get credentials from environment or file
            cred = _get_firebase_credentials()
            
            # Use bucket name exactly as specified in settings
            bucket_name = settings.firebase_storage_bucket
            
            # Only remove gs:// prefix if present (keep everything else as-is)
            if bucket_name.startswith('gs://'):
                bucket_name = bucket_name.replace('gs://', '')
            
            print(f"🔧 Initializing Firebase with bucket: {bucket_name}")
            
            firebase_admin.initialize_app(cred, {
                'storageBucket': bucket_name
            })
            _firebase_initialized = True
            print("✅ Firebase initialized successfully")
            return True
        except ValueError as e:
            print(f"⚠️ Firebase initialization failed: {str(e)}")
            print("📝 Note: Some features requiring Firebase will not work")
            return False
        except Exception as e:
            print(f"⚠️ Firebase initialization failed: {str(e)}")
            print("📝 Note: Some features requiring Firebase will not work")
            return False
    else:
        _firebase_initialized = True
        return True

def get_firestore_client():
    """Get Firestore client (with proper initialization check)"""
    global _firestore_client
    
    if not _firebase_initialized:
        if not initialize_firebase():
            return None
    
    if _firestore_client is None:
        try:
            _firestore_client = firestore.client()
            print("✅ Firestore client created successfully")
        except ValueError as e:
            print(f"⚠️ Firestore client creation failed: {str(e)}")
            return None
        except Exception as e:
            print(f"⚠️ Unexpected error creating Firestore client: {str(e)}")
            return None
    return _firestore_client

def get_storage_bucket():
    """Get Firebase Storage bucket (with proper initialization check)"""
    global _storage_bucket
    
    if not _firebase_initialized:
        if not initialize_firebase():
            return None
    
    if _storage_bucket is None:
        try:
            _storage_bucket = storage.bucket()
            print(f"✅ Storage bucket connected: {_storage_bucket.name}")
        except ValueError as e:
            print(f"⚠️ Storage bucket creation failed: {str(e)}")
            print(f"💡 Check FIREBASE_STORAGE_BUCKET setting")
            return None
        except Exception as e:
            print(f"⚠️ Unexpected error creating storage bucket: {str(e)}")
            return None
    return _storage_bucket

def is_firebase_available() -> bool:
    """Check if Firebase is available and initialized"""
    return _firebase_initialized and len(firebase_admin._apps) > 0

def reset_firebase_clients():
    """Reset Firebase clients (useful for testing)"""
    global _firestore_client, _storage_bucket, _firebase_initialized
    _firestore_client = None
    _storage_bucket = None
    _firebase_initialized = False

def test_storage_connection():
    """Test Firebase Storage connection"""
    try:
        bucket = get_storage_bucket()
        if bucket:
            print(f"✅ Storage test successful: {bucket.name}")
            return True
        else:
            print("❌ Storage test failed: No bucket available")
            return False
    except Exception as e:
        print(f"❌ Storage test failed: {str(e)}")
        return False

def get_firebase_info() -> dict:
    """Get Firebase configuration info (for debugging/health checks)"""
    info = {
        "initialized": _firebase_initialized,
        "firestore_available": _firestore_client is not None,
        "storage_available": _storage_bucket is not None,
        "credential_source": None,
        "bucket_name": None
    }
    
    # Determine credential source
    if os.getenv('FIREBASE_CREDENTIALS_JSON'):
        info["credential_source"] = "environment_variable"
    elif settings.firebase_credentials_path and Path(settings.firebase_credentials_path).exists():
        info["credential_source"] = "file"
    
    # Get bucket name if available
    if _storage_bucket:
        info["bucket_name"] = _storage_bucket.name
    
    return info