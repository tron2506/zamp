"""Document intelligence: PDF text → document type → structured fields.

Deterministic first (keyword scoring + labelled-field regexes). The LLM is only consulted for
documents the classifier is unsure about, or to fill fields the regexes could not find.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

DOC_TYPES = {
    "tax_certificate": "Tax registration certificate",
    "bank_letter": "Bank confirmation letter",
    "insurance_certificate": "Certificate of insurance",
    "incorporation_certificate": "Certificate of incorporation",
}

_KEYWORDS = {
    "tax_certificate": [
        "w-9", "request for taxpayer", "taxpayer identification", "employer identification number",
        "vat registration", "certificate of registration", "value added tax", "umsatzsteuer",
        "ust-idnr", "bundeszentralamt", "gstin", "goods and services tax", "form gst reg-06", "hm revenue",
    ],
    "bank_letter": [
        "bank confirmation", "account holder", "account name", "iban", "sort code", "routing number",
        "account number", "bic", "swift", "ifsc", "this is to confirm", "beneficiary", "bank letter",
        "account details",
    ],
    "insurance_certificate": [
        "certificate of insurance", "certificate of liability", "named insured", "policy number",
        "general liability", "each occurrence", "insurer", "limit of liability", "policy period",
        "coverage", "policyholder", "expiration date",
    ],
    "incorporation_certificate": [
        "certificate of incorporation", "companies house", "registrar of companies", "handelsregister",
        "company number", "incorporated under", "date of incorporation", "registration number",
        "amtsgericht", "ministry of corporate affairs", "articles of organization", "secretary of state",
    ],
}


# ---------------------------------------------------------------- text extraction
def extract_text(path: str | Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n".join((p.extract_text() or "") for p in reader.pages).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------- classification
def classify(text: str) -> dict:
    t = text.lower()
    scores = {k: sum(1 for kw in kws if kw in t) for k, kws in _KEYWORDS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 == 0:
        return {"type": "unknown", "confidence": 0.0, "scores": scores}
    confidence = round((s1 - s2) / s1, 2) if s1 else 0
    # Strong title phrases decide outright (a bank letter can mention a "policy number", etc.)
    titles = {"certificate of insurance": "insurance_certificate", "certificate of liability insurance":
              "insurance_certificate", "bank confirmation": "bank_letter", "form w-9": "tax_certificate",
              "certificate of incorporation": "incorporation_certificate", "vat registration certificate":
              "tax_certificate", "registration certificate": "tax_certificate"}
    head = t[:400]
    for phrase, typ in titles.items():
        if phrase in head:
            return {"type": typ, "confidence": max(confidence, 0.9), "scores": scores}
    return {"type": best if confidence >= 0.34 else "uncertain:" + best, "confidence": confidence, "scores": scores}


# ---------------------------------------------------------------- parsing helpers
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})


def parse_date(s: str | None, country: str = "") -> date | None:
    if not s:
        return None
    s = s.strip().rstrip(".,")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        # US documents use MM/DD/YYYY; everyone else DD/MM/YYYY. Disambiguate when one part > 12.
        if a > 12:
            return _mk(y, b, a)
        if b > 12:
            return _mk(y, a, b)
        return _mk(y, a, b) if country == "US" else _mk(y, b, a)
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m[1].lower() in _MONTHS:
        return _mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
    return None


def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_amount(s: str | None) -> float | None:
    """Handles 1,000,000 · 1.000.000 (German) · 1,000,000.00 · 2 000 000 · £1m · 10,00,000 (Indian)."""
    if not s:
        return None
    s = s.strip()
    mult = 1
    mm = re.search(r"(\d[\d.,\s]*)\s*(m|mm|million|mio|lakh|crore)\b", s, re.I)
    if mm:
        unit = mm[2].lower()
        mult = {"m": 1e6, "mm": 1e6, "million": 1e6, "mio": 1e6, "lakh": 1e5, "crore": 1e7}[unit]
        s = mm[1]
    m = re.search(r"\d[\d.,\s]*\d|\d", s)
    if not m:
        return None
    num = re.sub(r"\s", "", m[0])
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):  # 1.000.000,00
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif num.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", num):
        num = num.replace(".", "")
    elif "," in num:
        if re.fullmatch(r"\d+,\d{1,2}", num):
            num = num.replace(",", ".")
        else:
            num = num.replace(",", "")
    try:
        return float(num) * mult
    except ValueError:
        return None


def detect_currency(s: str) -> str | None:
    s = s or ""
    for sym, cur in (("£", "GBP"), ("€", "EUR"), ("$", "USD"), ("₹", "INR")):
        if sym in s:
            return cur
    m = re.search(r"\b(USD|GBP|EUR|INR|Rs\.?)\b", s, re.I)
    if m:
        return "INR" if m[1].lower().startswith("rs") else m[1].upper()
    return None


# ---------------------------------------------------------------- field extraction
def _field(text: str, labels: list[str], pattern: str = r"(.+)") -> str | None:
    for label in labels:
        # optional bilingual suffix, e.g. "Account holder / Kontoinhaber:"
        m = re.search(rf"(?im)^\s*{label}(?:\s*/\s*[^:\n]{{1,30}})?\s*[:\-–]\s*{pattern}\s*$", text)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


NAME_LABELS = {
    "tax_certificate": [r"name\s*\(as shown on your income tax return\)", r"legal name of business",
                        r"legal name", r"registered name", r"name of (?:the )?(?:taxpayer|business|company)",
                        r"business name", r"name"],
    "bank_letter": [r"account holder(?:\s*name)?", r"name on account", r"account name", r"beneficiary(?: name)?",
                    r"kontoinhaber"],
    "insurance_certificate": [r"named insured", r"insured", r"policyholder", r"policy holder"],
    "incorporation_certificate": [r"company name", r"name of company", r"firma", r"entity name"],
}


def extract_fields(doc_type: str, text: str, country: str = "") -> dict:
    f: dict = {}
    f["entity_name"] = _field(text, NAME_LABELS.get(doc_type, [r"name"]))
    if doc_type == "tax_certificate":
        f["tax_id"] = _field(text, [r"employer identification number(?:\s*\(EIN\))?", r"EIN",
                                    r"VAT registration number", r"VAT number", r"VAT reg(?:istration)? no\.?",
                                    r"USt-IdNr\.?", r"Umsatzsteuer-Identifikationsnummer", r"GSTIN",
                                    r"registration number", r"tax id(?:entification)?(?: number)?"],
                             r"([A-Z0-9][A-Z0-9 \-]{7,20}[A-Z0-9])")
        f["issue_date"] = _field(text, [r"date of issue", r"issue date", r"date of registration",
                                        r"effective date of registration", r"date", r"signed on"])
        f["address"] = _field(text, [r"address", r"principal place of business", r"registered address"])
    elif doc_type == "bank_letter":
        f["iban"] = _field(text, [r"IBAN"], r"([A-Z]{2}\d{2}[A-Z0-9 ]{8,40})")
        f["bic"] = _field(text, [r"BIC(?:\s*/\s*SWIFT)?", r"SWIFT(?:\s*/\s*BIC)?(?: code)?"], r"([A-Z0-9]{8,11})")
        f["account_number"] = _field(text, [r"account number", r"account no\.?", r"a/c no\.?"], r"([0-9 \-]{4,24})")
        f["routing_number"] = _field(text, [r"(?:ABA )?routing number", r"ABA", r"routing transit number"], r"(\d{9})")
        f["ifsc"] = _field(text, [r"IFSC(?: code)?"], r"([A-Z]{4}0[A-Z0-9]{6})")
        f["bank_name"] = _field(text, [r"bank name", r"bank", r"issued by"])
        f["letter_date"] = _field(text, [r"date", r"dated", r"date of letter", r"datum"])
    elif doc_type == "insurance_certificate":
        f["policy_number"] = _field(text, [r"policy number", r"policy no\.?"])
        f["insurer"] = _field(text, [r"insurer(?: a)?", r"insurance company", r"underwritten by", r"carrier"])
        f["coverage_raw"] = _field(text, [r"each occurrence", r"limit of liability", r"coverage limit",
                                          r"general liability limit", r"sum insured", r"limit"])
        f["effective_date"] = _field(text, [r"policy effective date", r"effective date", r"period from",
                                            r"inception date", r"valid from"])
        f["expiry_date"] = _field(text, [r"policy expiration date", r"expiration date", r"expiry date",
                                         r"expires(?: on)?", r"period to", r"valid until", r"valid to"])
        if not f["expiry_date"]:
            # "Period of Insurance: 10 June 2026 to 10 June 2027" (value may sit on the next line)
            m = re.search(r"(?i)(?:policy period|period of insurance|period of cover)\s*:?\s*([^\n]+?)\s+(?:to|until|-|–)\s+([^\n]+)", text)
            if m:
                f["effective_date"] = f.get("effective_date") or m[1].strip()
                f["expiry_date"] = m[2].strip()
    elif doc_type == "incorporation_certificate":
        f["company_number"] = _field(text, [r"company number", r"registration number", r"HRB", r"CIN",
                                            r"file number"])
        f["incorporation_date"] = _field(text, [r"date of incorporation", r"incorporated on", r"date"])
    return {k: v for k, v in f.items() if v}


def finalize_fields(doc_type: str, fields: dict, country: str) -> dict:
    """Turn raw strings into typed values (dates, amounts) — the part we never delegate to an LLM."""
    out = dict(fields)
    for key in ("issue_date", "letter_date", "effective_date", "expiry_date", "incorporation_date"):
        if out.get(key):
            d = parse_date(str(out[key]), country)
            out[key + "_parsed"] = d.isoformat() if d else None
    if out.get("coverage_raw"):
        out["coverage_amount"] = parse_amount(str(out["coverage_raw"]))
        out["coverage_currency"] = detect_currency(str(out["coverage_raw"]))
    return out


def summarize_for_display(doc_type: str, fields: dict) -> dict:
    keep = [k for k in fields if not k.endswith("_parsed")]
    return {k: fields[k] for k in keep}


def today() -> date:
    return datetime.now().date()
