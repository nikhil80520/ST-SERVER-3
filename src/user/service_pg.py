"""
User Service Module
Contains all business logic for user management using PostgreSQL.
Handles user profile creation, updates, deletion, and avatar management.
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
import base64
from fastapi import HTTPException
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import User, Child, UserReferenceImage, UserVoiceClone
from src.user.schema import ParentProfile, ChildProfile
from src.common_function.storage_service import StorageService
from src.common_function.cartesia_voice import CartesiaService
from src.user.account_status_service import account_status_service
from src.core.config import settings
import time


class UserService:
    """
    User service using PostgreSQL instead of Firebase Firestore
    All methods use SQLAlchemy ORM for database operations
    """
    
    def __init__(self):
        self.system_prompts: Dict[str, str] = {}  # In-memory cache
        
        # Profile cache with TTL (Time To Live)
        self._profile_cache: Dict[str, Dict[str, Any]] = {}  # user_id -> {data, timestamp}
        self._profile_cache_ttl = 300  # 5 minutes cache
        
        self._storage_service = None
        self._cartesia_service = None
    
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
    
    async def _get_user_id_from_firebase_id(self, db: AsyncSession, firebase_user_id: str) -> Optional[int]:
        """Helper: Convert firebase_user_id to integer user_id"""
        try:
            stmt = select(User.user_id).where(User.firebase_user_id == firebase_user_id)
            result = await db.execute(stmt)
            user_id = result.scalar_one_or_none()
            return user_id
        except Exception as e:
            print(f"❌ Error converting firebase_user_id to user_id: {e}")
            return None
    
    async def get_user_by_firebase_id(
        self,
        db: AsyncSession,
        firebase_user_id: str
    ) -> Optional[User]:
        """
        Get user by Firebase user ID.
        Returns User object or None if not found.
        
        Args:
            db: Database session
            firebase_user_id: Firebase UID from authentication token
            
        Returns:
            User object or None
        """
        try:
            stmt = select(User).where(User.firebase_user_id == firebase_user_id)
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            print(f"❌ Error getting user by firebase_id: {str(e)}")
            return None
    
    async def get_or_create_minimal_user(
        self,
        db: AsyncSession,
        firebase_user_id: str,
        email: str = None,
        display_name: str = None
    ) -> User:
        """
        Get user by firebase_user_id, or create a minimal user record if not found.
        This is used for auto-creating users when they signin but don't exist in PostgreSQL yet.
        
        Args:
            db: Database session
            firebase_user_id: Firebase UID
            email: Optional email (will fetch from Firebase Auth if not provided)
            display_name: Optional display name (will be split into first_name/last_name)
            
        Returns:
            User object (existing or newly created)
        """
        try:
            # Check if user exists
            user = await self.get_user_by_firebase_id(db, firebase_user_id)
            if user:
                return user
            
            # Fetch user info from Firebase Auth if email not provided
            if not email or not display_name:
                try:
                    from firebase_admin import auth
                    firebase_user = auth.get_user(firebase_user_id)
                    email = email or firebase_user.email
                    display_name = display_name or firebase_user.display_name
                except Exception as e:
                    print(f"⚠️ Could not fetch Firebase Auth user info: {str(e)}")
            
            # Parse display name
            name_parts = (display_name or "").split(maxsplit=1) if display_name else []
            first_name = name_parts[0] if len(name_parts) > 0 else None
            last_name = name_parts[1] if len(name_parts) > 1 else None
            
            # Create minimal user
            user = User(
                firebase_user_id=firebase_user_id,
                first_name=first_name,
                last_name=last_name,
                email=email or f"{firebase_user_id}@temp.com",  # Fallback email
                children_count=0,
                story_count=0,
                reference_images_count=0,
                account_status="trial_active",
                last_active=datetime.utcnow()
            )
            
            db.add(user)
            await db.commit()
            await db.refresh(user)
            
            print(f"✅ Auto-created minimal user: user_id={user.user_id}, firebase_id={firebase_user_id}, email={user.email}")
            return user
            
        except Exception as e:
            await db.rollback()
            print(f"❌ Error in get_or_create_minimal_user: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")
    
    async def create_user_profile(
        self, 
        db: AsyncSession,
        firebase_user_id: str,  # Changed from user_id
        parent: ParentProfile, 
        child: ChildProfile, 
        system_prompt: str = None, 
        child_image_base64: str = None, 
        voice_audio_base64: str = None
    ) -> Dict[str, Any]:
        """
        Create a new user profile in PostgreSQL
        Creates the parent account and the FIRST child automatically.
        
        Args:
            db: Database session
            firebase_user_id: Firebase UID from authentication
            parent: Parent profile data
            child: First child profile data
            system_prompt: Optional system prompt
            child_image_base64: Optional child image
            voice_audio_base64: Optional voice audio for cloning
        """
        try:
            # Check if user already exists by firebase_user_id
            existing_user = await self.get_user_by_firebase_id(db, firebase_user_id)
            
            if existing_user:
                raise HTTPException(status_code=400, detail="User already exists")
            
            # Parse parent name into first_name and last_name
            name_parts = (parent.name or "").split(maxsplit=1)
            first_name = name_parts[0] if len(name_parts) > 0 else None
            last_name = name_parts[1] if len(name_parts) > 1 else None
            
            # Create parent/user record
            user = User(
                firebase_user_id=firebase_user_id,
                first_name=first_name,
                last_name=last_name,
                email=parent.email,
                phone_number=parent.phone_number,
                avatar_seed=getattr(parent, 'avatar_seed', None),
                avatar_style=getattr(parent, 'avatar_style', 'adventurer'),
                avatar_generated=getattr(parent, 'avatar_generated', False),
                children_count=0,
                story_count=0,
                reference_images_count=0,
                account_status="trial_active",
                last_active=datetime.utcnow()
            )
            
            db.add(user)
            await db.flush()  # Flush to get the auto-generated user_id
            
            print(f"✅ Parent profile created in PostgreSQL: user_id={user.user_id}, firebase_id={firebase_user_id}")
            
            # Initialize account status (14-day free trial)
            try:
                account_status = await account_status_service.initialize_account_status(str(user.user_id))
                user.account_status_data = account_status.dict()
                print(f"✅ Account status initialized: {account_status.status}")
            except Exception as e:
                print(f"⚠️ Failed to initialize account status: {str(e)}")
            
            # Create the FIRST child profile
            first_child = None
            try:
                # Import child_service here to avoid circular dependency
                from src.children.service_pg import child_service_pg
                
                # ✅ Pass integer user_id directly (FK to user.user_id)
                first_child = await child_service_pg.create_child(
                    db=db,
                    user_id=user.user_id,  # Pass integer user_id (FK to user table)
                    name=child.name,
                    age=child.age,
                    interests=child.interests,
                    image_base64=child_image_base64,
                    avatar_seed=getattr(child, 'avatar_seed', None),
                    avatar_style=getattr(child, 'avatar_style', 'adventurer'),
                    system_prompt=system_prompt
                )
                
                # Update user's children count and default child
                user.children_count = 1
                user.default_child_id = first_child.child_id
                
                print(f"✅ First child profile created: {first_child.child_id}")
                
            except Exception as e:
                print(f"❌ Failed to create first child profile: {str(e)}")
                import traceback
                print(f"📋 Child creation traceback: {traceback.format_exc()}")
                # Continue without child - parent account is still created
                # Re-raise to see the actual error
                raise HTTPException(status_code=500, detail=f"Failed to create child: {str(e)}")
            
            # Handle voice cloning for the FIRST CHILD
            if voice_audio_base64 and first_child:
                try:
                    print(f"🎤 Processing voice cloning for first child")
                    
                    # Decode base64 audio
                    audio_data = base64.b64decode(voice_audio_base64)
                    print(f"   Decoded audio size: {len(audio_data)} bytes")
                    
                    # Create voice name using child's name
                    voice_name = f"{child.name.replace(' ', '_')}_voice_{firebase_user_id[:8]}"
                    print(f"   Voice name: {voice_name}")
                    
                    # Clone voice for this child
                    voice_clone_id = await self.cartesia_service.clone_voice_from_audio(
                        audio_data, str(user.user_id), voice_name
                    )
                    
                    if voice_clone_id:
                        print(f"✅ Voice cloned successfully for first child: {voice_clone_id}")
                except Exception as e:
                    print(f"⚠️ Failed to clone voice for first child: {str(e)}")
            
            # Commit the transaction
            await db.commit()
            await db.refresh(user)
            
            # Build full parent name
            parent_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            
            # Build response
            profile_data = {
                'user_id': user.user_id,  # Return integer user_id
                'firebase_user_id': user.firebase_user_id,  # Also return firebase_user_id
                'parent': {
                    'name': parent_name,
                    'email': user.email,
                    'phone_number': user.phone_number,
                    'avatar_seed': user.avatar_seed,
                    'avatar_style': user.avatar_style,
                    'avatar_generated': user.avatar_generated
                },
                'children_count': user.children_count,
                'default_child_id': user.default_child_id,
                'created_at': user.created_at.isoformat(),
                'updated_at': user.updated_at.isoformat(),
                'story_count': user.story_count,
                'last_active': user.last_active.isoformat() if user.last_active else None,
                'account_status': user.account_status_data or {}
            }
            
            if first_child:
                profile_data['first_child'] = first_child.dict()
            
            return profile_data
            
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to create user profile: {str(e)}")
    
    async def get_user_profile(self, db: AsyncSession, firebase_user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user profile from PostgreSQL by Firebase user ID
        Includes parent info, children list, and relations
        WITH CACHING: 5-minute TTL to reduce database reads
        
        Args:
            db: Database session
            firebase_user_id: Firebase UID from authentication
        """
        try:
            # Check cache first (cache by firebase_user_id)
            if firebase_user_id in self._profile_cache:
                cached_data = self._profile_cache[firebase_user_id]
                cache_age = time.time() - cached_data['timestamp']
                if cache_age < self._profile_cache_ttl:
                    print(f"💾 Using cached profile for firebase_user {firebase_user_id} (age: {cache_age:.1f}s)")
                    return cached_data['data']
                else:
                    print(f"⏰ Profile cache expired for firebase_user {firebase_user_id} (age: {cache_age:.1f}s)")
                    del self._profile_cache[firebase_user_id]
            
            print(f"🔍 Fetching fresh profile for firebase_user {firebase_user_id} from PostgreSQL")
            
            # Query user with relationships loaded
            stmt = (
                select(User)
                .options(
                    selectinload(User.children),
                    selectinload(User.reference_images),
                    selectinload(User.voice_clones)
                )
                .where(User.firebase_user_id == firebase_user_id)
            )
            
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                return None
            
            # Build full parent name
            parent_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            
            # Build profile dictionary
            profile = {
                'user_id': user.user_id,  # Integer user_id
                'firebase_user_id': user.firebase_user_id,  # Firebase UID
                'parent': {
                    'name': parent_name,
                    'email': user.email,
                    'phone_number': user.phone_number,
                    'avatar_seed': user.avatar_seed,
                    'avatar_style': user.avatar_style,
                    'avatar_generated': user.avatar_generated,
                    'avatar_url': user.avatar_url,
                    'avatar_updated_at': user.avatar_updated_at.isoformat() if user.avatar_updated_at else None
                },
                'children_count': user.children_count,
                'default_child_id': user.default_child_id,
                'story_count': user.story_count,
                'reference_images_count': user.reference_images_count,
                'account_status': user.account_status,
                'account_status_data': user.account_status_data or {},
                'token_balance': user.token_balance,
                'created_at': user.created_at.isoformat(),
                'updated_at': user.updated_at.isoformat(),
                'last_active': user.last_active.isoformat() if user.last_active else None
            }
            
            # Add children list
            children_list = []
            for child in user.children:
                if child.is_active:  # Only include active children
                    child_dict = {
                        'child_id': child.child_id,
                        'name': child.name,
                        'age': child.age,
                        'interests': child.interests or [],
                        'image_url': child.image_url,
                        'avatar_seed': None,  # Not in Child table
                        'avatar_style': None,  # Not in Child table
                        'avatar_url': None,  # Not in Child table
                        'system_prompt': child.child_prompt,  # Database has child_prompt
                        'voice_clone_id': child.voice_clone_id,
                        'is_active': child.is_active,
                        'created_at': child.created_at.isoformat(),
                        'updated_at': child.updated_at.isoformat()
                    }
                    children_list.append(child_dict)
            
            profile['children'] = children_list
            
            # Add reference images
            ref_images = []
            for ref_img in user.reference_images:
                ref_images.append({
                    'reference_image_id': ref_img.reference_image_id,
                    'image_url': ref_img.image_url,
                    'storage_path': ref_img.storage_path,
                    'description': ref_img.description,
                    'file_size': ref_img.file_size,
                    'mime_type': ref_img.mime_type,
                    'created_at': ref_img.created_at.isoformat(),
                    'updated_at': ref_img.updated_at.isoformat()
                })
            
            profile['reference_images'] = ref_images
            
            # Get default child if available
            if user.default_child_id:
                default_child = next(
                    (c for c in children_list if c['child_id'] == user.default_child_id),
                    None
                )
                if default_child:
                    profile['default_child'] = default_child
            
            # Cache the profile (cache by firebase_user_id)
            self._profile_cache[firebase_user_id] = {
                'data': profile,
                'timestamp': time.time()
            }
            print(f"💾 Cached profile for firebase_user {firebase_user_id}")
            
            return profile
            
        except Exception as e:
            print(f"Error getting user profile: {str(e)}")
            return None
    
    async def update_last_active(self, db: AsyncSession, user_id: str):
        """Update user's last_active timestamp"""
        try:
            stmt = (
                update(User)
                .where(User.user_id == user_id)
                .values(last_active=datetime.utcnow())
            )
            await db.execute(stmt)
            await db.commit()
            
            # Invalidate cache
            if user_id in self._profile_cache:
                del self._profile_cache[user_id]
                
        except Exception as e:
            print(f"Failed to update last_active for user {user_id}: {str(e)}")
            await db.rollback()
    
    def get_user_system_prompt(self, user_id: str) -> str:
        """Get user's system prompt from memory or default"""
        return self.system_prompts.get(user_id, settings.default_system_prompt)
    
    def _invalidate_cache(self, user_id: str):
        """Invalidate user's profile cache"""
        if user_id in self._profile_cache:
            print(f"🗑️ Invalidating profile cache for user {user_id}")
            del self._profile_cache[user_id]

    async def get_user_by_firebase_userid(self, firebase_userid: str, session: AsyncSession) -> Optional[int]:
        """
        Get user ID by Firebase user ID.
        Returns user_id (int) or raises HTTPException if not found.
        """
        try:
            statement = select(User.user_id).where(User.firebase_user_id == firebase_userid)
            result = await session.execute(statement)
            user_id: Optional[int] = result.scalar_one_or_none()
            
            if not user_id:
                raise HTTPException(status_code=404, detail="User not found")

            # logger.info(user)
            return user_id
        except HTTPException:
            raise
        except Exception as e:
            # await session.rollback() # Session rollback is usually handled by the caller or dependency
            print(f"❌ Error in get_user_by_firebase_userid: {str(e)}")
            # log_exception_db = LogExceptionDB(99999, "get_user_by_firebase_user_id")
            # await log_exception_db.init()
            raise e


# Global singleton instance
user_service = UserService()

# Backward compatibility alias
user_service_pg = user_service
UserServicePostgreSQL = UserService
