from . import paystack
from .paystack import PaystackError

# Paystack requires a default commission on every subaccount. Checkout always
# sends an explicit flat split, so this value only applies to payments made
# outside the marketplace checkout.
SUBACCOUNT_DEFAULT_PERCENTAGE_CHARGE = 5.0

__all__ = ["PaystackError", "create_paystack_subaccount"]


def create_paystack_subaccount(vendor, account_number, bank_code):
    """Create the vendor's settlement subaccount and persist its code."""
    data = paystack.create_subaccount(
        business_name=vendor.store_name,
        bank_code=bank_code,
        account_number=account_number,
        percentage_charge=SUBACCOUNT_DEFAULT_PERCENTAGE_CHARGE,
    )
    vendor.subaccount_code = data["subaccount_code"]
    vendor.save(update_fields=["subaccount_code"])
    return vendor.subaccount_code
