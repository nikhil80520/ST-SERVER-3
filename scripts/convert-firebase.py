#!/usr/bin/env python3
"""
Convert Firebase Custom Token to ID Token
This exchanges your custom token for an ID token that the API expects
"""

import requests
import json
import os

def get_firebase_project_id():
    """Extract project ID from firebase credentials"""
    try:
        with open('./firebase-credentials.json', 'r') as f:
            creds = json.load(f)
            project_id = creds.get('project_id')
            if project_id:
                return project_id
            else:
                print("❌ Could not find project_id in firebase-credentials.json")
                return None
    except Exception as e:
        print(f"❌ Error reading firebase-credentials.json: {e}")
        return None

def convert_custom_token_to_id_token(custom_token, project_id):
    """Convert custom token to ID token using Firebase REST API"""
    
    print("🔄 Converting custom token to ID token...")
    
    # Firebase REST API endpoint for token exchange
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={project_id}"
    
    payload = {
        "token": custom_token,
        "returnSecureToken": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            id_token = data.get('idToken')
            
            if id_token:
                print("✅ Successfully converted to ID token!")
                return id_token
            else:
                print(f"❌ No ID token in response: {data}")
                return None
        else:
            print(f"❌ Token conversion failed: {response.status_code}")
            print(f"Response: {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ Error converting token: {e}")
        return None

def get_api_key_from_env_or_ask():
    """Get Firebase Web API key"""
    print("\n🔑 Need Firebase Web API Key")
    print("This is different from your service account JSON file")
    print("\nTo find your Web API key:")
    print("1. Go to Firebase Console → Project Settings")
    print("2. Scroll down to 'Web API Key'")
    print("3. Copy the key that looks like: AIzaSyC...")
    
    # Check if already in environment
    api_key = "AIzaSyB1zev9GZAHJ57Rzlao8PuzJbxxI-i_6D0"
    if api_key:
        print(f"✅ Found Web API key in environment")
        return api_key
    
    try:
        api_key = input("\nEnter your Firebase Web API Key: ").strip()
        if api_key.startswith('AIza'):
            return api_key
        else:
            print("❌ Web API key should start with 'AIza'")
            return None
    except KeyboardInterrupt:
        print("\n❌ Cancelled")
        return None

def main():
    print("🔄 Firebase Token Converter")
    print("=" * 40)
    
    # Read the custom token
    custom_token = None
    
    # Try to read from file first
    if os.path.exists('firebase_token.txt'):
        try:
            with open('firebase_token.txt', 'r') as f:
                custom_token = f.read().strip()
            print("✅ Read custom token from firebase_token.txt")
        except Exception as e:
            print(f"❌ Error reading firebase_token.txt: {e}")
    
    # If not found, ask user to paste it
    if not custom_token:
        print("Please paste your custom token:")
        try:
            custom_token = input().strip()
        except KeyboardInterrupt:
            print("\n❌ Cancelled")
            return
    
    if not custom_token:
        print("❌ No token provided")
        return
    
    # Get Web API key
    api_key = get_api_key_from_env_or_ask()
    if not api_key:
        print("❌ Web API key required")
        return
    
    # Convert token
    id_token = convert_custom_token_to_id_token(custom_token, api_key)
    
    if id_token:
        print("\n📋 Your ID Token (use this for testing):")
        print("-" * 60)
        print(id_token)
        print("-" * 60)
        
        print("\n💾 Environment variable:")
        print(f"export FIREBASE_TOKEN='{id_token}'")
        
        # Save to file
        try:
            with open('firebase_id_token.txt', 'w') as f:
                f.write(id_token)
            print("\n💾 ID token saved to: firebase_id_token.txt")
        except Exception as e:
            print(f"⚠️ Could not save to file: {e}")
        
        print("\n✅ Now you can test your API with this ID token!")
        
        return id_token
    else:
        print("\n❌ Token conversion failed")
        return None

if __name__ == "__main__":
    main()