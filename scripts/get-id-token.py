#!/usr/bin/env python3
"""
Script to exchange a custom token for an ID token
This is what the mobile app does: custom token -> ID token
"""

import firebase_admin
from firebase_admin import credentials, auth
import requests
import json
import sys

# Firebase Web API key (from your Firebase console)
FIREBASE_WEB_API_KEY = "AIzaSyB1zev9GZAHJ57Rzlao8PuzJbxxI-i_6D0"  # From .env file

def get_id_token_from_custom_token(custom_token: str) -> str:
    """
    Exchange a custom token for an ID token using Firebase REST API
    This mimics what the mobile app does
    """
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={FIREBASE_WEB_API_KEY}"
    
    payload = {
        "token": custom_token,
        "returnSecureToken": True
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        data = response.json()
        id_token = data.get("idToken")
        refresh_token = data.get("refreshToken")
        expires_in = data.get("expiresIn")
        
        print("✅ Successfully exchanged custom token for ID token!")
        print(f"🔑 ID Token (expires in {expires_in}s):")
        print(f"\n{id_token}\n")
        
        return id_token
        
    except requests.exceptions.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
        print(f"Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def create_custom_token_and_exchange(user_id: str = "CnHUiHOSe0RGDPPev6fAeY4YfXj1") -> str:
    """
    Create a custom token and immediately exchange it for an ID token
    """
    try:
        # Initialize Firebase Admin if not already done
        if not firebase_admin._apps:
            cred = credentials.Certificate('./firebase-credentials.json')
            firebase_admin.initialize_app(cred)
        
        # Step 1: Create custom token
        print(f"🔐 Creating custom token for user: {user_id}")
        custom_token = auth.create_custom_token(user_id)
        custom_token_str = custom_token.decode('utf-8')
        
        print(f"✅ Custom token created")
        print(f"📋 Custom token (for reference):")
        print(f"{custom_token_str[:50]}...\n")
        
        # Step 2: Exchange for ID token
        print("🔄 Exchanging custom token for ID token...")
        id_token = get_id_token_from_custom_token(custom_token_str)
        
        return id_token
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    print("🔐 Firebase ID Token Generator")
    print("=" * 60)
    
    # Default test user
    user_id = "CnHUiHOSe0RGDPPev6fAeY4YfXj1"
    
    # Allow override from command line
    if len(sys.argv) > 1:
        user_id = sys.argv[1]
        print(f"Using custom user ID: {user_id}")
    
    id_token = create_custom_token_and_exchange(user_id)
    
    if id_token:
        print("=" * 60)
        print("💡 Usage:")
        print("1. Copy the ID token above")
        print("2. Use it as 'firebase_token' in your API calls")
        print("3. Or export to environment:")
        print(f"\nexport FIREBASE_ID_TOKEN='{id_token}'\n")
        
        # Save to a file for easy access
        with open('.test_id_token', 'w') as f:
            f.write(id_token)
        print("💾 Token saved to .test_id_token file")
    else:
        print("\n❌ Failed to generate ID token")
        sys.exit(1)
