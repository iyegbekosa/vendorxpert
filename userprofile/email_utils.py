"""
Email utilities for VendorXpert application
"""

from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

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
        subject = "🎉 Welcome to VendorXpert - Your Journey Starts Here!"

        # Create context for email template
        context = {
            "user_name": user.first_name or user.user_name,
            "full_name": f"{user.first_name} {user.last_name}".strip()
            or user.user_name,
            "email": user.email,
            "site_name": "VendorXpert",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # HTML email content
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome to VendorXpert</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f8f9fa;
                }}
                .container {{
                    background: white;
                    border-radius: 10px;
                    padding: 30px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 10px;
                }}
                .welcome-title {{
                    color: #27ae60;
                    font-size: 24px;
                    margin-bottom: 20px;
                }}
                .content {{
                    margin-bottom: 30px;
                }}
                .features {{
                    background: #ecf0f1;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .feature-item {{
                    margin: 10px 0;
                    padding-left: 25px;
                    position: relative;
                }}
                .feature-item::before {{
                    content: "✓";
                    position: absolute;
                    left: 0;
                    color: #27ae60;
                    font-weight: bold;
                }}
                .cta-button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 25px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    color: #666;
                    font-size: 14px;
                }}
                .social-links {{
                    margin: 15px 0;
                }}
                .social-links a {{
                    display: inline-block;
                    margin: 0 10px;
                    color: #667eea;
                    text-decoration: none;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🛍️ VendorXpert</div>
                    <h1 class="welcome-title">Welcome to VendorXpert, {context['user_name']}! 🎉</h1>
                </div>
                
                <div class="content">
                    <p>Hi <strong>{context['full_name']}</strong>,</p>
                    
                    <p>We're absolutely thrilled to welcome you to the <strong>VendorXpert</strong> community! 🚀</p>
                    
                    <p>You've just joined Nigeria's most innovative marketplace that connects students and vendors seamlessly. Whether you're here to discover amazing products or showcase your own business, you're in the right place!</p>
                    
                    <div class="features">
                        <h3>🌟 What you can do with VendorXpert:</h3>
                        <div class="feature-item">Browse products from verified local vendors</div>
                        <div class="feature-item">Discover student-friendly deals and discounts</div>
                        <div class="feature-item">Shop conveniently within your campus</div>
                        <div class="feature-item">Rate and review your favorite vendors</div>
                        <div class="feature-item">Join our growing community of smart shoppers</div>
                    </div>
                    
                    <p><strong>Ready to explore?</strong> Start browsing our marketplace and discover what makes VendorXpert special!</p>
                    
                    <div style="text-align: center;">
                        <a href="#" class="cta-button">🛍️ Start Shopping Now</a>
                    </div>
                    
                    <p><strong>💡 Pro Tip:</strong> Complete your profile to get personalized recommendations and exclusive offers!</p>
                </div>
                
                <div class="content">
                    <h3>🤝 Need Help Getting Started?</h3>
                    <p>Our friendly support team is here to help you make the most of VendorXpert:</p>
                    <ul>
                        <li>📧 Email us at <a href="mailto:{context['support_email']}">{context['support_email']}</a></li>
                        <li>💬 Check out our FAQ section</li>
                        <li>📱 Follow us on social media for tips and updates</li>
                    </ul>
                </div>
                
                <div class="content">
                    <p><strong>Interested in becoming a vendor?</strong> VendorXpert offers amazing opportunities for student entrepreneurs and local businesses to reach their target audience. <a href="#" style="color: #667eea;">Learn more about our vendor program</a>.</p>
                </div>
                
                <div class="footer">
                    <p>Welcome aboard! We can't wait to see what you discover.</p>
                    <p><strong>The VendorXpert Team</strong> 💜</p>
                    
                    <div class="social-links">
                        <a href="#">📱 Instagram</a>
                        <a href="#">🐦 Twitter</a>
                        <a href="#">📘 Facebook</a>
                    </div>
                    
                    <p style="margin-top: 20px; font-size: 12px;">
                        You received this email because you signed up for VendorXpert.<br>
                        If you have any questions, contact us at {context['support_email']}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        text_content = f"""
        Welcome to VendorXpert, {context['user_name']}!
        
        Hi {context['full_name']},
        
        We're thrilled to welcome you to the VendorXpert community!
        
        You've just joined Nigeria's most innovative marketplace that connects students and vendors seamlessly.
        
        What you can do with VendorXpert:
        ✓ Browse products from verified local vendors
        ✓ Discover student-friendly deals and discounts  
        ✓ Shop conveniently within your campus
        ✓ Rate and review your favorite vendors
        ✓ Join our growing community of smart shoppers
        
        Ready to explore? Start browsing our marketplace today!
        
        Pro Tip: Complete your profile to get personalized recommendations and exclusive offers!
        
        Need Help?
        - Email us at {context['support_email']}
        - Check out our FAQ section
        - Follow us on social media
        
        Interested in becoming a vendor? Learn more about our vendor program.
        
        Welcome aboard! We can't wait to see what you discover.
        
        The VendorXpert Team
        
        ---
        You received this email because you signed up for VendorXpert.
        If you have any questions, contact us at {context['support_email']}
        """

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


def send_vendor_welcome_email(vendor_profile):
    """
    Send a welcome email to newly registered vendors

    Args:
        vendor_profile: VendorProfile instance of the newly registered vendor

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        user = vendor_profile.user
        subject = "🎊 Welcome to VendorXpert - Your Store is Ready!"

        context = {
            "user_name": user.first_name or user.user_name,
            "full_name": f"{user.first_name} {user.last_name}".strip()
            or user.user_name,
            "store_name": vendor_profile.store_name,
            "email": user.email,
            "site_name": "VendorXpert",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # HTML email content for vendors
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome Vendor - VendorXpert</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f8f9fa;
                }}
                .container {{
                    background: white;
                    border-radius: 10px;
                    padding: 30px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 10px;
                }}
                .welcome-title {{
                    color: #e74c3c;
                    font-size: 24px;
                    margin-bottom: 20px;
                }}
                .store-highlight {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 10px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .features {{
                    background: #ecf0f1;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .feature-item {{
                    margin: 10px 0;
                    padding-left: 25px;
                    position: relative;
                }}
                .feature-item::before {{
                    content: "🚀";
                    position: absolute;
                    left: 0;
                }}
                .cta-button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 25px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    color: #666;
                    font-size: 14px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🏪 VendorXpert</div>
                    <h1 class="welcome-title">Your Store is Live! 🎊</h1>
                </div>
                
                <div class="store-highlight">
                    <h2>🌟 {context['store_name']}</h2>
                    <p>Your vendor journey starts now, {context['user_name']}!</p>
                </div>
                
                <div class="content">
                    <p>Hi <strong>{context['full_name']}</strong>,</p>
                    
                    <p>Congratulations! 🎉 You've successfully joined VendorXpert as a vendor. Your store "<strong>{context['store_name']}</strong>" is now ready to reach thousands of potential customers!</p>
                    
                    <div class="features">
                        <h3>🛍️ What you can do now:</h3>
                        <div class="feature-item">Add and manage your products</div>
                        <div class="feature-item">Set competitive prices and descriptions</div>
                        <div class="feature-item">Track your orders and sales</div>
                        <div class="feature-item">Communicate directly with customers</div>
                        <div class="feature-item">Access detailed analytics and insights</div>
                        <div class="feature-item">Manage your subscription and payments</div>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="#" class="cta-button">🏪 Go to Vendor Dashboard</a>
                    </div>
                    
                    <h3>📈 Tips for Success:</h3>
                    <ul>
                        <li><strong>High-quality photos:</strong> Upload clear, attractive product images</li>
                        <li><strong>Detailed descriptions:</strong> Help customers understand what you're offering</li>
                        <li><strong>Competitive pricing:</strong> Research market prices for similar products</li>
                        <li><strong>Quick responses:</strong> Reply to customer inquiries promptly</li>
                        <li><strong>Reliable fulfillment:</strong> Deliver orders on time and in good condition</li>
                    </ul>
                    
                    <p><strong>🎯 Ready to make your first sale?</strong> Start by adding your first product to your store!</p>
                </div>
                
                <div class="content">
                    <h3>🤝 Vendor Support</h3>
                    <p>Our vendor success team is here to help you succeed:</p>
                    <ul>
                        <li>📧 Email support: <a href="mailto:{context['support_email']}">{context['support_email']}</a></li>
                        <li>📚 Check out our vendor resources and guides</li>
                        <li>💬 Join our vendor community forum</li>
                        <li>📊 Access training materials and best practices</li>
                    </ul>
                </div>
                
                <div class="footer">
                    <p>We're excited to see your business grow with VendorXpert!</p>
                    <p><strong>The VendorXpert Team</strong> 💼</p>
                    
                    <p style="margin-top: 20px; font-size: 12px;">
                        You received this email because you registered as a vendor on VendorXpert.<br>
                        Questions? Contact us at {context['support_email']}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        text_content = f"""
        Your Store is Live on VendorXpert!
        
        Hi {context['full_name']},
        
        Congratulations! You've successfully joined VendorXpert as a vendor.
        Your store "{context['store_name']}" is now ready to reach thousands of potential customers!
        
        What you can do now:
        🚀 Add and manage your products
        🚀 Set competitive prices and descriptions
        🚀 Track your orders and sales
        🚀 Communicate directly with customers
        🚀 Access detailed analytics and insights
        🚀 Manage your subscription and payments
        
        Tips for Success:
        - High-quality photos: Upload clear, attractive product images
        - Detailed descriptions: Help customers understand what you're offering
        - Competitive pricing: Research market prices for similar products
        - Quick responses: Reply to customer inquiries promptly
        - Reliable fulfillment: Deliver orders on time and in good condition
        
        Ready to make your first sale? Start by adding your first product to your store!
        
        Vendor Support:
        - Email support: {context['support_email']}
        - Check out our vendor resources and guides
        - Join our vendor community forum
        - Access training materials and best practices
        
        We're excited to see your business grow with VendorXpert!
        
        The VendorXpert Team
        
        ---
        You received this email because you registered as a vendor on VendorXpert.
        Questions? Contact us at {context['support_email']}
        """

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

        subject = f"🧾 Your VendorXpert Receipt - Order #{order.ref}"

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
            "site_name": "VendorXpert",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }

        # HTML email content
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Order Receipt - VendorXpert</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 650px;
                    margin: 0 auto;
                    padding: 20px;
                    background-color: #f8f9fa;
                }}
                .container {{
                    background: white;
                    border-radius: 10px;
                    padding: 30px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                    padding-bottom: 20px;
                    border-bottom: 2px solid #667eea;
                }}
                .logo {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-bottom: 10px;
                }}
                .receipt-title {{
                    color: #27ae60;
                    font-size: 24px;
                    margin-bottom: 10px;
                }}
                .order-info {{
                    background: #ecf0f1;
                    padding: 20px;
                    border-radius: 8px;
                    margin: 20px 0;
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 15px;
                }}
                .info-item {{
                    margin: 5px 0;
                }}
                .info-label {{
                    font-weight: bold;
                    color: #2c3e50;
                }}
                .items-table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    background: white;
                }}
                .items-table th {{
                    background: #667eea;
                    color: white;
                    padding: 12px 8px;
                    text-align: left;
                    font-weight: bold;
                }}
                .items-table td {{
                    padding: 12px 8px;
                    border-bottom: 1px solid #ddd;
                }}
                .items-table tr:hover {{
                    background-color: #f8f9fa;
                }}
                .vendor-name {{
                    font-size: 12px;
                    color: #666;
                    font-style: italic;
                }}
                .total-section {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 20px;
                    border-radius: 8px;
                    text-align: center;
                    margin: 20px 0;
                }}
                .total-amount {{
                    font-size: 28px;
                    font-weight: bold;
                    margin: 10px 0;
                }}
                .pickup-info {{
                    background: #fff3cd;
                    border: 1px solid #ffeaa7;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .pickup-info h3 {{
                    margin-top: 0;
                    color: #856404;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    color: #666;
                    font-size: 14px;
                }}
                .thank-you {{
                    background: #d4edda;
                    border: 1px solid #c3e6cb;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                    text-align: center;
                }}
                @media (max-width: 600px) {{
                    .order-info {{
                        grid-template-columns: 1fr;
                    }}
                    .items-table {{
                        font-size: 14px;
                    }}
                    .items-table th,
                    .items-table td {{
                        padding: 8px 4px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <div class="logo">🛍️ VendorXpert</div>
                    <h1 class="receipt-title">Payment Successful! 🎉</h1>
                    <p>Thank you for your purchase, <strong>{context['user_name']}</strong>!</p>
                </div>
                
                <div class="thank-you">
                    <h3>🎊 Order Confirmed!</h3>
                    <p>Your payment has been processed successfully and your order is being prepared.</p>
                </div>
                
                <div class="order-info">
                    <div class="info-item">
                        <span class="info-label">Order Number:</span><br>
                        <strong>#{context['order_ref']}</strong>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Order Date:</span><br>
                        {context['order_date']}
                    </div>
                    <div class="info-item">
                        <span class="info-label">Customer:</span><br>
                        {context['customer_name']}
                    </div>
                    <div class="info-item">
                        <span class="info-label">Phone:</span><br>
                        {context['customer_phone']}
                    </div>
                </div>
                
                <h3>📦 Order Details</h3>
                <table class="items-table">
                    <thead>
                        <tr>
                            <th>Product</th>
                            <th>Qty</th>
                            <th>Price</th>
                            <th>Total</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        # Add items to the table
        for item in context["items"]:
            html_content += f"""
                        <tr>
                            <td>
                                <strong>{item['product_name']}</strong><br>
                                <span class="vendor-name">by {item['vendor_name']}</span>
                            </td>
                            <td>{item['quantity']}</td>
                            <td>₦{item['unit_price']:,.2f}</td>
                            <td>₦{item['total_price']:,.2f}</td>
                        </tr>
            """

        html_content += f"""
                    </tbody>
                </table>
                
                <div class="total-section">
                    <h3>💰 Total Amount Paid</h3>
                    <div class="total-amount">₦{context['total_amount']:,.2f}</div>
                    <p>Payment processed successfully via Paystack</p>
                </div>
                
                <div class="pickup-info">
                    <h3>📍 Pickup Information</h3>
                    <p><strong>Location:</strong> {context['pickup_location']}</p>
                    <p>Please bring this receipt and a valid ID when picking up your order.</p>
                    <p><strong>Contact:</strong> {context['customer_phone']}</p>
                </div>
                
                <div class="content">
                    <h3>👥 Vendors in this Order</h3>
                    <p>Your order includes items from: <strong>{', '.join(context['vendors_list'])}</strong></p>
                    <p>Each vendor will prepare their items and coordinate pickup at your selected location.</p>
                </div>
                
                <div class="content">
                    <h3>🤝 Need Help?</h3>
                    <p>If you have any questions about your order or need assistance:</p>
                    <ul>
                        <li>📧 Email us at <a href="mailto:{context['support_email']}">{context['support_email']}</a></li>
                        <li>📞 Contact the vendor directly for order-specific questions</li>
                        <li>💬 Check your order status in the VendorXpert app</li>
                    </ul>
                </div>
                
                <div class="content">
                    <h3>⭐ Enjoying VendorXpert?</h3>
                    <p>Don't forget to rate and review your purchases once you receive them. Your feedback helps other students and supports our vendors!</p>
                </div>
                
                <div class="footer">
                    <p>Thank you for choosing VendorXpert!</p>
                    <p><strong>Happy Shopping!</strong> 🛍️</p>
                    
                    <p style="margin-top: 20px; font-size: 12px;">
                        This is an automated receipt for order #{context['order_ref']}.<br>
                        Questions? Contact us at {context['support_email']}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        # Plain text fallback
        text_content = f"""
        VendorXpert - Payment Receipt
        
        Thank you for your purchase, {context['user_name']}!
        
        ORDER DETAILS:
        Order Number: #{context['order_ref']}
        Order Date: {context['order_date']}
        Customer: {context['customer_name']}
        Phone: {context['customer_phone']}
        
        ITEMS PURCHASED:
        """

        for item in context["items"]:
            text_content += f"""
        - {item['product_name']} (by {item['vendor_name']})
          Quantity: {item['quantity']} × ₦{item['unit_price']:,.2f} = ₦{item['total_price']:,.2f}
        """

        text_content += f"""
        
        TOTAL PAID: ₦{context['total_amount']:,.2f}
        
        PICKUP INFORMATION:
        Location: {context['pickup_location']}
        Please bring this receipt and a valid ID when picking up your order.
        Contact: {context['customer_phone']}
        
        Vendors in this order: {', '.join(context['vendors_list'])}
        
        Need Help?
        - Email: {context['support_email']}
        - Contact vendor directly for order-specific questions
        - Check order status in VendorXpert app
        
        Thank you for choosing VendorXpert!
        
        ---
        This is an automated receipt for order #{context['order_ref']}.
        Questions? Contact us at {context['support_email']}
        """

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
