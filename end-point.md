# API Endpoints Documentation

This document lists all server API endpoints used in the JuneKids mobile application.

**Base URL:** `https://api.junekids.xyz`

---

## Table of Contents
- [Authentication Endpoints](#authentication-endpoints)
- [User Profile Endpoints](#user-profile-endpoints)
- [Children Management Endpoints](#children-management-endpoints)
- [Story Management Endpoints](#story-management-endpoints)
- [Lullaby Endpoints](#lullaby-endpoints)
- [Voice Clone Endpoints](#voice-clone-endpoints)
- [Avatar Management Endpoints](#avatar-management-endpoints)
- [Story Sharing Endpoints](#story-sharing-endpoints)
- [Push Notification Endpoints](#push-notification-endpoints)
- [Utility Endpoints](#utility-endpoints)

---

## Authentication Endpoints

### 1. Sign Up
- **Endpoint:** `POST /auth/signup`
- **Description:** Register a new user account
- **Request Body:**
  ```json
  {
    "email": "string",
    "password": "string",
    "display_name": "string (optional)"
  }
  ```
- **Service:** `apiService.signUp()`

### 2. Sign In
- **Endpoint:** `POST /auth/signin`
- **Description:** Authenticate existing user
- **Request Body:**
  ```json
  {
    "email": "string",
    "password": "string"
  }
  ```
- **Service:** `apiService.signIn()`

### 3. Register User Profile
- **Endpoint:** `POST /auth/register`
- **Description:** Complete user profile registration with parent and child info
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "parent": {
      "name": "string",
      "email": "string",
      "phone_number": "string (optional)",
      "avatar_seed": "string",
      "avatar_style": "string",
      "avatar_generated": "boolean"
    },
    "child": {
      "name": "string",
      "age": "number",
      "gender": "male|female|other",
      "interests": ["string"],
      "image_url": "string (optional)",
      "avatar_seed": "string",
      "avatar_style": "string",
      "avatar_generated": "boolean"
    },
    "system_prompt": "string (optional)",
    "child_image_base64": "string (optional)"
  }
  ```
- **Service:** `apiService.registerUserProfile()`

### 4. Verify Token
- **Endpoint:** `POST /auth/verify-token`
- **Description:** Verify Firebase authentication token
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `apiService.verifyToken()`

### 5. Refresh Token
- **Endpoint:** `POST /auth/refresh-token`
- **Description:** Refresh expired authentication token
- **Request Body:**
  ```json
  {
    "refresh_token": "string"
  }
  ```
- **Service:** `apiService.refreshToken()`

### 6. Sign Out
- **Endpoint:** `POST /auth/signout`
- **Description:** Sign out user and invalidate session
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `apiService.signOut()`

### 7. Request Password Reset OTP
- **Endpoint:** `POST /auth/password-reset`
- **Description:** Request OTP for password reset
- **Request Body:**
  ```json
  {
    "email": "string"
  }
  ```
- **Service:** `apiService.requestPasswordResetOTP()`

### 8. Validate OTP
- **Endpoint:** `POST /auth/validate-otp`
- **Description:** Validate password reset OTP
- **Request Body:**
  ```json
  {
    "email": "string",
    "otp": "string"
  }
  ```
- **Service:** `apiService.validateOTP()`

### 9. Reset Password with OTP
- **Endpoint:** `POST /auth/reset-password`
- **Description:** Reset password using validated OTP
- **Request Body:**
  ```json
  {
    "email": "string",
    "otp": "string",
    "new_password": "string"
  }
  ```
- **Service:** `apiService.resetPasswordWithOTP()`

### 10. Validate Reset Token
- **Endpoint:** `POST /auth/validate-reset-token`
- **Description:** Validate password reset token
- **Request Body:**
  ```json
  {
    "token": "string",
    "email": "string"
  }
  ```
- **Service:** `apiService.validateResetToken()`

### 11. Reset Password with Token
- **Endpoint:** `POST /auth/reset-password-with-token`
- **Description:** Reset password using reset token
- **Request Body:**
  ```json
  {
    "token": "string",
    "email": "string",
    "new_password": "string"
  }
  ```
- **Service:** `apiService.resetPassword()`

---

## User Profile Endpoints

### 1. Get User Profile
- **Endpoint:** `GET /users/profile?firebase_token={token}`
- **Description:** Retrieve user profile information
- **Authentication:** Query parameter
- **Service:** `apiService.getUserProfile()`

### 2. Update User Profile
- **Endpoint:** `PUT /users/profile`
- **Description:** Update user profile information
- **Request Body:** User profile data
- **Service:** `apiService.updateUserProfile()`

---

## Children Management Endpoints

### 1. Create Child
- **Endpoint:** `POST /children`
- **Description:** Create a new child profile
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "name": "string",
    "age": "number",
    "gender": "male|female|other",
    "interests": ["string"],
    "avatar_seed": "string (optional)",
    "avatar_style": "string (optional)"
  }
  ```
- **Service:** `childrenService.createChild()`

### 2. List Children
- **Endpoint:** `GET /children`
- **Description:** Get all children for authenticated user
- **Authentication:** Bearer token
- **Service:** `childrenService.listChildren()`

### 3. Get Child Details
- **Endpoint:** `GET /children/{child_id}`
- **Description:** Get detailed information about a specific child
- **Authentication:** Bearer token
- **Service:** `childrenService.getChildDetails()`

### 4. Update Child
- **Endpoint:** `PUT /children/{child_id}`
- **Description:** Update child profile information
- **Authentication:** Bearer token
- **Request Body:** Child update data
- **Service:** `childrenService.updateChild()`

### 5. Delete Child
- **Endpoint:** `DELETE /children/{child_id}`
- **Description:** Delete a child profile
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `childrenService.deleteChild()`

### 6. Set Default Child
- **Endpoint:** `POST /children/{child_id}/select`
- **Description:** Set a child as the default for story generation
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `childrenService.setDefaultChild()`

### 7. Get Default Child
- **Endpoint:** `GET /children/default`
- **Description:** Get the default child profile
- **Authentication:** Bearer token
- **Service:** `childrenService.getDefaultChild()`

### 8. Get Child Stories
- **Endpoint:** `GET /children/{child_id}/stories?limit={limit}&offset={offset}`
- **Description:** Get stories for a specific child
- **Authentication:** Bearer token
- **Service:** `childrenService.getChildStories()`

### 9. Update Child System Prompt
- **Endpoint:** `PATCH /children/{child_id}/system-prompt`
- **Description:** Update the system prompt for story generation
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "system_prompt": "string"
  }
  ```
- **Service:** `childrenService.updateChildSystemPrompt()`

### 10. Select Child Voice Clone
- **Endpoint:** `POST /children/{child_id}/voice-clone/select`
- **Description:** Assign a voice clone to a child
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "voice_clone_id": "string"
  }
  ```
- **Service:** `childrenService.selectChildVoiceClone()`

### 11. Link Child Reference Image
- **Endpoint:** `POST /children/{child_id}/reference-images/link`
- **Description:** Link a reference image to a child profile
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "reference_image_id": "string"
  }
  ```
- **Service:** `childrenService.linkChildReferenceImage()`

### 12. Get Children Stats
- **Endpoint:** `GET /children/stats`
- **Description:** Get aggregate statistics for all children
- **Authentication:** Bearer token
- **Service:** `childrenService.getChildrenStats()`

### 13. Get Child Profile Picture
- **Endpoint:** `GET /children/{child_id}/profile-picture?firebase_token={token}`
- **Description:** Retrieve child's profile picture
- **Authentication:** Query parameter
- **Service:** `apiService.getChildProfilePicture()`

### 14. Upload Child Profile Picture
- **Endpoint:** `POST /children/{child_id}/profile-picture`
- **Description:** Upload a new profile picture for a child
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "image_base64": "string"
  }
  ```
- **Service:** `apiService.uploadChildProfilePicture()`

### 15. Delete Child Profile Picture
- **Endpoint:** `DELETE /children/{child_id}/profile-picture`
- **Description:** Delete child's profile picture
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `apiService.deleteChildProfilePicture()`

---

## Story Management Endpoints

### 1. Generate Story
- **Endpoint:** `POST /stories/generate`
- **Description:** Generate a new personalized story
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "prompt": "string",
    "length": "string",
    "isfemale": "boolean",
    "age_range": "string",
    "interests": ["string"],
    "child_name": "string",
    "child_age": "number",
    "art_style": "string",
    "voice_option": "string",
    "dimensions": "string (optional)"
  }
  ```
- **Service:** `apiService.generateStory()`

### 3. Fetch Story Status
- **Endpoint:** `GET /stories/fetch/{story_id}`
- **Description:** Get the current status of a story generation
- **Service:** `apiService.fetchStoryStatus()`

### 4. Get User Stories
- **Endpoint:** `GET /stories/user/stories?limit={limit}&offset={offset}`
- **Description:** Retrieve all stories for authenticated user
- **Authentication:** Bearer token
- **Service:** `apiService.getUserStories()`

### 5. Get Story IDs (Debug)
- **Endpoint:** `GET /stories/user/{token}/story-ids`
- **Description:** Get list of story IDs for debugging
- **Service:** `apiService.getUserStoryIds()`

### 6. Get Story Details
- **Endpoint:** `GET /stories/details/{story_id}`
- **Description:** Get detailed information about a specific story
- **Service:** `apiService.getStoryDetails()`

### 7. Delete Story (Legacy)
- **Endpoint:** `DELETE /stories/user/{token}/story/{story_id}`
- **Description:** Delete a user's story (legacy endpoint)
- **Service:** `apiService.deleteUserStory()`

### 8. Delete Story
- **Endpoint:** `DELETE /stories/delete/{story_id}`
- **Description:** Delete a story
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "firebase_token": "string"
  }
  ```
- **Service:** `apiService.deleteStory()`

### 9. Update System Prompt
- **Endpoint:** `POST /stories/system-prompt`
- **Description:** Update the system prompt for story generation
- **Request Body:**
  ```json
  {
    "firebase_token": "string",
    "system_prompt": "string"
  }
  ```
- **Service:** `apiService.updateSystemPrompt()`

---

## Lullaby Endpoints

### 1. Generate Lullaby
- **Endpoint:** `POST /lullabies/generate`
- **Description:** Generate a new personalized lullaby (async with WebSocket)
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "description": "string",
    "child_id": "string"
  }
  ```
- **Service:** `lullabyService.generateLullaby()`
- **Note:** Returns immediately with lullaby_id. Generation takes 2-4 minutes in background.

### 2. List User Lullabies
- **Endpoint:** `GET /lullabies/`
- **Description:** Get all lullabies for authenticated user
- **Authentication:** Bearer token
- **Service:** `lullabyService.getUserLullabies()`

### 3. Get Lullaby
- **Endpoint:** `GET /lullabies/{lullaby_id}`
- **Description:** Get details of a specific lullaby
- **Authentication:** Bearer token
- **Service:** `lullabyService.getLullaby()`

### 4. Delete Lullaby
- **Endpoint:** `DELETE /lullabies/{lullaby_id}`
- **Description:** Delete a lullaby
- **Authentication:** Bearer token
- **Service:** `lullabyService.deleteLullaby()`

---

## Voice Clone Endpoints

### 1. Create Voice Clone (Multipart)
- **Endpoint:** `POST /users/voice-clone/create-multipart`
- **Description:** Create a new voice clone from audio file
- **Authentication:** Via FormData field
- **Request Body:** FormData with:
  - `firebase_token`: string
  - `voice_name`: string
  - `description`: string (optional)
  - `audio_file`: File object (audio/wav)
- **Service:** `apiService.createVoiceClone()`

### 2. Update Voice Clone (Multipart)
- **Endpoint:** `PUT /users/voice-clone/update-multipart`
- **Description:** Update existing voice clone
- **Authentication:** Via FormData field
- **Request Body:** FormData with:
  - `firebase_token`: string
  - `voice_name`: string
  - `description`: string (optional)
  - `audio_file`: File object (audio/wav)
- **Service:** `apiService.updateVoiceClone()`

### 3. Get Voice Clone Status
- **Endpoint:** `GET /users/voice-clone/status?firebase_token={token}`
- **Description:** Get status of user's voice clone
- **Authentication:** Query parameter
- **Service:** `apiService.getVoiceCloneStatus()`

### 4. Delete Voice Clone
- **Endpoint:** `DELETE /users/voice-clone/delete?firebase_token={token}`
- **Description:** Delete user's voice clone
- **Authentication:** Query parameter
- **Service:** `apiService.deleteVoiceClone()`

---

## Avatar Management Endpoints

### 1. Update Avatar Settings
- **Endpoint:** `PUT /users/api/user/avatar?firebase_token={token}`
- **Description:** Update user avatar settings
- **Authentication:** Query parameter
- **Request Body:**
  ```json
  {
    "avatar_style": "string",
    "avatar_seed": "string",
    "avatar_url": "string"
  }
  ```
- **Service:** `apiService.updateAvatarSettings()`

### 2. Get Avatar Settings
- **Endpoint:** `GET /users/api/user/avatar?firebase_token={token}`
- **Description:** Retrieve user avatar settings
- **Authentication:** Query parameter
- **Service:** `apiService.getAvatarSettings()`

---

## Story Sharing Endpoints

### 1. Enable Story Sharing
- **Endpoint:** `POST /stories/share/enable/{story_id}`
- **Description:** Enable sharing for a story with custom settings
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "allow_custom_title": "boolean (optional)",
    "allow_custom_description": "boolean (optional)",
    "expires_in_days": "number (optional)"
  }
  ```
- **Service:** `apiService.enableStorySharing()`

### 2. Disable Story Sharing
- **Endpoint:** `POST /stories/share/disable/{story_id}`
- **Description:** Disable sharing for a story
- **Authentication:** Bearer token
- **Service:** `apiService.disableStorySharing()`

### 3. Track Share Access
- **Endpoint:** `POST /stories/share/track/{story_id}`
- **Description:** Track when a user accesses a shared story
- **Authentication:** Bearer token
- **Service:** `apiService.trackShareAccess()`

### 4. Get Shared Stories
- **Endpoint:** `GET /stories/share/received?limit={limit}&offset={offset}`
- **Description:** Get stories that have been shared with the user
- **Authentication:** Bearer token
- **Service:** `apiService.getSharedStories()`

### 5. View Shared Story
- **Endpoint:** `GET /stories/share/view/{story_id}`
- **Description:** View a shared story (public endpoint)
- **Authentication:** None (public)
- **Service:** `apiService.viewSharedStory()`

---

## Push Notification Endpoints

### 1. Register Device Token
- **Endpoint:** `POST /notifications/register`
- **Description:** Register device for push notifications
- **Authentication:** Bearer token
- **Request Body:**
  ```json
  {
    "user_id": "string",
    "device_token": "string",
    "platform": "ios|android",
    "device_info": {
      "model": "string",
      "os_version": "string"
    }
  }
  ```
- **Service:** `notificationService.sendTokenToServer()`

---

## Utility Endpoints

### 1. Health Check
- **Endpoint:** `GET /health`
- **Description:** Check if the API server is healthy
- **Authentication:** None
- **Service:** `apiService.healthCheck()`

---

## WebSocket Endpoints

### 1. Story Generation WebSocket
- **URL:** `wss://api.junekids.xyz/ws/stories/{firebase_token}`
- **Description:** Real-time updates for story generation progress
- **Authentication:** Token in URL path
- **Usage:** Subscribe to story_id channels to receive updates

### 2. Lullaby Generation WebSocket
- **URL:** Provided in lullaby generation response as `websocket_endpoint`
- **Description:** Real-time updates for lullaby generation progress
- **Authentication:** Bearer token
- **Usage:** Connect to receive progress updates during lullaby generation

