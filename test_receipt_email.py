#!/usr/bin/env python
"""
Test receipt email functionality
"""
import os
import sys
import django
from pathlib import Path

# Add the project directory to Python path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vendorxpert.settings')
django.setup()

from store.models import Order, OrderItem, Product
from userprofile.models import UserProfile
from userprofile.email_utils import send_receipt_email

def test_receipt_email():
    """Test receipt email with a real or sample order"""
    
    print("🧪 Testing Receipt Email Functionality")
    print("=" * 50)
    
    try:
        # Try to find a paid order
        order = Order.objects.filter(is_paid=True).first()
        
        if order:
            print(f"📦 Found order: #{order.ref}")
            print(f"👤 Customer: {order.first_name} {order.last_name}")
            print(f"📧 Email: {order.created_by.email if order.created_by else 'No email'}")
            print(f"💰 Total: ₦{order.total_cost/100:,.2f}" if order.total_cost else "No total")
            print(f"📅 Date: {order.created_at}")
            
            # Get order items
            items = OrderItem.objects.filter(order=order)
            print(f"📋 Items: {items.count()}")
            
            for item in items:
                print(f"  - {item.product.title} (x{item.quantity}) - ₦{item.price/100:,.2f}")
            
            if order.created_by and order.created_by.email:
                print("\n📧 Sending receipt email...")
                result = send_receipt_email(order)
                
                if result:
                    print("✅ Receipt email sent successfully!")
                    print(f"📬 Sent to: {order.created_by.email}")
                else:
                    print("❌ Failed to send receipt email")
            else:
                print("❌ Order has no associated user email")
                
        else:
            print("❌ No paid orders found in database")
            print("💡 Create a test order or make a purchase to test receipt emails")
            
            # Let's try to create a sample order for testing
            print("\n🔧 Creating sample order for testing...")
            test_user = UserProfile.objects.first()
            if test_user:
                # Note: This is just for testing the email format
                # In reality, you shouldn't manually create orders
                print(f"👤 Using test user: {test_user.email}")
                print("📧 This will test the email template formatting...")
                
                # Create a minimal test order (don't save to DB)
                from datetime import datetime
                test_order = Order(
                    ref="TEST_" + str(int(datetime.now().timestamp())),
                    created_by=test_user,
                    first_name=test_user.first_name or "Test",
                    last_name=test_user.last_name or "User", 
                    phone="+2348123456789",
                    pickup_location="hall_1",
                    total_cost=500000,  # ₦5000 in kobo
                    is_paid=True,
                    created_at=datetime.now()
                )
                
                print("🧪 Testing email format (without real order items)...")
                result = send_receipt_email(test_order)
                
                if result:
                    print("✅ Test receipt email sent successfully!")
                else:
                    print("❌ Failed to send test receipt email")
            else:
                print("❌ No users found for testing")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")

if __name__ == "__main__":
    test_receipt_email()