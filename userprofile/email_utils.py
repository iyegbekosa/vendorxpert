"""
Email utilities for VendorXprt application
"""

from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging
import random
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def send_welcome_email(user):
    """
    Send a welcome email to newly registered users

    Args:
        user: UserProfile instance of the newly registered user

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        subject = "🎉 Welcome to VendorXprt - Your Journey Starts Here!"

        # Create context for email template
        context = {
            "user_name": user.first_name or user.user_name,
            "full_name": f"{user.first_name} {user.last_name}".strip()
            or user.user_name,
            "email": user.email,
            "site_name": "VendorXprt",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # Render HTML and text templates
        html_content = render_to_string("emails/welcome_user.html", context)
        text_content = render_to_string("emails/welcome_user.txt", context)

        # Create and send email
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_content, "text/html")

        # Send the email
        result = email.send()

        if result:
            logger.info(f"Welcome email sent successfully to {user.email}")
            return True
        else:
            logger.error(f"Failed to send welcome email to {user.email}")
            return False

    except Exception as e:
        logger.error(f"Error sending welcome email to {user.email}: {str(e)}")
        return False


def send_verification_email(email, code, expires_at=None):
    """Send a 6-digit verification code to `email`.

    Returns True on success, False otherwise.
    """
    try:
        subject = "Your VendorXprt verification code"
        expires_at = expires_at or (timezone.now() + timedelta(minutes=15))

        context = {
            "code": code,
            "email": email,
            "site_name": "VendorXprt",
            "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        text_content = render_to_string("emails/verification.txt", context)
        html_content = render_to_string("emails/verification.html", context)

        email_msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        email_msg.attach_alternative(html_content, "text/html")

        result = email_msg.send()
        if result:
            logger.info(f"Verification email sent to {email}")
            return True
        else:
            logger.error(f"Failed to send verification email to {email}")
            return False
    except Exception as e:
        logger.error(f"Error sending verification email to {email}: {str(e)}")
        return False


def send_password_reset_email(email, code, expires_at=None):
    """Send a 6-digit password reset code to `email`.

    Returns True on success, False otherwise.
    """
    try:
        subject = "Reset your VendorXprt password"
        expires_at = expires_at or (timezone.now() + timedelta(minutes=15))

        context = {
            "code": code,
            "email": email,
            "site_name": "VendorXprt",
            "expires_at": expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        text_content = render_to_string("emails/password_reset.txt", context)
        html_content = render_to_string("emails/password_reset.html", context)

        email_msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        email_msg.attach_alternative(html_content, "text/html")

        result = email_msg.send()
        if result:
            logger.info(f"Password reset email sent to {email}")
            return True
        else:
            logger.error(f"Failed to send password reset email to {email}")
            return False
    except Exception as e:
        logger.error(f"Error sending password reset email to {email}: {str(e)}")
        return False


def send_vendor_welcome_email(vendor_profile_or_user):
    """
    Send a welcome email to newly registered vendors

    Args:
        vendor_profile_or_user: VendorProfile instance or UserProfile instance of the vendor

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Handle both VendorProfile and UserProfile objects
        if hasattr(vendor_profile_or_user, "user"):
            # It's a VendorProfile
            vendor_profile = vendor_profile_or_user
            user = vendor_profile.user
        else:
            # It's a UserProfile, get the VendorProfile
            user = vendor_profile_or_user
            vendor_profile = user.vendor_profile
        subject = "🎊 Welcome to VendorXprt - Your Store is Ready!"

        context = {
            "user_name": user.first_name or user.user_name,
            "full_name": f"{user.first_name} {user.last_name}".strip()
            or user.user_name,
            "store_name": vendor_profile.store_name,
            "email": user.email,
            "site_name": "VendorXprt",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # Render HTML and text templates
        html_content = render_to_string("emails/welcome_vendor.html", context)
        text_content = render_to_string("emails/welcome_vendor.txt", context)

        # Create and send email
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_content, "text/html")

        # Send the email
        result = email.send()

        if result:
            logger.info(f"Vendor welcome email sent successfully to {user.email}")
            return True
        else:
            logger.error(f"Failed to send vendor welcome email to {user.email}")
            return False

    except Exception as e:
        logger.error(f"Error sending vendor welcome email to {user.email}: {str(e)}")
        return False


def send_receipt_email(order):
    """
    Send a receipt email to customers after successful payment

    Args:
        order: Order instance of the completed purchase

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        user = order.created_by
        if not user or not user.email:
            logger.error(f"No user email found for order {order.ref}")
            return False

        subject = f"🧾 Your VendorXprt Receipt - Order #{order.ref}"

        # Calculate order totals and get items
        from store.models import OrderItem

        order_items = OrderItem.objects.filter(order=order).select_related(
            "product", "product__vendor"
        )

        total_amount = order.total_cost or 0
        items_data = []
        vendors_involved = set()

        for item in order_items:
            vendors_involved.add(item.product.vendor.store_name)
            items_data.append(
                {
                    "product_name": item.product.title,
                    "vendor_name": item.product.vendor.store_name,
                    "quantity": item.quantity,
                    "unit_price": item.price / 100,  # Convert from kobo to naira
                    "total_price": (item.price * item.quantity) / 100,
                    "product_image": (
                        item.product.get_thumbnail()
                        if hasattr(item.product, "get_thumbnail")
                        else None
                    ),
                }
            )

        # Create context for email template
        context = {
            "user_name": user.first_name or user.user_name,
            "full_name": f"{user.first_name} {user.last_name}".strip()
            or user.user_name,
            "email": user.email,
            "order_ref": order.ref,
            "order_date": order.created_at.strftime("%B %d, %Y at %I:%M %p"),
            "pickup_location": dict(order.PICKUP_CHOICES).get(
                order.pickup_location, order.pickup_location
            ),
            "total_amount": total_amount / 100,  # Convert from kobo to naira
            "items": items_data,
            "vendors_list": list(vendors_involved),
            "customer_phone": order.phone,
            "customer_name": f"{order.first_name} {order.last_name}",
            "site_name": "VendorXprt",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # Render HTML and text templates
        html_content = render_to_string("emails/receipt.html", context)
        text_content = render_to_string("emails/receipt.txt", context)

        # Create and send email
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_content, "text/html")

        # Send the email
        result = email.send()

        if result:
            logger.info(
                f"Receipt email sent successfully to {user.email} for order {order.ref}"
            )
            return True
        else:
            logger.error(
                f"Failed to send receipt email to {user.email} for order {order.ref}"
            )
            return False

    except Exception as e:
        logger.error(f"Error sending receipt email for order {order.ref}: {str(e)}")
        return False


def send_vendor_order_notification(order):
    """
    Send order notification emails to vendors when their products are ordered

    Args:
        order: Order instance of the completed purchase

    Returns:
        bool: True if all vendor emails sent successfully, False otherwise
    """
    try:
        from store.models import OrderItem
        from collections import defaultdict

        # Group order items by vendor
        vendor_orders = defaultdict(list)
        order_items = OrderItem.objects.filter(order=order).select_related(
            "product", "product__vendor", "product__vendor__user"
        )

        for item in order_items:
            vendor = item.product.vendor
            vendor_orders[vendor].append(item)

        all_emails_sent = True

        # Send email to each vendor
        for vendor, items in vendor_orders.items():
            try:
                if not vendor.user or not vendor.user.email:
                    logger.error(f"No email found for vendor {vendor.store_name}")
                    continue

                # Calculate vendor's total earnings from this order
                vendor_total = (
                    sum(item.price * item.quantity for item in items) / 100
                )  # Convert from kobo to naira

                # Prepare vendor items data
                vendor_items_data = []
                for item in items:
                    vendor_items_data.append(
                        {
                            "product_name": item.product.title,
                            "quantity": item.quantity,
                            "unit_price": item.price
                            / 100,  # Convert from kobo to naira
                            "total_price": (item.price * item.quantity) / 100,
                        }
                    )

                # Create context for email template
                context = {
                    "vendor_name": vendor.user.first_name or vendor.user.user_name,
                    "store_name": vendor.store_name,
                    "order_ref": order.ref,
                    "order_date": order.created_at.strftime("%B %d, %Y at %I:%M %p"),
                    "customer_name": f"{order.first_name} {order.last_name}",
                    "customer_phone": order.phone,
                    "pickup_location": dict(order.PICKUP_CHOICES).get(
                        order.pickup_location, order.pickup_location
                    ),
                    "vendor_items": vendor_items_data,
                    "vendor_total": vendor_total,
                    "support_email": settings.DEFAULT_FROM_EMAIL,
                }

                subject = f"🎉 New Order #{order.ref} - {vendor.store_name}"

                # Render HTML and text templates
                html_content = render_to_string(
                    "emails/vendor_order_notification.html", context
                )
                text_content = render_to_string(
                    "emails/vendor_order_notification.txt", context
                )

                # Create and send email
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=text_content,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[vendor.user.email],
                )
                email.attach_alternative(html_content, "text/html")

                # Send the email
                result = email.send()

                if result:
                    logger.info(
                        f"Vendor notification email sent to {vendor.user.email} for order {order.ref}"
                    )
                else:
                    logger.error(
                        f"Failed to send vendor notification to {vendor.user.email} for order {order.ref}"
                    )
                    all_emails_sent = False

            except Exception as e:
                logger.error(
                    f"Error sending vendor notification to {vendor.store_name}: {str(e)}"
                )
                all_emails_sent = False

        return all_emails_sent

    except Exception as e:
        logger.error(
            f"Error sending vendor notifications for order {order.ref}: {str(e)}"
        )
        return False
