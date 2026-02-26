"""
ZeptoMail HTTP API Integration for VendorXprt
Replaces SMTP with ZeptoMail's REST API for better deliverability
"""

import requests
import logging
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import json

logger = logging.getLogger(__name__)


class ZeptoMailClient:
    """ZeptoMail HTTP API client for sending emails"""

    def __init__(self):
        self.api_key = getattr(settings, "ZEPTOMAIL_API_KEY", "")
        self.from_name = getattr(settings, "ZEPTOMAIL_FROM_NAME", "VendorXprt")
        self.from_email = getattr(
            settings, "ZEPTOMAIL_FROM_EMAIL", "noreply@vendorxprt.com"
        )
        self.base_url = "https://api.zeptomail.com/v1.1/email"

        if not self.api_key:
            raise ValueError("ZEPTOMAIL_API_KEY not configured in settings")

    def send_email(
        self,
        to_email,
        subject,
        text_content,
        html_content=None,
        from_email=None,
        from_name=None,
    ):
        """
        Send email via ZeptoMail HTTP API

        Args:
            to_email (str): Recipient email address
            subject (str): Email subject
            text_content (str): Plain text content
            html_content (str, optional): HTML content
            from_email (str, optional): Override sender email
            from_name (str, optional): Override sender name

        Returns:
            bool: True if successful, False otherwise
        """

        # Prepare sender information
        sender_email = from_email or self.from_email
        sender_name = from_name or self.from_name

        # Build email payload
        payload = {
            "from": {"address": sender_email, "name": sender_name},
            "to": [{"email_address": {"address": to_email, "name": ""}}],
            "subject": subject,
            "textbody": text_content,
        }

        # Add HTML content if provided
        if html_content:
            payload["htmlbody"] = html_content

        # Prepare headers
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Zoho-enczapikey {self.api_key}",
        }

        try:
            logger.info(f"Sending email via ZeptoMail to {to_email}")
            logger.debug(f"Subject: {subject}")

            # Send request to ZeptoMail API
            response = requests.post(
                self.base_url, data=json.dumps(payload), headers=headers, timeout=30
            )

            # Check response - ZeptoMail returns 200 or 201 for success
            if response.status_code in [200, 201]:
                result = response.json()
                logger.info(f"Email sent successfully to {to_email}: {result}")
                return True
            else:
                logger.error(
                    f"ZeptoMail API error {response.status_code}: {response.text}"
                )
                return False

        except requests.exceptions.Timeout:
            logger.error(f"Timeout sending email to {to_email}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error sending email to {to_email}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email to {to_email}: {str(e)}")
            return False

    def send_template_email(
        self, to_email, subject, template_name, context, from_email=None, from_name=None
    ):
        """
        Send email using Django templates

        Args:
            to_email (str): Recipient email address
            subject (str): Email subject
            template_name (str): Template name (without extension)
            context (dict): Template context
            from_email (str, optional): Override sender email
            from_name (str, optional): Override sender name

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Render templates
            html_content = render_to_string(f"emails/{template_name}.html", context)
            text_content = render_to_string(f"emails/{template_name}.txt", context)

            # Send email
            return self.send_email(
                to_email=to_email,
                subject=subject,
                text_content=text_content,
                html_content=html_content,
                from_email=from_email,
                from_name=from_name,
            )

        except Exception as e:
            logger.error(f"Error rendering template {template_name}: {str(e)}")
            return False


# Global ZeptoMail client instance
zeptomail_client = ZeptoMailClient()


def send_zeptomail(
    to_email, subject, template_name, context, from_email=None, from_name=None
):
    """
    Convenience function to send email via ZeptoMail

    Args:
        to_email (str): Recipient email address
        subject (str): Email subject
        template_name (str): Template name (without extension)
        context (dict): Template context
        from_email (str, optional): Override sender email
        from_name (str, optional): Override sender name

    Returns:
        bool: True if successful, False otherwise
    """
    return zeptomail_client.send_template_email(
        to_email=to_email,
        subject=subject,
        template_name=template_name,
        context=context,
        from_email=from_email,
        from_name=from_name,
    )
