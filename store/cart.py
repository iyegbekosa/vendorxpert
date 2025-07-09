from django.conf import settings
from django.db import models
from .models import Product, CartItem


class Cart(object):
    def __init__(self, request):
        self.session = request.session
        self.request = request
        self.user = request.user if request.user.is_authenticated else None

        # For authenticated users, use database storage
        if self.user:
            self.cart = None  # We'll load from database
        else:
            # For anonymous users, use session storage
            cart = self.session.get(settings.CART_SESSION_ID)
            if not cart:
                cart = self.session[settings.CART_SESSION_ID] = {}
            self.cart = cart

    def __iter__(self):
        if self.user:
            # For authenticated users, iterate through CartItem objects
            cart_items = CartItem.objects.filter(user=self.user).select_related(
                "product"
            )
            for cart_item in cart_items:
                yield {
                    "product": cart_item.product,
                    "quantity": cart_item.quantity,
                    "total_price": cart_item.total_price,
                    "id": str(cart_item.product.id),
                }
        else:
            # For anonymous users, use session-based iteration
            if self.cart:
                for p in self.cart.keys():
                    self.cart[str(p)]["product"] = Product.objects.get(pk=p)

                for item in self.cart.values():
                    item["total_price"] = int(item["product"].price * item["quantity"])
                    yield item

    def __len__(self):
        if self.user:
            # For authenticated users, count CartItem objects
            return (
                CartItem.objects.filter(user=self.user).aggregate(
                    total=models.Sum("quantity")
                )["total"]
                or 0
            )
        else:
            # For anonymous users, use session-based count
            if self.cart:
                return sum(item["quantity"] for item in self.cart.values())
            return 0

    def save(self):
        if not self.user and self.cart is not None:
            # Only save session for anonymous users
            self.session[settings.CART_SESSION_ID] = self.cart
            self.session.modified = True

    def add(self, product_id, quantity=1, update_quantity=False):
        if self.user:
            # For authenticated users, use database storage
            try:
                product = Product.objects.get(id=product_id)
                cart_item, created = CartItem.objects.get_or_create(
                    user=self.user, product=product, defaults={"quantity": quantity}
                )

                if not created and update_quantity:
                    cart_item.quantity += int(quantity)
                    if cart_item.quantity <= 0:
                        cart_item.delete()
                        return
                elif not created:
                    cart_item.quantity = int(quantity)

                cart_item.save()
            except Product.DoesNotExist:
                pass
        else:
            # For anonymous users, use session storage
            if self.cart is not None:
                product_id = str(product_id)

                if product_id not in self.cart:
                    self.cart[product_id] = {"quantity": quantity, "id": product_id}

                if update_quantity:
                    self.cart[product_id]["quantity"] += int(quantity)

                    if self.cart[product_id]["quantity"] == 0:
                        self.remove(product_id)

                self.save()

    def get_total_cost(self):
        if self.user:
            # For authenticated users, calculate from CartItem objects
            total = 0
            cart_items = CartItem.objects.filter(user=self.user).select_related(
                "product"
            )
            for cart_item in cart_items:
                total += cart_item.total_price
            return int(total)
        else:
            # For anonymous users, use session-based calculation
            if self.cart:
                for p in self.cart.keys():
                    self.cart[str(p)]["product"] = Product.objects.get(pk=p)

                return int(
                    sum(
                        item["product"].price * item["quantity"]
                        for item in self.cart.values()
                    )
                )
            return 0

    def remove(self, product_id):
        if self.user:
            # For authenticated users, remove from database
            try:
                CartItem.objects.filter(user=self.user, product_id=product_id).delete()
            except CartItem.DoesNotExist:
                pass
        else:
            # For anonymous users, remove from session
            if self.cart and str(product_id) in self.cart:
                del self.cart[str(product_id)]
                self.save()

    def clear(self):
        if self.user:
            # For authenticated users, clear database entries
            CartItem.objects.filter(user=self.user).delete()
        else:
            # For anonymous users, clear session
            if settings.CART_SESSION_ID in self.session:
                del self.session[settings.CART_SESSION_ID]
                self.session.modified = True
