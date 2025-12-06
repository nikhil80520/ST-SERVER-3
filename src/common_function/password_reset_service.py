"""
Password Reset Service - OTP Based
=================================
Handles password reset using 6-digit OTP codes for better mobile experience.
"""

import random
import string
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import auth as firebase_auth
from src.common_function.firebase_init import get_firestore_client, is_firebase_available
from src.common_function.ses_email_service import email_service


class PasswordResetService:
    def __init__(self):
        self.db = None
        self.otp_expiry_minutes = 10  # 10 minutes expiry for OTP
        self.max_attempts = 3  # Maximum OTP verification attempts
    
    @property
    def firestore_db(self):
        """Lazy initialization of Firestore client"""
        if self.db is None and is_firebase_available():
            self.db = get_firestore_client()
        return self.db
    
    def _generate_otp(self) -> str:
        """Generate a 6-digit OTP"""
        return ''.join(random.choices(string.digits, k=6))
    
    def _hash_otp(self, otp: str) -> str:
        """Hash the OTP for secure storage"""
        return hashlib.sha256(otp.encode()).hexdigest()
    
    async def initiate_password_reset(self, email: str) -> Dict[str, Any]:
        """
        Initiate password reset process for a user by sending OTP
        
        Args:
            email: User's email address
            
        Returns:
            dict: Response with success status and message
        """
        try:
            if not is_firebase_available() or not self.firestore_db:
                return {
                    "success": False,
                    "message": "Password reset service not available"
                }
            
            # Check if user exists in Firebase Auth
            try:
                user = firebase_auth.get_user_by_email(email)
            except firebase_auth.UserNotFoundError:
                # For security, we don't reveal if the email exists or not
                return {
                    "success": True,
                    "message": "If an account with this email exists, you will receive a password reset code."
                }
            
            # Generate 6-digit OTP
            otp = self._generate_otp()
            otp_hash = self._hash_otp(otp)
            
            # Store OTP in Firestore with expiry
            expiry_time = datetime.now(timezone.utc) + timedelta(minutes=self.otp_expiry_minutes)
            
            # Remove any existing OTPs for this email
            await self._cleanup_user_otps(email)
            
            otp_data = {
                "email": email,
                "user_id": user.uid,
                "otp_hash": otp_hash,
                "created_at": datetime.now(timezone.utc),
                "expires_at": expiry_time,
                "used": False,
                "attempts": 0,
                "ip_address": None,  # You can add this from request if needed
                "user_agent": None   # You can add this from request if needed
            }
            
            # Store in password_reset_otps collection
            otp_doc = self.firestore_db.collection('password_reset_otps').document()
            otp_doc.set(otp_data)
            
            # Send OTP via email
            await email_service.send_password_reset_otp_email(
                user_email=email,
                otp_code=otp,
                user_name=user.display_name,
                expiry_minutes=self.otp_expiry_minutes
            )
            
            print(f"✅ Password reset OTP sent to user: {email}")
            
            return {
                "success": True,
                "message": "If an account with this email exists, you will receive a 6-digit verification code.",
                "otp_doc_id": otp_doc.id  # For internal tracking only
            }
            
        except Exception as e:
            print(f"❌ Password reset OTP initiation failed: {str(e)}")
            return {
                "success": False,
                "message": "Unable to process password reset request. Please try again later."
            }
    
    async def validate_otp(self, otp: str, email: str) -> Dict[str, Any]:
        """
        Validate a password reset OTP
        
        Args:
            otp: 6-digit OTP code
            email: User's email address
            
        Returns:
            dict: Validation result with user info if valid
        """
        try:
            if not is_firebase_available() or not self.firestore_db:
                return {
                    "valid": False,
                    "message": "Password reset service not available"
                }
            
            otp_hash = self._hash_otp(otp)
            
            # Query for matching OTP
            otp_query = (
                self.firestore_db.collection('password_reset_otps')
                .where('email', '==', email)
                .where('used', '==', False)
                .limit(1)
            )
            
            otp_docs = otp_query.get()
            
            if not otp_docs:
                return {
                    "valid": False,
                    "message": "No active reset code found for this email"
                }
            
            otp_doc = otp_docs[0]
            otp_data = otp_doc.to_dict()
            
            # Check if OTP has expired
            if datetime.now(timezone.utc) > otp_data['expires_at']:
                # Clean up expired OTP
                otp_doc.reference.delete()
                return {
                    "valid": False,
                    "message": "Reset code has expired. Please request a new one."
                }
            
            # Check attempts limit
            if otp_data.get('attempts', 0) >= self.max_attempts:
                # Clean up OTP after max attempts
                otp_doc.reference.delete()
                return {
                    "valid": False,
                    "message": "Too many incorrect attempts. Please request a new reset code."
                }
            
            # Check if OTP matches
            if otp_data['otp_hash'] != otp_hash:
                # Increment attempts
                otp_doc.reference.update({
                    "attempts": otp_data.get('attempts', 0) + 1
                })
                remaining_attempts = self.max_attempts - (otp_data.get('attempts', 0) + 1)
                return {
                    "valid": False,
                    "message": f"Incorrect code. {remaining_attempts} attempts remaining."
                }
            
            return {
                "valid": True,
                "message": "Code is valid",
                "otp_doc_id": otp_doc.id,
                "user_id": otp_data['user_id'],
                "email": otp_data['email']
            }
            
        except Exception as e:
            print(f"❌ OTP validation failed: {str(e)}")
            return {
                "valid": False,
                "message": "Unable to validate reset code"
            }
    
    async def reset_password(self, otp: str, email: str, new_password: str) -> Dict[str, Any]:
        """
        Reset user password using valid OTP
        
        Args:
            otp: 6-digit OTP code
            email: User's email address
            new_password: New password
            
        Returns:
            dict: Reset result
        """
        try:
            # First validate the OTP
            validation_result = await self.validate_otp(otp, email)
            
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "message": validation_result["message"]
                }
            
            user_id = validation_result["user_id"]
            otp_doc_id = validation_result["otp_doc_id"]
            
            # Update password in Firebase Auth
            firebase_auth.update_user(
                user_id,
                password=new_password
            )
            
            # Mark OTP as used and delete it
            otp_doc = self.firestore_db.collection('password_reset_otps').document(otp_doc_id)
            otp_doc.delete()
            
            # Clean up any other OTPs for this user
            await self._cleanup_user_otps(email)
            
            print(f"✅ Password reset successful for user: {email}")
            
            return {
                "success": True,
                "message": "Password has been reset successfully. You can now log in with your new password."
            }
            
        except Exception as e:
            print(f"❌ Password reset failed: {str(e)}")
            return {
                "success": False,
                "message": "Unable to reset password. Please try again or request a new reset code."
            }
    
    async def _cleanup_user_otps(self, email: str):
        """
        Clean up all OTPs for a user
        
        Args:
            email: User's email address
        """
        try:
            if not self.firestore_db:
                return
            
            # Get all OTPs for this email
            query = (
                self.firestore_db.collection('password_reset_otps')
                .where('email', '==', email)
            )
            
            docs = query.get()
            
            for doc in docs:
                doc.reference.delete()
            
            if docs:
                print(f"✅ Cleaned up {len(docs)} OTPs for user: {email}")
            
        except Exception as e:
            print(f"❌ Failed to cleanup user OTPs: {str(e)}")
    
    async def cleanup_expired_otps(self):
        """
        Clean up expired OTPs (can be called periodically)
        """
        try:
            if not self.firestore_db:
                return
            
            # Delete OTPs that expired more than 1 hour ago
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
            
            query = (
                self.firestore_db.collection('password_reset_otps')
                .where('expires_at', '<', cutoff_time)
            )
            
            docs = query.get()
            deleted_count = 0
            
            for doc in docs:
                doc.reference.delete()
                deleted_count += 1
            
            if deleted_count > 0:
                print(f"✅ Cleaned up {deleted_count} expired OTPs")
            
        except Exception as e:
            print(f"❌ Failed to cleanup expired OTPs: {str(e)}")


# Global password reset service instance
password_reset_service = PasswordResetService()
