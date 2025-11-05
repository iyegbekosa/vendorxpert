import requests
from django.conf import settings


def create_paystack_subaccount(vendor, account_number, bank_code):
    url = "https://api.paystack.co/subaccount"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "business_name": vendor.store_name,
        "settlement_bank": bank_code,
        "account_number": account_number,
        "percentage_charge": 5.0,  # adjust as needed
    }

    response = requests.post(url, json=payload, headers=headers)
    data = response.json()

    if response.status_code == 201 and data.get("status"):
        vendor.subaccount_code = data["data"]["subaccount_code"]
        vendor.save()
        return vendor.subaccount_code
    else:
        raise Exception(f"Paystack error: {data.get('message')}")


def retry_paystack_subaccount_creation(
    vendor, account_number, bank_code, max_retries=3
):
    """
    Retry creating a Paystack subaccount for a vendor.
    Useful for vendors whose initial setup failed.
    """
    for attempt in range(max_retries):
        try:
            subaccount_code = create_paystack_subaccount(
                vendor, account_number, bank_code
            )
            return {"success": True, "subaccount_code": subaccount_code}
        except Exception as e:
            if attempt == max_retries - 1:
                return {"success": False, "error": str(e)}
            continue

    return {"success": False, "error": "Max retries exceeded"}


def validate_paystack_subaccount(subaccount_code):
    """
    Validate if a Paystack subaccount is still active and properly configured.
    """
    url = f"https://api.paystack.co/subaccount/{subaccount_code}"
    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers)
        data = response.json()

        if response.status_code == 200 and data.get("status"):
            return {"valid": True, "data": data["data"]}
        else:
            return {"valid": False, "error": data.get("message")}
    except Exception as e:
        return {"valid": False, "error": str(e)}
