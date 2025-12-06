"""
Email Service for User Notifications
===================================
Handles sending welcome emails, login notifications, and password reset emails using AWS SES.
"""

import boto3
import os
from botocore.exceptions import ClientError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
from src.core.config import settings


class EmailService:
    def __init__(self):
        # AWS SES Configuration
        self.aws_region = getattr(settings, 'aws_region', 'us-east-1')
        self.aws_access_key_id = getattr(settings, 'aws_access_key_id', None)
        self.aws_secret_access_key = getattr(settings, 'aws_secret_access_key', None)
        self.from_email = getattr(settings, 'from_email', None)
        self.from_name = getattr(settings, 'from_name', 'June Kids')
        self.enabled = getattr(settings, 'email_enabled', False)
        
        # Initialize SES client
        self.ses_client = None
        if self.enabled and self.aws_access_key_id and self.aws_secret_access_key:
            try:
                self.ses_client = boto3.client(
                    'ses',
                    region_name=self.aws_region,
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key
                )
                print(f"✅ AWS SES client initialized in region: {self.aws_region}")
            except Exception as e:
                print(f"❌ Failed to initialize AWS SES client: {str(e)}")
                self.ses_client = None

    def load_email_template(self, html_filename: str, text_filename: str):
        """Load HTML + TEXT email templates from same directory."""
        base_path = os.path.dirname(__file__)

        try:
            with open(os.path.join(base_path, html_filename), "r", encoding="utf-8") as f:
                html_content = f.read()

            with open(os.path.join(base_path, text_filename), "r", encoding="utf-8") as f:
                text_content = f.read()

            return html_content, text_content

        except Exception as e:
            print(f"Failed to load template files: {str(e)}")
            return None, None

    async def send_email(self, to_email: str, subject: str, html_content: str, text_content: str = None):
        """
        Send an email using AWS SES
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text email content (optional)
        """
        try:
            if not self.enabled or not self.ses_client:
                print("⚠️ Email service not configured - skipping email send")
                return False

            if not self.from_email:
                print("❌ From email address not configured")
                return False

            # Prepare the email body
            body = {}
            
            if text_content:
                body['Text'] = {
                    'Data': text_content,
                    'Charset': 'UTF-8'
                }
            
            if html_content:
                body['Html'] = {
                    'Data': html_content,
                    'Charset': 'UTF-8'
                }

            # Send email using SES
            response = self.ses_client.send_email(
                Source=f"{self.from_name} <{self.from_email}>",
                Destination={
                    'ToAddresses': [to_email]
                },
                Message={
                    'Subject': {
                        'Data': subject,
                        'Charset': 'UTF-8'
                    },
                    'Body': body
                }
            )

            print(f"✅ Email sent successfully to {to_email} (MessageId: {response['MessageId']})")
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            print(f"❌ AWS SES error sending to {to_email}: [{error_code}] {error_message}")
            return False
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {str(e)}")
            return False

    async def send_raw_email(self, to_email: str, subject: str, html_content: str, text_content: str = None):
        """
        Send a raw email using AWS SES (alternative method with more control)
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML email content
            text_content: Plain text email content (optional)
        """
        try:
            if not self.enabled or not self.ses_client:
                print("⚠️ Email service not configured - skipping email send")
                return False

            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to_email

            # Add text content
            if text_content:
                text_part = MIMEText(text_content, "plain", "utf-8")
                message.attach(text_part)

            # Add HTML content
            if html_content:
                html_part = MIMEText(html_content, "html", "utf-8")
                message.attach(html_part)

            # Send raw email
            response = self.ses_client.send_raw_email(
                Source=f"{self.from_name} <{self.from_email}>",
                Destinations=[to_email],
                RawMessage={
                    'Data': message.as_string()
                }
            )

            print(f"✅ Raw email sent successfully to {to_email} (MessageId: {response['MessageId']})")
            return True

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            print(f"❌ AWS SES error sending to {to_email}: [{error_code}] {error_message}")
            return False
        except Exception as e:
            print(f"❌ Failed to send raw email to {to_email}: {str(e)}")
            return False

    async def send_welcome_email(self, user_email: str, user_name: str = None):
        """
        Send welcome email to new users
        
        Args:
            user_email: User's email address
            user_name: User's display name (optional)
        """
        subject = "Welcome to June Kids! 🎉"

        html_content, text_content = self.load_email_template("welcome_email.html", "welcome_email.txt")

        if not html_content:
            return False
        
        display_name = user_name if user_name else user_email.split('@')[0]

        # Replace placeholders
        html_content = html_content.replace("{user mail id}", display_name)
        text_content = text_content.replace("{user mail id}", display_name)

        return await self.send_email(
            user_email, subject, html_content, text_content
        )
        


    async def send_login_notification(self, user_email: str, user_name: str = None, login_time: datetime = None, device_info: str = None):
        """
        Send login notification email
        
        Args:
            user_email: User's email address
            user_name: User's display name (optional)
            login_time: Login timestamp (optional)
            device_info: Device/browser information (optional)
        """
        subject = "New Login to Your June Kids Account"
        
        display_name = user_name if user_name else user_email.split('@')[0]
        login_datetime = login_time if login_time else datetime.utcnow()
        formatted_time = login_datetime.strftime("%B %d, %Y at %I:%M %p UTC")
        device_text = f" from {device_info}" if device_info else ""
        
        html_content, text_content = self.load_email_template(
            "login_notification.html", "login_notification.txt"
        )

        if not html_content:
            return False

        # Replace placeholders
        for key, value in {
            "{user mail id}": user_email,
            "{display_name}": display_name,
            "{login_time}": formatted_time,
            "{device_info}": device_text
        }.items():
            html_content = html_content.replace(key, value)
            text_content = text_content.replace(key, value)

        return await self.send_email(
            user_email, subject, html_content, text_content
        )
        

    async def send_password_reset_email(self, user_email: str, reset_token: str, user_name: str = None):
        """
        Send password reset email
        
        Args:
            user_email: User's email address
            reset_token: Password reset token
            user_name: User's display name (optional)
        """
        subject = "Reset Your June Kids Password"
        
        display_name = user_name if user_name else user_email.split('@')[0]
        
        # Use Expo default development URL for password reset
        reset_url = f"exp://localhost:19000/--/reset-password?token={reset_token}&email={user_email}"
        
        html_content, text_content = self.load_email_template(
            "password_reset.html", "password_reset.txt"
        )

        if not html_content:
            return False

        for key, value in {
            "{user mail id}": user_email,
            "{display_name}": display_name,
            "{reset_url}": reset_url
        }.items():
            html_content = html_content.replace(key, value)
            text_content = text_content.replace(key, value)

        return await self.send_email(
            user_email, subject, html_content, text_content
        )
    
    async def send_password_reset_otp_email(self, user_email: str, otp_code: str, user_name: Optional[str] = None, expiry_minutes: int = 10):
        """
        Send a password reset OTP email
        
        Args:
            user_email: User's email address
            otp_code: 6-digit OTP code
            user_name: User's display name (optional)
            expiry_minutes: OTP expiry time in minutes
        """
        if not self.enabled:
            print("⚠️ Email service is disabled - OTP email not sent")
            return
        
        display_name = user_name if user_name else "StoryTeller User"
        subject = "Your June Kids Password Reset Code"
        
        html_content, text_content = self.load_email_template(
            "password_reset_otp.html", "password_reset_otp.txt"
        )

        if not html_content:
            return False

        for key, value in {
            "{display_name}": display_name,
            "{otp_code}": otp_code,
            "{expiry_minutes}": str(expiry_minutes)
        }.items():
            html_content = html_content.replace(key, value)
            text_content = text_content.replace(key, value)

        return await self.send_email(
            user_email, subject, html_content, text_content
        )


# Global email service instance
email_service = EmailService()