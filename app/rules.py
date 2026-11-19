"""Business rules in one place, so procurement can read (and change) the policy without reading code."""

COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "DE": "Germany", "IN": "India",
    "NL": "Netherlands", "FR": "France", "IE": "Ireland", "AE": "United Arab Emirates",
}
COUNTRY_ALIASES = {
    "usa": "US", "united states": "US", "united states of america": "US", "us": "US",
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB", "gb": "GB",
    "germany": "DE", "deutschland": "DE", "de": "DE", "india": "IN", "in": "IN",
    "netherlands": "NL", "france": "FR", "ireland": "IE", "uae": "AE",
}
CURRENCY = {"US": "USD", "GB": "GBP", "DE": "EUR", "IN": "INR", "NL": "EUR", "FR": "EUR", "IE": "EUR", "AE": "AED"}

REQUIRED_FIELDS = {
    "legal_name": "Legal company name",
    "country": "Country of registration",
    "address": "Registered address",
    "contact_name": "Contact name",
    "contact_email": "Contact email",
    "contact_phone": "Contact phone",
    "tax_id": "Tax ID",
}
BANK_FIELDS = {
    "iban": {"iban": "IBAN", "bic": "BIC / SWIFT"},
    "aba": {"routing_number": "ABA routing number", "account_number": "Bank account number"},
    "ifsc": {"ifsc": "IFSC code", "account_number": "Bank account number"},
}
COMMON_BANK_FIELDS = {"bank_name": "Bank name"}

REQUIRED_DOCS = ["tax_certificate", "bank_letter", "insurance_certificate"]
RECOMMENDED_DOCS = ["incorporation_certificate"]

TAX_DOC_NAME = {"US": "IRS Form W-9", "GB": "HMRC VAT registration certificate",
                "DE": "USt-IdNr confirmation (Bundeszentralamt für Steuern)", "IN": "GST registration certificate (REG-06)"}

MIN_LIABILITY_COVER = {"USD": 1_000_000, "GBP": 1_000_000, "EUR": 1_000_000, "INR": 10_000_000, "AED": 3_500_000}
INSURANCE_EXPIRY_WARNING_DAYS = 30
BANK_LETTER_MAX_AGE_DAYS = 183

SEVERITY_WEIGHT = {"pass": 0, "info": 0, "action": 10, "review": 25, "critical": 100}
REJECT_RISK_THRESHOLD = 75
