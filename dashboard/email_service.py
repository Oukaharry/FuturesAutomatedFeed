"""
Email Service Module for Trading Dashboard
Sends email notifications for password changes, account creation, etc.
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# Email Configuration - Set these environment variables or update directly
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')  # Your email address
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')  # App password for Gmail
FROM_EMAIL = os.getenv('FROM_EMAIL', SMTP_USERNAME)
FROM_NAME = os.getenv('FROM_NAME', 'Trading Dashboard')

# Enable/disable email sending (set to False during development)
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'


def send_email(to_email: str, subject: str, html_body: str, text_body: str = None) -> bool:
    """
    Send an email using SMTP.
    Returns True if successful, False otherwise.
    """
    if not EMAIL_ENABLED:
        print(f"[EMAIL DISABLED] Would send to {to_email}: {subject}")
        return True
    
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("[EMAIL ERROR] SMTP credentials not configured")
        return False
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg['To'] = to_email
        
        # Add text version
        if text_body:
            msg.attach(MIMEText(text_body, 'plain'))
        
        # Add HTML version
        msg.attach(MIMEText(html_body, 'html'))
        
        # Connect and send
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        
        print(f"[EMAIL SENT] To: {to_email}, Subject: {subject}")
        return True
        
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send to {to_email}: {str(e)}")
        return False


def send_password_changed_notification(to_email: str, username: str, changed_by: str = 'self') -> bool:
    """Send notification when password is changed."""
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    
    if changed_by == 'self':
        subject = "Password Changed Successfully - Trading Dashboard"
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
                .success {{ color: #16a34a; font-size: 48px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="success">✓</div>
                    <h1>Password Changed</h1>
                </div>
                <div class="content">
                    <p>Hi <strong>{username}</strong>,</p>
                    <p>Your password was successfully changed on <strong>{timestamp}</strong>.</p>
                    <p>If you did not make this change, please contact your administrator immediately and reset your password.</p>
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #666; font-size: 14px;">
                        <strong>Security Tip:</strong> Never share your password with anyone. 
                        Our team will never ask for your password.
                    </p>
                </div>
                <div class="footer">
                    <p>Trading Dashboard Security Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    else:
        subject = "Your Password Has Been Reset - Trading Dashboard"
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
                .warning {{ color: #f59e0b; font-size: 48px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="warning">🔑</div>
                    <h1>Password Reset</h1>
                </div>
                <div class="content">
                    <p>Hi <strong>{username}</strong>,</p>
                    <p>Your password was reset by an administrator on <strong>{timestamp}</strong>.</p>
                    <p>You will be required to change your password when you next log in.</p>
                    <p>If you did not request this change, please contact your administrator.</p>
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #666; font-size: 14px;">
                        <strong>Next Steps:</strong> Log in with your new temporary password and create a new secure password.
                    </p>
                </div>
                <div class="footer">
                    <p>Trading Dashboard Security Team</p>
                </div>
            </div>
        </body>
        </html>
        """
    
    text_body = f"Hi {username}, your password was changed on {timestamp}. If you did not make this change, contact your administrator."
    
    return send_email(to_email, subject, html_body, text_body)


def send_account_created_notification(to_email: str, username: str, temp_password: str, user_type: str) -> bool:
    """Send notification when a new account is created."""
    subject = "Welcome to Trading Dashboard - Your Account is Ready"
    
    role_display = {
        'admin': 'Administrator',
        'trader': 'Trader',
        'client': 'Client'
    }.get(user_type, user_type.title())
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
            .credentials {{ background: white; padding: 20px; border-radius: 8px; border: 2px solid #667eea; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎉 Welcome!</h1>
                <p>Your Trading Dashboard account is ready</p>
            </div>
            <div class="content">
                <p>Hi <strong>{username}</strong>,</p>
                <p>Your {role_display} account has been created. Here are your login credentials:</p>
                
                <div class="credentials">
                    <p><strong>Username/Email:</strong> {username}</p>
                    <p><strong>Temporary Password:</strong> {temp_password}</p>
                    <p><strong>Role:</strong> {role_display}</p>
                </div>
                
                <p style="color: #dc2626;"><strong>⚠️ Important:</strong> You will be required to change your password when you first log in.</p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                <p style="color: #666; font-size: 14px;">
                    <strong>Security Tips:</strong>
                    <ul>
                        <li>Never share your password</li>
                        <li>Use a strong, unique password</li>
                        <li>Log out when using shared devices</li>
                    </ul>
                </p>
            </div>
            <div class="footer">
                <p>Trading Dashboard Security Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_body = f"Welcome {username}! Your {role_display} account is ready. Username: {username}, Temp Password: {temp_password}. Please change your password after logging in."
    
    return send_email(to_email, subject, html_body, text_body)


def send_password_reset_with_temp(to_email: str, username: str, temp_password: str) -> bool:
    """Send email with temporary password after admin reset."""
    subject = "Your Password Has Been Reset - Trading Dashboard"
    timestamp = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 10px 10px; }}
            .credentials {{ background: white; padding: 20px; border-radius: 8px; border: 2px solid #f59e0b; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🔑 Password Reset</h1>
            </div>
            <div class="content">
                <p>Hi <strong>{username}</strong>,</p>
                <p>Your password was reset by an administrator on <strong>{timestamp}</strong>.</p>
                
                <div class="credentials">
                    <p><strong>Your Temporary Password:</strong></p>
                    <p style="font-size: 24px; font-family: monospace; color: #667eea;">{temp_password}</p>
                </div>
                
                <p style="color: #dc2626;"><strong>⚠️ Important:</strong> You must change this password when you next log in.</p>
                
                <p>If you did not request this reset, please contact your administrator immediately.</p>
            </div>
            <div class="footer">
                <p>Trading Dashboard Security Team</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    text_body = f"Hi {username}, your password was reset on {timestamp}. Temporary password: {temp_password}. Please change it when you log in."
    
    return send_email(to_email, subject, html_body, text_body)
