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

    if response.status_code == 200 and data.get("status"):
        vendor.subaccount_code = data["data"]["subaccount_code"]
        vendor.save()
        return vendor.subaccount_code
    else:
        raise Exception(f"Paystack error: {data.get('message')}")
