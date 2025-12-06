#!/bin/bash
# Get Firebase token via API endpoints

set -e

API_BASE="http://localhost:8000"
EMAIL="${1:-test@example.com}"
PASSWORD="${2:-testpassword123}"

echo "🔐 Getting Firebase Token via API"
echo "=================================="
echo ""
echo "Options:"
echo "  1. Sign Up (create new account)"
echo "  2. Sign In (existing account)"
echo "  3. Use existing credentials"
echo ""

# Check if server is running
if ! curl -s "${API_BASE}/health" > /dev/null 2>&1; then
    echo "❌ Server is not running at ${API_BASE}"
    echo "   Start server: uvicorn app.main:app --reload"
    exit 1
fi

echo "✅ Server is running"
echo ""

# Function to sign up
sign_up() {
    echo "📝 Signing up new user..."
    echo "   Email: $EMAIL"
    echo "   Password: $PASSWORD"
    echo ""
    
    RESPONSE=$(curl -s -X POST "${API_BASE}/auth/signup" \
        -H "Content-Type: application/json" \
        -d "{
            \"email\": \"$EMAIL\",
            \"password\": \"$PASSWORD\",
            \"display_name\": \"Test User\"
        }")
    
    if echo "$RESPONSE" | grep -q '"success".*true'; then
        TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('firebase_token', ''))" 2>/dev/null || echo "")
        REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('refresh_token', ''))" 2>/dev/null || echo "")
        
        if [ -n "$TOKEN" ]; then
            echo "✅ Sign up successful!"
            echo "$TOKEN" > .test_id_token
            echo "$REFRESH_TOKEN" > .test_refresh_token
            echo ""
            echo "🔑 Firebase Token:"
            echo "$TOKEN"
            echo ""
            echo "💾 Token saved to .test_id_token"
            echo "💾 Refresh token saved to .test_refresh_token"
            return 0
        fi
    fi
    
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('detail', data.get('message', 'Unknown error')))" 2>/dev/null || echo "$RESPONSE")
    
    if echo "$ERROR" | grep -q "already exists\|EmailAlreadyExists"; then
        echo "⚠️  User already exists, trying sign in instead..."
        return 1
    else
        echo "❌ Sign up failed: $ERROR"
        return 1
    fi
}

# Function to sign in
sign_in() {
    echo "🔑 Signing in existing user..."
    echo "   Email: $EMAIL"
    echo ""
    
    RESPONSE=$(curl -s -X POST "${API_BASE}/auth/signin" \
        -H "Content-Type: application/json" \
        -d "{
            \"email\": \"$EMAIL\",
            \"password\": \"$PASSWORD\"
        }")
    
    if echo "$RESPONSE" | grep -q '"success".*true'; then
        TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('firebase_token', ''))" 2>/dev/null || echo "")
        REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('refresh_token', ''))" 2>/dev/null || echo "")
        
        if [ -n "$TOKEN" ]; then
            echo "✅ Sign in successful!"
            echo "$TOKEN" > .test_id_token
            echo "$REFRESH_TOKEN" > .test_refresh_token
            echo ""
            echo "🔑 Firebase Token:"
            echo "$TOKEN"
            echo ""
            echo "💾 Token saved to .test_id_token"
            echo "💾 Refresh token saved to .test_refresh_token"
            return 0
        fi
    fi
    
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('detail', data.get('message', 'Unknown error')))" 2>/dev/null || echo "$RESPONSE")
    echo "❌ Sign in failed: $ERROR"
    return 1
}

# Function to refresh token
refresh_token() {
    if [ ! -f ".test_refresh_token" ]; then
        echo "❌ No refresh token found. Please sign in first."
        return 1
    fi
    
    REFRESH_TOKEN=$(cat .test_refresh_token)
    echo "🔄 Refreshing token..."
    
    RESPONSE=$(curl -s -X POST "${API_BASE}/auth/refresh-token" \
        -H "Content-Type: application/json" \
        -d "{
            \"refresh_token\": \"$REFRESH_TOKEN\"
        }")
    
    if echo "$RESPONSE" | grep -q '"success".*true'; then
        TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('firebase_token', ''))" 2>/dev/null || echo "")
        NEW_REFRESH_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('refresh_token', ''))" 2>/dev/null || echo "")
        
        if [ -n "$TOKEN" ]; then
            echo "✅ Token refreshed!"
            echo "$TOKEN" > .test_id_token
            if [ -n "$NEW_REFRESH_TOKEN" ]; then
                echo "$NEW_REFRESH_TOKEN" > .test_refresh_token
            fi
            echo ""
            echo "🔑 New Firebase Token:"
            echo "$TOKEN"
            echo ""
            echo "💾 Token saved to .test_id_token"
            return 0
        fi
    fi
    
    ERROR=$(echo "$RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('detail', 'Unknown error'))" 2>/dev/null || echo "$RESPONSE")
    echo "❌ Token refresh failed: $ERROR"
    return 1
}

# Main logic
if [ "$1" == "refresh" ]; then
    refresh_token
    exit $?
fi

# Try sign up first, if fails (user exists), try sign in
if ! sign_up; then
    sign_in
fi

echo ""
echo "=================================="
echo "✅ Done!"
echo ""
echo "Usage:"
echo "  ./get-token-via-api.sh [email] [password]"
echo "  ./get-token-via-api.sh refresh  # Refresh existing token"
echo ""
echo "Test with token:"
echo "  ./test-api-simple.sh"
echo ""

