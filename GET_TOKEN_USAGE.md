# Get Firebase Token via API

You now have two ways to get a Firebase token using your API endpoints:

## Option 1: Python Script (Recommended)
```bash
# Sign up with new account
python3 get-token-api.py your@email.com yourpassword

# Sign in with existing account
python3 get-token-api.py your@email.com yourpassword

# Refresh existing token
python3 get-token-api.py refresh
```

## Option 2: Bash Script
```bash
# Sign up or sign in
./get-token-via-api.sh your@email.com yourpassword

# Refresh existing token
./get-token-via-api.sh refresh
```

## Option 3: Direct cURL

### Sign Up
```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your@email.com",
    "password": "yourpassword",
    "display_name": "Your Name"
  }' | jq -r '.firebase_token' > .test_id_token
```

### Sign In
```bash
curl -X POST http://localhost:8000/auth/signin \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your@email.com",
    "password": "yourpassword"
  }' | jq -r '.firebase_token' > .test_id_token
```

### Refresh Token
```bash
REFRESH_TOKEN=$(cat .test_refresh_token)
curl -X POST http://localhost:8000/auth/refresh-token \
  -H "Content-Type: application/json" \
  -d "{
    \"refresh_token\": \"$REFRESH_TOKEN\"
  }" | jq -r '.firebase_token' > .test_id_token
```

## After Getting Token

The token will be saved to `.test_id_token`. Use it with:

```bash
# Test story generation API
./test-api-simple.sh

# Or manually use in curl
TOKEN=$(cat .test_id_token)
curl -X POST http://localhost:8000/stories/generate \
  -H "Content-Type: application/json" \
  -d "{
    \"firebase_token\": \"$TOKEN\",
    \"prompt\": \"Create a story about...\",
    \"child_name\": \"Alex\",
    \"child_age\": 6
  }"
```

## Available Endpoints

- `POST /auth/signup` - Create new account
- `POST /auth/signin` - Sign in existing account
- `POST /auth/refresh-token` - Refresh expired token
- `POST /auth/verify-token` - Verify token validity

## Notes

- Tokens expire after 1 hour (default Firebase setting)
- Use refresh token to get new tokens without re-authenticating
- Both scripts automatically save tokens to `.test_id_token` and `.test_refresh_token`

