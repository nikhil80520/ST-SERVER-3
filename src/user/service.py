from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import base64
from fastapi import HTTPException
from firebase_admin import firestore
from src.user.schema import ParentProfile, ChildProfile
from src.common_function.firebase_init import get_firestore_client, is_firebase_available
from src.common_function.storage_s3_service import S3StorageService as StorageService
from src.common_function.cartesia_voice import CartesiaService
from src.user.account_status_service import account_status_service
from src.config import settings
import time

class UserService:
    def __init__(self):
        self.users_collection = 'users'
        self.system_prompts = {}  # In-memory cache
        
        # Profile cache with TTL (Time To Live)
        self._profile_cache: Dict[str, Dict[str, Any]] = {}  # user_id -> {data, timestamp}
        self._profile_cache_ttl = 300  # 5 minutes cache
        
        # Don't initialize Firebase client here - do it lazily
        self._db = None
        self._storage_service = None
        self._cartesia_service = None
    
    @property
    def db(self):
        """Lazy initialization of Firestore client"""
        if self._db is None:
            self._db = get_firestore_client()
        return self._db
    
    @property
    def storage_service(self):
        """Lazy initialization of Storage service"""
        if self._storage_service is None:
            self._storage_service = StorageService()
        return self._storage_service
    
    @property
    def cartesia_service(self):
        """Lazy initialization of Cartesia service"""
        if self._cartesia_service is None:
            self._cartesia_service = CartesiaService()
        return self._cartesia_service
    
    async def create_user_profile(self, user_id: str, parent: ParentProfile, child: ChildProfile, system_prompt: str = None, child_image_base64: str = None, voice_audio_base64: str = None) -> Dict[str, Any]:
        """
        Create a new user profile in Firestore (PARENT-CENTRIC MODEL)
        This creates the parent account and the FIRST child automatically.
        """
        try:
            # Check if Firebase is available
            if not is_firebase_available() or self.db is None:
                raise HTTPException(status_code=503, detail="Firebase service is not available")
            
            # Import child_service here to avoid circular dependency
            from src.children.service import child_service
            
            # Create parent profile data (NEW: parent-centric model)
            profile_data = {
                'user_id': user_id,
                'parent': {
                    'name': parent.name,
                    'email': parent.email,
                    'phone_number': parent.phone_number,
                    'avatar_seed': getattr(parent, 'avatar_seed', None),
                    'avatar_style': getattr(parent, 'avatar_style', 'avataaars'),
                    'avatar_generated': getattr(parent, 'avatar_generated', False)
                },
                # NEW: Add children tracking fields
                'children_count': 0,  # Will be incremented when first child is created
                'default_child_id': None,  # Will be set when first child is created
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat(),
                'story_count': 0,
                'last_active': datetime.utcnow().isoformat()
            }
            
            # Save parent profile to Firestore FIRST
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            doc_ref.set(profile_data)
            print(f"✅ Parent profile created in Firebase: {user_id}")
            
            # Initialize account status (14-day free trial)
            try:
                account_status = await account_status_service.initialize_account_status(user_id)
                profile_data['account_status'] = account_status.dict()
                print(f"✅ Account status initialized: {account_status.status}")
            except Exception as e:
                print(f"⚠️ Failed to initialize account status: {str(e)}")
            
            # Create the FIRST child profile in children sub-collection
            try:
                first_child = await child_service.create_child(
                    user_id=user_id,
                    name=child.name,
                    age=child.age,
                    interests=child.interests,
                    image_base64=child_image_base64,
                    avatar_seed=getattr(child, 'avatar_seed', None),
                    avatar_style=getattr(child, 'avatar_style', 'avataaars'),
                    system_prompt=system_prompt
                )
                print(f"✅ First child profile created: {first_child.child_id}")
                
                # Add first child info to response
                profile_data['first_child'] = first_child.dict()
                profile_data['children_count'] = 1
                profile_data['default_child_id'] = first_child.child_id
                
            except Exception as e:
                print(f"⚠️ Failed to create first child profile: {str(e)}")
                # Continue without child - parent account is still created
            
            # Handle voice cloning for the FIRST CHILD
            if voice_audio_base64 and 'first_child' in profile_data:
                try:
                    print(f"🎤 Processing voice cloning for first child")
                    
                    # Decode base64 audio
                    audio_data = base64.b64decode(voice_audio_base64)
                    print(f"   Decoded audio size: {len(audio_data)} bytes")
                    
                    # Create voice name using child's name
                    voice_name = f"{child.name.replace(' ', '_')}_voice_{user_id[:8]}"
                    print(f"   Voice name: {voice_name}")
                    
                    # Clone voice for this child
                    voice_clone_id = await self.cartesia_service.clone_voice_from_audio(
                        audio_data, user_id, voice_name
                    )
                    
                    if voice_clone_id:
                        print(f"✅ Voice cloned successfully for first child: {voice_clone_id}")
                except Exception as e:
                    print(f"⚠️ Failed to clone voice for first child: {str(e)}")
            
            return profile_data
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create user profile: {str(e)}")
            return profile_data
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create user profile: {str(e)}")
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user profile from Firestore (PARENT-CENTRIC MODEL)
        Includes parent info, children list, and default child
        WITH CACHING: 5-minute TTL to reduce Firestore reads
        """
        try:
            # Check cache first
            if user_id in self._profile_cache:
                cached_data = self._profile_cache[user_id]
                cache_age = time.time() - cached_data['timestamp']
                if cache_age < self._profile_cache_ttl:
                    print(f"💾 Using cached profile for user {user_id} (age: {cache_age:.1f}s)")
                    return cached_data['data']
                else:
                    print(f"⏰ Profile cache expired for user {user_id} (age: {cache_age:.1f}s)")
                    del self._profile_cache[user_id]
            
            if not is_firebase_available() or self.db is None:
                return None
            
            print(f"🔍 Fetching fresh profile for user {user_id} from Firestore")
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            doc = doc_ref.get()
            
            if doc.exists:
                profile = doc.to_dict()
                
                # Convert datetime objects to ISO strings for JSON serialization
                def convert_datetime_to_iso(obj):
                    if isinstance(obj, datetime):
                        return obj.isoformat()
                    elif isinstance(obj, dict):
                        return {k: convert_datetime_to_iso(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [convert_datetime_to_iso(v) for v in obj]
                    return obj
                
                profile = convert_datetime_to_iso(profile)
                
                # NEW: Fetch children from sub-collection (parent-centric model)
                try:
                    from src.children.service import child_service
                    children = await child_service.get_all_children(user_id, include_inactive=False)
                    
                    # Convert children to dict format
                    children_list = []
                    for child in children:
                        child_dict = child.dict()
                        # Get child stats
                        child_with_stats = await child_service.get_child_with_stats(user_id, child.child_id)
                        if child_with_stats:
                            child_dict = child_with_stats.dict()
                        children_list.append(child_dict)
                    
                    profile['children'] = children_list
                    profile['children_count'] = len(children_list)
                    
                    # Get default child
                    default_child_id = profile.get('default_child_id')
                    if default_child_id:
                        default_child = await child_service.get_child(user_id, default_child_id)
                        if default_child:
                            profile['default_child'] = default_child.dict()
                    
                except Exception as e:
                    print(f"⚠️ Failed to fetch children: {str(e)}")
                    profile['children'] = []
                    profile['children_count'] = 0
                
                # BACKWARD COMPATIBILITY: If old 'child' field exists, keep it for legacy clients
                # This will be removed in future versions
                if 'child' in profile and not profile.get('children'):
                    print(f"⚠️ User {user_id} has old single-child structure - needs migration")
                
                # Fetch reference images from subcollection (kept for backward compatibility)
                try:
                    ref_images_ref = self.db.collection('users').document(user_id).collection('reference_images')
                    ref_images_docs = ref_images_ref.stream()
                    
                    reference_images = []
                    for doc in ref_images_docs:
                        ref_data = doc.to_dict()
                        reference_images.append({
                            'reference_image_id': ref_data.get('reference_image_id'),
                            'person_name': ref_data.get('person_name'),
                            'relation': ref_data.get('relation'),
                            'image_url': ref_data.get('image_url'),
                            'created_at': convert_datetime_to_iso(ref_data.get('created_at')),
                            'updated_at': convert_datetime_to_iso(ref_data.get('updated_at'))
                        })
                    
                    profile['reference_images'] = reference_images
                    profile['reference_images_count'] = len(reference_images)
                    
                except Exception as e:
                    print(f"⚠️ Failed to fetch reference images: {str(e)}")
                    profile['reference_images'] = []
                    profile['reference_images_count'] = 0
                
                # Load system prompt into memory if not already there (for backward compatibility)
                if user_id not in self.system_prompts and 'system_prompt' in profile:
                    self.system_prompts[user_id] = profile['system_prompt']
                
                # Get or initialize account status
                try:
                    account_status = await account_status_service.get_account_status(user_id)
                    profile['account_status'] = account_status.dict()
                except Exception as e:
                    print(f"⚠️ Failed to fetch account status for {user_id}: {str(e)}")
                    # Continue without account status
                
                # Cache the profile
                self._profile_cache[user_id] = {
                    'data': profile,
                    'timestamp': time.time()
                }
                print(f"💾 Cached profile for user {user_id}")
                
                return profile
            return None
            
        except Exception as e:
            print(f"Error getting user profile: {str(e)}")
            return None
    
    async def update_user_profile(self, user_id: str, parent: ParentProfile = None, child: ChildProfile = None, system_prompt: str = None, child_image_base64: str = None, voice_audio_base64: str = None) -> Dict[str, Any]:
        """Update user profile in Firestore"""
        try:
            if not is_firebase_available() or self.db is None:
                raise HTTPException(status_code=503, detail="Firebase service is not available")
            
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            
            # Get existing profile
            existing_profile = await self.get_user_profile(user_id)
            if not existing_profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            # Prepare updates
            updates = {
                'updated_at': datetime.utcnow().isoformat(),
                'last_active': datetime.utcnow().isoformat()
            }
            
            if parent:
                updates['parent'] = {
                    'name': parent.name,
                    'email': parent.email,
                    'phone_number': parent.phone_number,
                    'avatar_seed': getattr(parent, 'avatar_seed', None),
                    'avatar_style': getattr(parent, 'avatar_style', 'avataaars'),
                    'avatar_generated': getattr(parent, 'avatar_generated', False)
                }
            
            if child:
                # Handle image upload if provided
                image_url = existing_profile.get('child', {}).get('image_url')  # Keep existing image URL
                if child_image_base64:
                    try:
                        # Decode base64 image
                        image_data = base64.b64decode(child_image_base64)
                        # Upload new image to Firebase Storage
                        image_url = await self.storage_service.upload_user_image(image_data, user_id)
                        print(f"✅ Child profile image updated: {image_url}")
                    except Exception as e:
                        print(f"⚠️ Failed to upload child profile image: {str(e)}")
                        # Keep existing image if upload fails
                
                updates['child'] = {
                    'name': child.name,
                    'age': child.age,
                    'interests': child.interests,
                    'image_url': image_url,  # Updated or existing image URL
                    'avatar_seed': getattr(child, 'avatar_seed', None),
                    'avatar_style': getattr(child, 'avatar_style', 'avataaars'),
                    'avatar_generated': getattr(child, 'avatar_generated', False)
                }
                # Regenerate system prompt if child info changed
                if not system_prompt:
                    system_prompt = self._generate_personalized_prompt(child)
                    updates['system_prompt'] = system_prompt
            
            if system_prompt:
                updates['system_prompt'] = system_prompt
                self.system_prompts[user_id] = system_prompt
            
            # Handle voice cloning update if audio provided
            if voice_audio_base64:
                try:
                    print(f"🎤 Updating voice clone for user {user_id}")
                    
                    # Delete existing voice clone if it exists
                    existing_voice_clone = existing_profile.get('voice_clone')
                    if existing_voice_clone and existing_voice_clone.get('voice_id'):
                        old_voice_id = existing_voice_clone.get('voice_id')
                        print(f"🗑️ Deleting old voice clone: {old_voice_id}")
                        await self.cartesia_service.delete_cloned_voice(old_voice_id, user_id)
                    
                    # Decode base64 audio
                    audio_data = base64.b64decode(voice_audio_base64)
                    # Create voice name using parent's name or existing name
                    parent_name = parent.name if parent else existing_profile.get('parent', {}).get('name', 'User')
                    voice_name = f"{parent_name.replace(' ', '_')}_clone_{user_id[:8]}"
                    
                    # Clone new voice using Cartesia
                    voice_clone_id = await self.cartesia_service.clone_voice_from_audio(
                        audio_data, user_id, voice_name
                    )
                    
                    if voice_clone_id:
                        print(f"✅ Voice clone updated successfully: {voice_clone_id}")
                    else:
                        print(f"⚠️ Voice cloning failed, keeping existing voice settings")
                        
                except Exception as e:
                    print(f"⚠️ Failed to update voice clone: {str(e)}")
                    # Continue without voice clone update rather than failing the entire update
            
            # Update Firestore
            doc_ref.update(updates)
            
            # Invalidate cache since profile changed
            if user_id in self._profile_cache:
                print(f"🗑️ Invalidating profile cache for user {user_id}")
                del self._profile_cache[user_id]
            
            # Return updated profile
            return await self.get_user_profile(user_id)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")
    
    async def delete_user_data(self, user_id: str):
        """Delete user profile and associated data"""
        try:
            if not is_firebase_available() or self.db is None:
                raise HTTPException(status_code=503, detail="Firebase service is not available")
            
            # Delete user profile
            user_doc_ref = self.db.collection('users').document(user_id)
            user_doc_ref.delete()
            
            # Delete user stories
            stories_ref = self.db.collection('stories')
            user_stories = stories_ref.where('user_id', '==', user_id).stream()
            
            for story in user_stories:
                story.reference.delete()
            
            # Remove from memory
            if user_id in self.system_prompts:
                del self.system_prompts[user_id]
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete user data: {str(e)}")
    
    def get_user_system_prompt(self, user_id: str) -> str:
        """Get user's system prompt from memory or default"""
        return self.system_prompts.get(user_id, settings.default_system_prompt)
    
    async def update_avatar_settings(self, user_id: str, target: str, avatar_seed: str, avatar_style: str = "avataaars") -> Dict[str, Any]:
        """Update avatar settings for child or parent"""
        try:
            if not is_firebase_available() or self.db is None:
                raise HTTPException(status_code=503, detail="Firebase service is not available")
            
            if target not in ["child", "parent"]:
                raise HTTPException(status_code=400, detail="Target must be 'child' or 'parent'")
            
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            
            # Get existing profile
            existing_profile = await self.get_user_profile(user_id)
            if not existing_profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            # Prepare updates
            updates = {
                f'{target}.avatar_seed': avatar_seed,
                f'{target}.avatar_style': avatar_style,
                f'{target}.avatar_generated': True,
                'updated_at': datetime.utcnow().isoformat(),
                'last_active': datetime.utcnow().isoformat()
            }
            
            # Update Firestore
            doc_ref.update(updates)
            
            # Return updated profile
            return await self.get_user_profile(user_id)
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update avatar settings: {str(e)}")
    
    async def get_avatar_settings(self, user_id: str, target: str) -> Dict[str, Any]:
        """Get avatar settings for child or parent"""
        try:
            if target not in ["child", "parent"]:
                raise HTTPException(status_code=400, detail="Target must be 'child' or 'parent'")
            
            profile = await self.get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            target_data = profile.get(target, {})
            return {
                "avatar_seed": target_data.get('avatar_seed'),
                "avatar_style": target_data.get('avatar_style', 'avataaars'),
                "avatar_generated": target_data.get('avatar_generated', False)
            }
            
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get avatar settings: {str(e)}")

    async def update_user_avatar(self, user_id: str, avatar_data: Dict[str, str]) -> Dict[str, Any]:
        """Update user's unified avatar settings for cross-device consistency"""
        try:
            if not is_firebase_available() or self.db is None:
                raise HTTPException(status_code=503, detail="Firebase service is not available")
            
            # Validate required fields
            required_fields = ['avatar_style', 'avatar_seed', 'avatar_url']
            for field in required_fields:
                if field not in avatar_data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
            
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            
            # Check if user exists
            existing_profile = await self.get_user_profile(user_id)
            if not existing_profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            # Prepare avatar updates
            updates = {
                'avatar_style': avatar_data['avatar_style'],
                'avatar_seed': avatar_data['avatar_seed'],
                'avatar_url': avatar_data['avatar_url'],
                'avatar_updated_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat(),
                'last_active': datetime.utcnow().isoformat()
            }
            
            # Update Firestore
            doc_ref.update(updates)
            
            return {
                "success": True,
                "message": "Avatar updated successfully"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update avatar: {str(e)}")

    async def get_user_avatar(self, user_id: str) -> Dict[str, Any]:
        """Get user's unified avatar settings for cross-device consistency"""
        try:
            profile = await self.get_user_profile(user_id)
            if not profile:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            # Check if user has unified avatar settings
            if all(key in profile for key in ['avatar_style', 'avatar_seed', 'avatar_url']):
                avatar_data = {
                    "avatar_style": profile['avatar_style'],
                    "avatar_seed": profile['avatar_seed'],
                    "avatar_url": profile['avatar_url'],
                    "updated_at": profile.get('avatar_updated_at', profile.get('updated_at'))
                }
                
                # Convert datetime to ISO string if needed
                if isinstance(avatar_data.get('updated_at'), datetime):
                    avatar_data['updated_at'] = avatar_data['updated_at'].isoformat()
                
                return {
                    "success": True,
                    "avatar": avatar_data
                }
            else:
                return {
                    "success": True,
                    "avatar": None,
                    "message": "No avatar found"
                }
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get avatar: {str(e)}")

    def update_system_prompt(self, user_id: str, system_prompt: str):
        """Update system prompt in memory and Firestore"""
        self.system_prompts[user_id] = system_prompt
        
        if is_firebase_available() and self.db is not None:
            try:
                # Update in Firestore
                user_ref = self.db.collection('users').document(user_id)
                user_ref.update({
                    'system_prompt': system_prompt,
                    'updated_at': datetime.utcnow().isoformat()
                })
            except Exception as e:
                print(f"Failed to update system prompt in Firestore: {str(e)}")
    
    def _generate_personalized_prompt(self, child: ChildProfile) -> str:
        """Generate a personalized system prompt based on child's profile"""
        interests_str = ", ".join(child.interests) if child.interests else "various topics"
        
        age_appropriate_language = {
            range(3, 6): "very simple words and short sentences",
            range(6, 9): "simple language with some new vocabulary",
            range(9, 13): "age-appropriate language with educational elements"
        }
        
        language_level = "simple, engaging language"
        for age_range, description in age_appropriate_language.items():
            if child.age in age_range:
                language_level = description
                break
        
        # Add image reference if available
        image_reference = ""
        if hasattr(child, 'image_url') and child.image_url:
            image_reference = f"\n\nWhen {child.name} appears in stories, their appearance should be consistent with their profile image."
        
        personalized_prompt = f"""You are a creative children's storyteller creating stories for {child.name}, who is {child.age} years old and loves {interests_str}.

Create engaging, age-appropriate stories that are educational and fun. Use {language_level} that's perfect for a {child.age}-year-old.

Incorporate themes and elements related to {interests_str} when possible, making {child.name} feel like the stories are made just for them.

Structure your story into clear scenes that can be visualized. Each scene should be 2-3 sentences long and paint a vivid picture.

Make the stories positive, encouraging, and help build {child.name}'s imagination and confidence.{image_reference}"""

        return personalized_prompt
    
    async def update_voice_clone_id(self, user_id: str, voice_clone_id: Optional[str]) -> bool:
        """Update user's voice clone ID in Firestore"""
        try:
            if not self.db:
                print("⚠️ Firestore not available")
                return False
            
            user_ref = self.db.collection(self.users_collection).document(user_id)
            
            update_data = {
                'voice_clone_id': voice_clone_id,
                'voice_clone_updated_at': datetime.utcnow().isoformat(),
                'last_active': datetime.utcnow().isoformat()
            }
            
            # Remove voice_clone_id field if setting to None
            if voice_clone_id is None:
                update_data['voice_clone_id'] = firestore.DELETE_FIELD
            
            user_ref.update(update_data)
            
            action = "updated" if voice_clone_id else "removed"
            print(f"✅ Voice clone ID {action} for user {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to update voice clone ID for user {user_id}: {e}")
            return False