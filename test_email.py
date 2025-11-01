#!/usr/bin/env python
"""
Test script to verify email configuration with Zoho mail
"""
import os
import sys
import django
from pathlib import Path

# Add the project directory to Python path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "vendorxpert.settings")
django.setup()

from django.core.mail import send_mail
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def test_email_configuration():
    """Test basic email configuration"""
    print("🔧 Testing Email Configuration...")
    print(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
    print(f"EMAIL_HOST: {settings.EMAIL_HOST}")
    print(f"EMAIL_PORT: {settings.EMAIL_PORT}")
    print(f"EMAIL_USE_SSL: {settings.EMAIL_USE_SSL}")
    print(f"EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
    print(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
    print(f"DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
    print("-" * 50)


def send_test_email():
    """Send a test email"""
    try:
        print("📧 Sending test email...")

        subject = "VendorXprt - Email Configuration Test"
        message = """
        Hello!
        
        This is a test email from your VendorXprt Django application.
        
        If you're receiving this email, your Zoho mail configuration is working perfectly! 🎉
        
        Email settings:
        - Host: smtppro.zoho.com
        - Port: 465 (SSL)
        - From: contact@vendorxprt.com
        
        Best regards,
        VendorXprt Team
        """

        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = ["egyadesm@gmail.com"]  # Send to specified email address

        # Send simple email
        result = send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )

        if result:
            print("✅ Test email sent successfully!")
            print(f"📨 Sent from: {from_email}")
            print(f"📬 Sent to: {recipient_list[0]}")
        else:
            print("❌ Failed to send test email")

        return result

    except Exception as e:
        print(f"❌ Error sending email: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return False


def send_html_test_email():
    """Send a test HTML email"""
    try:
        print("\n📧 Sending HTML test email...")

        subject = "VendorXprt - HTML Email Test"
        text_content = "This is a plain text email test from VendorXprt."
        html_content = """
        <html>
        <body>
            <h2 style="color: #2c3e50;">🎉 VendorXprt Email Test</h2>
            <p>Hello!</p>
            <p>This is an <strong>HTML test email</strong> from your VendorXprt Django application.</p>
            <div style="background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 15px 0;">
                <h3>Configuration Details:</h3>
                <ul>
                    <li><strong>Host:</strong> smtppro.zoho.com</li>
                    <li><strong>Port:</strong> 465 (SSL)</li>
                    <li><strong>From:</strong> contact@vendorxprt.com</li>
                </ul>
            </div>
            <p style="color: #27ae60;"><em>✅ Your email configuration is working perfectly!</em></p>
            <hr>
            <p><small>Best regards,<br>VendorXprt Team</small></p>
        </body>
        </html>
        """

        from_email = settings.DEFAULT_FROM_EMAIL
        to_email = "egyadesm@gmail.com"

        # Create email with both text and HTML
        email = EmailMultiAlternatives(
            subject=subject, body=text_content, from_email=from_email, to=[to_email]
        )
        email.attach_alternative(html_content, "text/html")

        result = email.send()

        if result:
            print("✅ HTML test email sent successfully!")
            print(f"📨 Sent from: {from_email}")
            print(f"📬 Sent to: {to_email}")
        else:
            print("❌ Failed to send HTML test email")

        return result

    except Exception as e:
        print(f"❌ Error sending HTML email: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return False


if __name__ == "__main__":
    print("🚀 VendorXprt Email Configuration Test")
    print("=" * 50)

    # Test configuration
    test_email_configuration()

    # Test simple email
    simple_result = send_test_email()

    # Test HTML email
    html_result = send_html_test_email()

    print("\n" + "=" * 50)
    print("📋 Test Results Summary:")
    print(f"✅ Simple Email: {'PASSED' if simple_result else 'FAILED'}")
    print(f"✅ HTML Email: {'PASSED' if html_result else 'FAILED'}")

    if simple_result and html_result:
        print(
            "\n🎉 All email tests passed! Your Zoho mail configuration is working perfectly."
        )
    else:
        print("\n❌ Some tests failed. Please check your email configuration.")
