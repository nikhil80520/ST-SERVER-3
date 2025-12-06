#!/usr/bin/env python3
"""
Get Firebase token via API endpoints
More robust Python version with better error handling
"""
import requests
import json
import sys
import os

API_BASE = os.getenv("API_BASE", "http://localhost:8000")

def check_server():
    """Check if server is running"""
    try:
        response = requests.get(f"{API_BASE}/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def sign_up(email: str, password: str, display_name: str = "Test User"):
    """Sign up a new user"""
    print(f"📝 Signing up new user: {email}")
    
    try:
        response = requests.post(
            f"{API_BASE}/auth/signup",
            json={
                "email": email,
                "password": password,
                "display_name": display_name
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            token = data.get("firebase_token")
            refresh_token = data.get("refresh_token")
            
            # Save tokens
            with open(".test_id_token", "w") as f:
                f.write(token)
            if refresh_token:
                with open(".test_refresh_token", "w") as f:
                    f.write(refresh_token)
            
            print("✅ Sign up successful!")
            print(f"\n🔑 Firebase Token:\n{token}\n")
            print("💾 Token saved to .test_id_token")
            
            return token
        
        # Check if user already exists
        detail = data.get("detail", "")
        if "already exists" in detail.lower() or "EmailAlreadyExists" in detail:
            print("⚠️  User already exists, trying sign in...")
            return None
        
        print(f"❌ Sign up failed: {detail or data.get('message', 'Unknown error')}")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

def sign_in(email: str, password: str):
    """Sign in existing user"""
    print(f"🔑 Signing in: {email}")
    
    try:
        response = requests.post(
            f"{API_BASE}/auth/signin",
            json={
                "email": email,
                "password": password
            },
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            token = data.get("firebase_token")
            refresh_token = data.get("refresh_token")
            
            # Save tokens
            with open(".test_id_token", "w") as f:
                f.write(token)
            if refresh_token:
                with open(".test_refresh_token", "w") as f:
                    f.write(refresh_token)
            
            print("✅ Sign in successful!")
            print(f"\n🔑 Firebase Token:\n{token}\n")
            print("💾 Token saved to .test_id_token")
            
            return token
        
        detail = data.get("detail", data.get("message", "Unknown error"))
        print(f"❌ Sign in failed: {detail}")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

def refresh_token_func():
    """Refresh existing token"""
    if not os.path.exists(".test_refresh_token"):
        print("❌ No refresh token found. Please sign in first.")
        return None
    
    with open(".test_refresh_token", "r") as f:
        refresh_token = f.read().strip()
    
    print("🔄 Refreshing token...")
    
    try:
        response = requests.post(
            f"{API_BASE}/auth/refresh-token",
            json={"refresh_token": refresh_token},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        data = response.json()
        
        if response.status_code == 200 and data.get("success"):
            token = data.get("firebase_token")
            new_refresh_token = data.get("refresh_token")
            
            # Save tokens
            with open(".test_id_token", "w") as f:
                f.write(token)
            if new_refresh_token:
                with open(".test_refresh_token", "w") as f:
                    f.write(new_refresh_token)
            
            print("✅ Token refreshed!")
            print(f"\n🔑 New Firebase Token:\n{token}\n")
            print("💾 Token saved to .test_id_token")
            
            return token
        
        detail = data.get("detail", "Unknown error")
        print(f"❌ Token refresh failed: {detail}")
        return None
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return None

def main():
    print("🔐 Get Firebase Token via API")
    print("=" * 40)
    print()
    
    # Check server
    if not check_server():
        print(f"❌ Server is not running at {API_BASE}")
        print("   Start server: uvicorn app.main:app --reload")
        sys.exit(1)
    
    print("✅ Server is running\n")
    
    # Handle refresh command
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        token = refresh_token_func()
        sys.exit(0 if token else 1)
    
    # Show usage if no args
    if len(sys.argv) == 1:
        print("Usage:")
        print("  python3 get-token-api.py <email> <password>")
        print("  python3 get-token-api.py refresh")
        print()
        print("Example:")
        print("  python3 get-token-api.py user@example.com mypassword")
        print()
        sys.exit(1)
    
    # Get credentials
    email = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None
    
    if not password:
        import getpass
        password = getpass.getpass("Enter password: ")
    
    # Try sign up first, if fails (user exists), try sign in
    print(f"\nAttempting sign up first...")
    token = sign_up(email, password)
    
    if not token:
        print(f"\nAttempting sign in...")
        token = sign_in(email, password)
    
    if token:
        print("\n" + "=" * 40)
        print("✅ Done!")
        print("\nNext steps:")
        print("  ./test-api-simple.sh  # Test story generation API")
        print("  cat .test_id_token    # View saved token")
    else:
        print("\n❌ Failed to get token")
        print("\nTroubleshooting:")
        print("  1. Check email and password are correct")
        print("  2. Verify server is running: curl http://localhost:8000/health")
        print("  3. Check server logs for errors")
        sys.exit(1)

if __name__ == "__main__":
    main()

