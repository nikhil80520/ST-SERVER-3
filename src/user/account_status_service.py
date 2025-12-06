"""
Account Status Service
======================
Handles account status validation, updates, and access control based on subscription state.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
from fastapi import HTTPException
from firebase_admin import firestore
from src.user.schema import AccountStatus, AccountStatusInfo
from src.common_function.firebase_init import get_firestore_client

class AccountStatusService:
    """Service for managing user account status and access control"""
    
    def __init__(self):
        self._db = None
        self.users_collection = 'users'
    
    @property
    def db(self):
        """Lazy initialization of Firestore client"""
        if self._db is None:
            self._db = get_firestore_client()
        return self._db
    
    def get_default_trial_days(self) -> int:
        """Get default trial period in days (configurable)"""
        return 14  # 14-day free trial
    
    def get_grace_period_days(self) -> int:
        """Get grace period after payment failure in days"""
        return 7  # 7-day grace period
    
    async def initialize_account_status(self, user_id: str) -> AccountStatusInfo:
        """
        Initialize account status for new user (trial_active)
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            AccountStatusInfo with trial_active status
        """
        trial_end_date = (datetime.utcnow() + timedelta(days=self.get_default_trial_days())).isoformat()
        
        status_info = AccountStatusInfo(
            status=AccountStatus.TRIAL_ACTIVE,
            trial_end_date=trial_end_date,
            can_access_content=True,
            can_create_stories=True,
            requires_payment=False,
            message=f"Welcome! Your {self.get_default_trial_days()}-day free trial is active.",
            action_required=None
        )
        
        # Save to Firestore
        await self._save_account_status(user_id, status_info)
        
        print(f"✅ Account status initialized for user {user_id}: {status_info.status}")
        return status_info
    
    async def get_account_status(self, user_id: str) -> AccountStatusInfo:
        """
        Get current account status for user
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            AccountStatusInfo with current status
        """
        try:
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                # User doesn't exist, return trial_active as default
                return await self.initialize_account_status(user_id)
            
            user_data = doc.to_dict()
            account_status_data = user_data.get('account_status', {})
            
            # If no account status exists, initialize it
            if not account_status_data:
                return await self.initialize_account_status(user_id)
            
            # Parse account status
            status_info = AccountStatusInfo(**account_status_data)
            
            # Auto-update status if needed (e.g., trial expired)
            updated_status = await self._check_and_update_status(user_id, status_info)
            
            return updated_status
            
        except Exception as e:
            print(f"❌ Error getting account status for {user_id}: {e}")
            # Return trial_active as fallback
            return AccountStatusInfo(
                status=AccountStatus.TRIAL_ACTIVE,
                can_access_content=True,
                can_create_stories=True,
                requires_payment=False,
                message="Unable to verify account status. Using trial mode.",
                action_required=None
            )
    
    async def _check_and_update_status(self, user_id: str, current_status: AccountStatusInfo) -> AccountStatusInfo:
        """
        Check if status needs to be updated based on dates (e.g., trial expired, grace period ended)
        
        Args:
            user_id: Firebase user ID
            current_status: Current account status
            
        Returns:
            Updated AccountStatusInfo if changes were made
        """
        now = datetime.utcnow()
        updated = False
        
        # Check trial expiration
        if current_status.status == AccountStatus.TRIAL_ACTIVE and current_status.trial_end_date:
            trial_end = datetime.fromisoformat(current_status.trial_end_date.replace('Z', '+00:00'))
            if now >= trial_end:
                current_status.status = AccountStatus.TRIAL_EXPIRED
                current_status.can_create_stories = False
                current_status.requires_payment = True
                current_status.message = "Your free trial has ended. Subscribe to continue creating stories."
                current_status.action_required = "subscribe"
                updated = True
                print(f"⏰ Trial expired for user {user_id}")
        
        # Check grace period expiration
        if current_status.status == AccountStatus.GRACE_PERIOD and current_status.grace_period_end_date:
            grace_end = datetime.fromisoformat(current_status.grace_period_end_date.replace('Z', '+00:00'))
            if now >= grace_end:
                current_status.status = AccountStatus.SUSPENDED_UNPAID
                current_status.can_access_content = True  # Can view old stories
                current_status.can_create_stories = False  # Cannot create new ones
                current_status.requires_payment = True
                current_status.message = "Your account is suspended due to payment issues. Update payment to continue."
                current_status.action_required = "update_payment"
                updated = True
                print(f"🚫 Account suspended for user {user_id} (grace period expired)")
        
        # Save updated status if changed
        if updated:
            await self._save_account_status(user_id, current_status)
        
        return current_status
    
    async def _save_account_status(self, user_id: str, status_info: AccountStatusInfo):
        """Save account status to Firestore"""
        try:
            doc_ref = self.db.collection(self.users_collection).document(user_id)
            # Use set with merge=True to create document if it doesn't exist
            doc_ref.set({
                'account_status': status_info.model_dump(),
                'updated_at': datetime.utcnow().isoformat()
            }, merge=True)
        except Exception as e:
            print(f"❌ Error saving account status for {user_id}: {e}")
    
    async def update_to_paid(self, user_id: str, subscription_end_date: Optional[str] = None) -> AccountStatusInfo:
        """
        Update account to active_paid status after successful payment
        
        Args:
            user_id: Firebase user ID
            subscription_end_date: Optional end date for subscription (ISO 8601)
            
        Returns:
            Updated AccountStatusInfo
        """
        current_status = await self.get_account_status(user_id)
        
        current_status.status = AccountStatus.ACTIVE_PAID
        current_status.subscription_end_date = subscription_end_date or (datetime.utcnow() + timedelta(days=30)).isoformat()
        current_status.last_payment_date = datetime.utcnow().isoformat()
        current_status.can_access_content = True
        current_status.can_create_stories = True
        current_status.requires_payment = False
        current_status.message = "Your subscription is active. Enjoy creating stories!"
        current_status.action_required = None
        current_status.payment_failed_date = None
        current_status.grace_period_end_date = None
        
        await self._save_account_status(user_id, current_status)
        print(f"✅ Account activated (paid) for user {user_id}")
        
        return current_status
    
    async def mark_payment_failed(self, user_id: str) -> AccountStatusInfo:
        """
        Mark account as payment_failed and start grace period
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            Updated AccountStatusInfo with grace_period status
        """
        current_status = await self.get_account_status(user_id)
        
        current_status.status = AccountStatus.GRACE_PERIOD
        current_status.payment_failed_date = datetime.utcnow().isoformat()
        current_status.grace_period_end_date = (datetime.utcnow() + timedelta(days=self.get_grace_period_days())).isoformat()
        current_status.can_access_content = True  # Still allow access during grace period
        current_status.can_create_stories = True  # Still allow creation during grace period
        current_status.requires_payment = True
        current_status.message = f"Payment failed. Please update your payment method within {self.get_grace_period_days()} days."
        current_status.action_required = "update_payment"
        
        await self._save_account_status(user_id, current_status)
        print(f"⚠️ Payment failed for user {user_id}, grace period started")
        
        return current_status
    
    async def cancel_subscription(self, user_id: str) -> AccountStatusInfo:
        """
        Cancel user subscription
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            Updated AccountStatusInfo with cancelled status
        """
        current_status = await self.get_account_status(user_id)
        
        current_status.status = AccountStatus.CANCELLED
        current_status.cancellation_date = datetime.utcnow().isoformat()
        current_status.can_access_content = True  # Can still view existing stories
        current_status.can_create_stories = False  # Cannot create new stories
        current_status.requires_payment = False
        current_status.message = "Your subscription has been cancelled. You can still view your existing stories."
        current_status.action_required = "resubscribe"
        
        await self._save_account_status(user_id, current_status)
        print(f"🚫 Subscription cancelled for user {user_id}")
        
        return current_status
    
    async def disable_by_admin(self, user_id: str, reason: str) -> AccountStatusInfo:
        """
        Disable account by admin (security, policy violation, etc.)
        
        Args:
            user_id: Firebase user ID
            reason: Reason for disabling
            
        Returns:
            Updated AccountStatusInfo with disabled_by_admin status
        """
        current_status = await self.get_account_status(user_id)
        
        current_status.status = AccountStatus.DISABLED_BY_ADMIN
        current_status.disabled_date = datetime.utcnow().isoformat()
        current_status.disabled_reason = reason
        current_status.can_access_content = False
        current_status.can_create_stories = False
        current_status.requires_payment = False
        current_status.message = f"Your account has been disabled. Reason: {reason}"
        current_status.action_required = "contact_support"
        
        await self._save_account_status(user_id, current_status)
        print(f"🔒 Account disabled by admin for user {user_id}: {reason}")
        
        return current_status
    
    async def mark_deleted(self, user_id: str) -> AccountStatusInfo:
        """
        Mark account as deleted (for GDPR compliance, etc.)
        
        Args:
            user_id: Firebase user ID
            
        Returns:
            Updated AccountStatusInfo with deleted status
        """
        current_status = await self.get_account_status(user_id)
        
        current_status.status = AccountStatus.DELETED
        current_status.can_access_content = False
        current_status.can_create_stories = False
        current_status.requires_payment = False
        current_status.message = "This account has been deleted."
        current_status.action_required = None
        
        await self._save_account_status(user_id, current_status)
        print(f"🗑️ Account marked as deleted for user {user_id}")
        
        return current_status
    
    def validate_access(self, status_info: AccountStatusInfo, action: str = "access_content") -> Tuple[bool, Optional[str]]:
        """
        Validate if user can perform an action based on account status
        
        Args:
            status_info: User's account status info
            action: Action to validate ("access_content", "create_story", "view_profile")
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        # Deleted accounts have no access
        if status_info.status == AccountStatus.DELETED:
            return False, "Account has been deleted"
        
        # Disabled accounts have no access
        if status_info.status == AccountStatus.DISABLED_BY_ADMIN:
            return False, f"Account disabled: {status_info.disabled_reason or 'Contact support'}"
        
        # Action-specific validation
        if action == "create_story":
            if not status_info.can_create_stories:
                if status_info.status == AccountStatus.TRIAL_EXPIRED:
                    return False, "Free trial expired. Subscribe to create stories."
                elif status_info.status == AccountStatus.SUSPENDED_UNPAID:
                    return False, "Account suspended. Update payment to continue."
                elif status_info.status == AccountStatus.CANCELLED:
                    return False, "Subscription cancelled. Resubscribe to create stories."
                else:
                    return False, "Cannot create stories with current account status"
            return True, None
        
        elif action == "access_content":
            if not status_info.can_access_content:
                return False, "Cannot access content with current account status"
            return True, None
        
        elif action == "view_profile":
            # Most statuses allow viewing profile (except deleted/disabled)
            return True, None
        
        # Default: allow access
        return True, None
    
    def get_http_error_for_status(self, status_info: AccountStatusInfo, action: str = "access_content") -> Optional[HTTPException]:
        """
        Get appropriate HTTPException for account status if action is not allowed
        
        Args:
            status_info: User's account status info
            action: Action being attempted
            
        Returns:
            HTTPException if action not allowed, None if allowed
        """
        is_allowed, error_message = self.validate_access(status_info, action)
        
        if not is_allowed:
            # Determine status code based on account status
            if status_info.status in [AccountStatus.TRIAL_EXPIRED, AccountStatus.SUSPENDED_UNPAID]:
                # Payment required
                return HTTPException(
                    status_code=402,  # Payment Required
                    detail={
                        "error": error_message,
                        "account_status": status_info.status.value,
                        "requires_payment": status_info.requires_payment,
                        "action_required": status_info.action_required,
                        "message": status_info.message
                    }
                )
            elif status_info.status == AccountStatus.CANCELLED:
                # Subscription cancelled
                return HTTPException(
                    status_code=403,  # Forbidden
                    detail={
                        "error": error_message,
                        "account_status": status_info.status.value,
                        "action_required": status_info.action_required,
                        "message": status_info.message
                    }
                )
            elif status_info.status in [AccountStatus.DISABLED_BY_ADMIN, AccountStatus.DELETED]:
                # Account disabled/deleted
                return HTTPException(
                    status_code=403,  # Forbidden
                    detail={
                        "error": error_message,
                        "account_status": status_info.status.value,
                        "message": status_info.message,
                        "action_required": status_info.action_required
                    }
                )
            else:
                # Generic access denied
                return HTTPException(
                    status_code=403,
                    detail={
                        "error": error_message,
                        "account_status": status_info.status.value,
                        "message": status_info.message
                    }
                )
        
        return None


# Global instance
account_status_service = AccountStatusService()
