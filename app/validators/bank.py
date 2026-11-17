"""Bank detail validation: IBAN, BIC/SWIFT, US ABA routing, Indian IFSC."""
from __future__ import annotations

import re

IBAN_LENGTHS = {"GB": 22, "DE": 22, "NL": 18, "FR": 27, "IE": 22, "ES": 24, "IT": 27, "BE": 16,
                "CH": 21, "AT": 20, "LU": 20, "PL": 28, "AE": 23, "CY": 28, "MT": 31, "PT": 25}

# Which identifiers each country's payments rail needs.
BANK_SCHEME = {"GB": "iban", "DE": "iban", "US": "aba", "IN": "ifsc"}


def clean(s: str | None) -> str:
    return re.sub(r"[\s\-]", "", s or "").upper()


def iban_validate(iban: str | None) -> dict:
    i = clean(iban)
    out = {"valid": False, "normalized": i, "country": i[:2] if len(i) >= 2 else None, "problem": None}
    if not i:
        out["problem"] = "missing"
        return out
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", i):
        out["problem"] = "format"
        return out
    expected = IBAN_LENGTHS.get(i[:2])
    if expected and len(i) != expected:
        out["problem"] = "length"
        out["expected_length"] = expected
        return out
    rearranged = i[4:] + i[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    if int(numeric) % 97 != 1:
        out["problem"] = "checksum"
        return out
    out["valid"] = True
    return out


def iban_with_check_digits(country: str, bban: str) -> str:
    numeric = "".join(str(int(c, 36)) for c in (bban + country + "00"))
    return f"{country}{98 - int(numeric) % 97:02d}{bban}"


def bic_validate(bic: str | None) -> dict:
    b = clean(bic)
    out = {"valid": False, "normalized": b, "country": None, "problem": None}
    if not b:
        out["problem"] = "missing"
        return out
    if not re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", b):
        out["problem"] = "format"
        return out
    out["country"] = b[4:6]
    out["valid"] = True
    return out


def aba_validate(routing: str | None) -> dict:
    r = clean(routing)
    out = {"valid": False, "normalized": r, "problem": None}
    if not r:
        out["problem"] = "missing"
        return out
    if not re.fullmatch(r"\d{9}", r):
        out["problem"] = "format"
        return out
    d = [int(c) for c in r]
    if (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10:
        out["problem"] = "checksum"
        return out
    out["valid"] = True
    return out


def aba_check_digit(first8: str) -> str:
    d = [int(c) for c in first8]
    s = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5])
    return str((10 - s % 10) % 10)


def ifsc_validate(ifsc: str | None) -> dict:
    f = clean(ifsc)
    out = {"valid": False, "normalized": f, "problem": None}
    if not f:
        out["problem"] = "missing"
        return out
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", f):
        out["problem"] = "format"
        return out
    out["valid"] = True
    return out


def account_number_validate(acct: str | None, country: str) -> dict:
    a = clean(acct)
    out = {"valid": False, "normalized": a, "problem": None}
    if not a:
        out["problem"] = "missing"
        return out
    lo, hi = {"US": (4, 17), "IN": (9, 18)}.get(country, (6, 20))
    if not (a.isdigit() and lo <= len(a) <= hi):
        out["problem"] = "format"
        out["expected"] = f"{lo}–{hi} digits"
        return out
    out["valid"] = True
    return out


def account_fingerprint(country: str, iban: str = "", routing: str = "", ifsc: str = "", account: str = "") -> str | None:
    """A canonical key identifying the destination account, used for duplicate-account detection."""
    if clean(iban):
        return "IBAN:" + clean(iban)
    if clean(routing) and clean(account):
        return f"ABA:{clean(routing)}:{clean(account)}"
    if clean(ifsc) and clean(account):
        return f"IFSC:{clean(ifsc)}:{clean(account)}"
    return None


def mask(value: str | None, keep: int = 4) -> str:
    v = clean(value)
    if len(v) <= keep:
        return v
    return "•" * min(len(v) - keep, 8) + v[-keep:]
