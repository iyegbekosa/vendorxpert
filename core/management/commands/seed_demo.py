"""Populate a development database with realistic marketplace data.

    python manage.py seed_demo           # add demo data (idempotent: resets first)
    python manage.py seed_demo --clear   # only remove demo data
    python manage.py seed_demo --orders-for you@example.com
                                         # also give a real account orders to rate

Every demo account uses an ``@demo.vendorxprt.test`` email, so demo data can
be removed without touching real records. No Paystack or email calls are made.
"""

import random
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import quote_plus

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from store.models import CartItem, Category, Order, OrderItem, Payment, Product, Review
from store.services import calculate_service_fee
from userprofile.models import SubscriptionHistory, UserProfile, VendorPlan, VendorProfile

DEMO_DOMAIN = "demo.vendorxprt.test"
DEMO_PASSWORD = "Campus-Demo-2026"

CATEGORIES = [
    ("Food & Snacks", "food-snacks"),
    ("Gadgets", "gadgets"),
    ("Fashion", "fashion"),
    ("Beauty & Care", "beauty-care"),
    ("Books & Stationery", "books-stationery"),
    ("Services", "services"),
]

PLANS = [
    ("basic", 3000, 6, "Up to 6 listings\nOrder notifications"),
    ("premium", 5000, 12, "Up to 12 listings\nPriority support"),
    ("executive", 10000, 25, "Up to 25 listings\nPriority support\nFeatured placement eligibility"),
]

# (store, owner first name, description, whatsapp, status, category slug, products)
# products: (title, price, quantity, description)
VENDORS = [
    (
        "Mama Tee's Kitchen", "Temitope", "Home-cooked jollof, small chops and drinks. Order before 2pm for same-day pickup.",
        "08031110001", "active", "food-snacks",
        [
            ("Jollof Rice & Chicken", 2500, 20, "Smoky party jollof with grilled chicken and plantain."),
            ("Small Chops Pack", 1800, 15, "Puff-puff, samosa, spring rolls and gizdodo."),
            ("Zobo Drink (1L)", 700, 30, "Chilled zobo with ginger and pineapple."),
            ("Meat Pie (x2)", 1000, 2, "Fresh-baked, flaky pastry."),
            ("Fried Rice Combo", 2800, 0, "Back tomorrow."),
        ],
    ),
    (
        "GadgetHub Campus", "Ifeanyi", "Chargers, power banks and phone accessories. Everything tested before pickup.",
        "08031110002", "trial", "gadgets",
        [
            ("20,000mAh Power Bank", 14500, 8, "Fast charging, two USB ports and Type-C."),
            ("Type-C Fast Charger 25W", 6500, 12, "Original-grade adapter with cable."),
            ("Wireless Earbuds", 18000, 5, "Bluetooth 5.3, 20 hours with case."),
            ("Phone Ring Light", 4500, 3, "Clip-on light for video calls and content."),
            ("Laptop Cooling Pad", 9000, 0, "Restocking soon."),
        ],
    ),
    (
        "Thread & Style", "Chioma", "Thrift and new pieces for campus life. Sizes S–XL.",
        "08031110003", "active", "fashion",
        [
            ("Vintage Denim Jacket", 12000, 4, "Unisex, lightly worn, size M."),
            ("Plain Hoodie", 9500, 10, "Heavyweight cotton, black or grey."),
            ("Tote Bag", 3500, 25, "Canvas, fits a 15-inch laptop."),
            ("Bucket Hat", 4000, 6, "Reversible, one size."),
        ],
    ),
    (
        "Glow by Ada", "Adaeze", "Skincare and hair care for students. Gentle, budget-friendly picks.",
        "08031110004", "cancelled", "beauty-care",
        [
            ("Shea Butter Body Cream", 3000, 14, "Unscented, 250ml."),
            ("Braiding Hair (3 packs)", 4500, 9, "Soft, tangle-free."),
            ("Lip Gloss Set", 2500, 1, "Three shades."),
        ],
    ),
    (
        "PageTurners", "Kunle", "Used textbooks, past questions and stationery.",
        "08031110005", "trial", "books-stationery",
        [
            ("GST 101 Past Questions", 1500, 40, "Ten years of past questions with answers."),
            ("Scientific Calculator", 8500, 6, "Exam-approved model."),
            ("A4 Notebook Pack (5)", 2000, 20, "80 leaves each."),
            ("Organic Chemistry Textbook", 6000, 2, "Good condition, light highlighting."),
        ],
    ),
    (
        "FixIt Phones", "Seyi", "Screen replacements and phone repairs. Currently on a break.",
        "08031110006", "lapsed", "services",
        [
            ("Screen Replacement (Android)", 15000, 10, "Most models, same day."),
            ("Battery Replacement", 8000, 10, "Includes testing."),
        ],
    ),
]

BUYERS = [("Bisi", "Adeyemi", "hall_2"), ("Emeka", "Okafor", "hall_5")]

REVIEW_TEXTS = [
    (5, "Exactly as described and the vendor was on time."),
    (5, "Very fast pickup, will buy again!"),
    (4, "Good quality. Pickup took a little long."),
    (4, ""),
    (3, "Okay for the price."),
]


def demo_email(handle):
    return f"{handle}@{DEMO_DOMAIN}"


def placeholder_image(title, size="800x600"):
    return f"https://placehold.co/{size}/EF8650/FFFFFF/png?text={quote_plus(title)}"


class Command(BaseCommand):
    help = "Seed the database with demo vendors, products, buyers, orders and reviews."

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Only remove demo data.")
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG=False.")
        parser.add_argument(
            "--orders-for",
            metavar="EMAIL",
            help="Also create paid orders from demo vendors for this existing account.",
        )

    def handle(self, *args, clear=False, force=False, orders_for=None, **options):
        if not settings.DEBUG and not force:
            raise CommandError(
                "Refusing to seed demo data with DEBUG=False. Use --force only on a staging database."
            )

        with transaction.atomic():
            removed = self.clear_demo_data()
            if clear:
                self.stdout.write(self.style.SUCCESS(f"Removed {removed} demo accounts."))
                return
            self.seed()
            if orders_for:
                self.seed_orders_for(orders_for)

        self.stdout.write(self.style.SUCCESS("Demo data ready.\n"))
        self.stdout.write(f"Password for every demo account: {DEMO_PASSWORD}")
        self.stdout.write(f"Buyers:  {demo_email('bisi')}, {demo_email('emeka')}")
        self.stdout.write(f"Vendors: {demo_email('temitope')} (active), {demo_email('ifeanyi')} (trial),")
        self.stdout.write(f"         {demo_email('adaeze')} (cancelled, still selling), {demo_email('seyi')} (lapsed, hidden)")

    def clear_demo_data(self):
        demo_users = UserProfile.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        # Orders protect their products, so remove orders before vendors/products.
        Order.objects.filter(created_by__in=demo_users).delete()
        Order.objects.filter(items__product__vendor__user__in=demo_users).delete()
        count = demo_users.count()
        demo_users.delete()
        return count

    def seed(self):
        rng = random.Random(42)
        now = timezone.now()

        categories = {
            slug: Category.objects.get_or_create(slug=slug, defaults={"title": title})[0]
            for title, slug in CATEGORIES
        }
        plans = {}
        for name, price, max_products, features in PLANS:
            plan, _ = VendorPlan.objects.get_or_create(
                name=name,
                defaults={
                    "price": price,
                    "max_products": max_products,
                    "features": features,
                    "is_active": True,
                    "paystack_plan_code": "",
                },
            )
            plans[name] = plan

        products = []
        vendors = []
        for store_name, first_name, description, whatsapp, status, category_slug, items in VENDORS:
            user = UserProfile.objects.create_user(
                email=demo_email(first_name.lower()),
                user_name=f"{first_name.lower()}.demo",
                first_name=first_name,
                last_name="Demo",
                password=DEMO_PASSWORD,
                is_vendor=True,
            )
            vendor = VendorProfile.objects.create(
                user=user,
                store_name=store_name,
                store_description=description,
                whatsapp_number=f"+234{whatsapp[1:]}",
                instagram_handle=store_name.lower().replace(" ", "").replace("'", "")[:30],
                is_verified=True,
                subaccount_code=f"ACCT_demo{user.pk}",
                **self.subscription_fields(status, plans, now),
            )
            SubscriptionHistory.log_event(
                vendor=vendor, event_type="trial_started", new_plan=vendor.plan, notes="Demo data"
            )
            vendors.append(vendor)
            for index, (title, price, quantity, product_description) in enumerate(items):
                product = Product(
                    vendor=vendor,
                    category=categories[category_slug],
                    title=title,
                    description=product_description,
                    price=price,
                    quantity=quantity,
                    product_image=placeholder_image(title),
                    featured=index == 0 and status == "active",
                )
                # full_clean would try to validate the Cloudinary field.
                with patch.object(Product, "full_clean"):
                    product.save()
                Product.objects.filter(pk=product.pk).update(
                    created_at=now - timedelta(days=rng.randint(1, 40), hours=rng.randint(0, 23))
                )
                products.append(product)

        buyers = []
        for first_name, last_name, hall in BUYERS:
            buyers.append(
                UserProfile.objects.create_user(
                    email=demo_email(first_name.lower()),
                    user_name=f"{first_name.lower()}.demo",
                    first_name=first_name,
                    last_name=last_name,
                    password=DEMO_PASSWORD,
                    hostel=hall,
                )
            )

        # A vendor shops too: Temitope buys from GadgetHub.
        shoppers = buyers + [vendors[0].user]
        in_stock = [p for p in products if p.quantity > 0 and p.vendor.subscription_status != "lapsed"]
        for order_number in range(9):
            buyer = shoppers[order_number % len(shoppers)]
            choices = [p for p in in_stock if p.vendor.user_id != buyer.pk]
            lines = rng.sample(choices, k=rng.randint(1, 3))
            self.create_paid_order(buyer, lines, rng, now - timedelta(days=order_number * 2 + 1),
                                   collected=order_number >= 3)

        # Something waiting in a cart.
        CartItem.objects.create(user=buyers[0], product=in_stock[1], quantity=1)

        self.stdout.write(
            f"Created {len(vendors)} vendors, {len(products)} products, {len(buyers)} buyers, "
            f"{Order.objects.filter(created_by__in=shoppers).count()} orders."
        )

    def seed_orders_for(self, email):
        """Paid orders for a real account: two collected (ready to rate), one
        waiting for pickup. Demo orders are removed with --clear like the rest."""
        user = UserProfile.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No account with email {email}.")
        rng = random.Random(7)
        now = timezone.now()
        available = list(
            Product.objects.purchasable()
            .filter(vendor__user__email__endswith=f"@{DEMO_DOMAIN}")
            .exclude(vendor__user=user)
            .select_related("vendor")
        )
        if len(available) < 4:
            raise CommandError("Not enough demo products to create orders.")
        rng.shuffle(available)
        plan = [(available[0:2], True, 6), (available[2:3], True, 3), (available[3:5], False, 0)]
        for products, collected, days_ago in plan:
            self.create_paid_order(
                user, products, rng, now - timedelta(days=days_ago, hours=2), collected=collected, review=False
            )
        self.stdout.write(f"Created 3 paid orders for {user.email} (2 collected and unrated, 1 awaiting pickup).")

    def subscription_fields(self, status, plans, now):
        if status == "active":
            return {
                "plan": plans["premium"],
                "subscription_status": "active",
                "subscription_expiry": now + timedelta(days=21),
                "last_payment_date": now - timedelta(days=9),
            }
        if status == "cancelled":
            return {
                "plan": plans["basic"],
                "subscription_status": "cancelled",
                "subscription_expiry": now + timedelta(days=6),
            }
        if status == "lapsed":
            return {
                "plan": plans["basic"],
                "subscription_status": "trial",
                "trial_start": now - timedelta(days=45),
                "trial_end": now - timedelta(days=15),
            }
        return {
            "plan": plans["basic"],
            "subscription_status": "trial",
            "trial_start": now - timedelta(days=24),
            "trial_end": now + timedelta(days=6),
        }

    def create_paid_order(self, buyer, products, rng, paid_at, collected, review=True):
        quantities = {product.pk: rng.randint(1, min(2, product.quantity)) for product in products}
        subtotal = sum(product.price * quantities[product.pk] for product in products)
        fee = calculate_service_fee(subtotal)
        order = Order.objects.create(
            created_by=buyer,
            first_name=buyer.first_name,
            last_name=buyer.last_name or "Demo",
            phone=f"+23480{rng.randint(10_000_000, 99_999_999)}",
            pickup_location=buyer.hostel or "hall_2",
            total_cost=subtotal,
            service_fee=fee,
            is_paid=True,
            paid_at=paid_at,
            ref=f"demo{rng.getrandbits(48):012x}",
        )
        Order.objects.filter(pk=order.pk).update(created_at=paid_at)
        for product in products:
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantities[product.pk],
                price=product.price * quantities[product.pk],
                fulfilled=collected,
            )
            Product.objects.filter(pk=product.pk).update(
                quantity=max(product.quantity - quantities[product.pk], 0)
            )
            product.refresh_from_db(fields=["quantity"])
            if review and collected and not Review.objects.filter(product=product, author=buyer).exists():
                rating, text = rng.choice(REVIEW_TEXTS)
                Review.objects.create(
                    product=product,
                    author=buyer,
                    rating=rating,
                    text=text,
                    created_date=paid_at + timedelta(days=1),
                )
        Payment.objects.create(
            user=buyer,
            order=order,
            ref=order.ref,
            amount=Decimal(subtotal + fee),
            status=Payment.PAID,
        )
