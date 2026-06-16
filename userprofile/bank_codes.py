"""Nigerian bank codes accepted by Paystack for subaccount creation."""

# Maps Paystack bank code → display name. Covers commercial, microfinance, and
# digital banks that are active as of 2025. Keep in sync with Paystack's bank
# list (https://api.paystack.co/bank?country=nigeria).
NIGERIAN_BANK_CODES: dict[str, str] = {
    # Commercial banks
    "044": "Access Bank",
    "063": "Access Bank (Diamond)",
    "035A": "ALAT by Wema",
    "401": "ASO Savings and Loans",
    "023": "Citibank Nigeria",
    "050": "Ecobank Nigeria",
    "562": "Ekondo MFB",
    "214": "First City Monument Bank (FCMB)",
    "011": "First Bank of Nigeria",
    "070": "Fidelity Bank",
    "058": "Guaranty Trust Bank (GTBank)",
    "030": "Heritage Bank",
    "301": "Jaiz Bank",
    "082": "Keystone Bank",
    "014": "Mainstreet MFB",
    "526": "Parallex Bank",
    "076": "Polaris Bank",
    "101": "Providus Bank",
    "125": "Rubies MFB",
    "221": "Stanbic IBTC Bank",
    "068": "Standard Chartered Bank",
    "232": "Sterling Bank",
    "100": "SunTrust Bank",
    "032": "Union Bank of Nigeria",
    "033": "United Bank for Africa (UBA)",
    "215": "Unity Bank",
    "035": "Wema Bank",
    "057": "Zenith Bank",
    # Digital / fintech banks
    "304": "OPay",
    "999991": "PalmPay",
    "50515": "MoniePoint MFB",
    "90267": "Kuda Bank",
    "566": "VFD MFB (VBank)",
    "318": "Fidelity MFB",
    "559": "Coronation Merchant Bank",
    "058A": "GTBank (Digital)",
    "120001": "9PSB (9 Payment Service Bank)",
    "090405": "Prospa MFB",
}

VALID_BANK_CODES: frozenset[str] = frozenset(NIGERIAN_BANK_CODES.keys())


def get_bank_name(code: str) -> str:
    """Return the bank display name for a code, or the code itself if unknown."""
    return NIGERIAN_BANK_CODES.get(code, code)
