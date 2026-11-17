"""Country-specific tax ID validation. Pure, deterministic functions."""
from __future__ import annotations

import re

SUPPORTED = {"US": "EIN", "GB": "VAT number", "DE": "USt-IdNr (VAT ID)", "IN": "GSTIN"}

# IRS never issues EINs with these prefixes.
_EIN_INVALID_PREFIXES = {"00", "07", "08", "09", "17", "18", "19", "28", "29", "49",
                         "69", "70", "78", "79", "89", "96", "97"}
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def clean(tax_id: str | None) -> str:
    return re.sub(r"[\s.\-/]", "", (tax_id or "")).upper()


# ---------------------------------------------------------------- checksums
def gb_vat_checksum_ok(digits: str) -> bool:
    """HMRC mod-97 (and the 'mod 9755' variant for numbers issued after 2010)."""
    if not re.fullmatch(r"\d{9}", digits):
        return False
    total = sum(int(d) * w for d, w in zip(digits[:7], range(8, 1, -1))) + int(digits[7:])
    return total % 97 == 0 or (total + 55) % 97 == 0


def gb_vat_check_digits(first7: str) -> str:
    total = sum(int(d) * w for d, w in zip(first7, range(8, 1, -1)))
    return f"{(-total) % 97:02d}"


def de_vat_check_digit(first8: str) -> int:
    """ISO 7064 MOD 11,10 as used for the German USt-IdNr."""
    product = 10
    for d in first8:
        s = (int(d) + product) % 10 or 10
        product = (2 * s) % 11
    check = 11 - product
    return 0 if check == 10 else check


def de_vat_checksum_ok(digits: str) -> bool:
    return bool(re.fullmatch(r"\d{9}", digits)) and de_vat_check_digit(digits[:8]) == int(digits[8])


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, c in enumerate(first14):
        product = _B36.index(c) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _B36[(36 - total % 36) % 36]


def gstin_checksum_ok(g: str) -> bool:
    return len(g) == 15 and all(c in _B36 for c in g) and gstin_check_char(g[:14]) == g[14]


# ---------------------------------------------------------------- formats
_FORMATS = {
    "US": re.compile(r"^\d{9}$"),
    "GB": re.compile(r"^(GB)?(\d{9}|\d{12})$"),
    "DE": re.compile(r"^DE\d{9}$"),
    "IN": re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"),
}


def detect_countries(tax_id: str) -> list[str]:
    """Which supported countries' formats does this ID look like? Prefixed IDs are unambiguous."""
    t = clean(tax_id)
    if t.startswith("GB"):
        return ["GB"] if _FORMATS["GB"].match(t) else []
    if t.startswith("DE"):
        return ["DE"] if _FORMATS["DE"].match(t) else []
    return [c for c, rx in _FORMATS.items() if rx.match(t)]


def validate(country: str, tax_id: str | None, entity_is_company: bool = True) -> dict:
    """Returns {valid, format_ok, checksum_ok, normalized, detected_countries, problem, notes}.

    problem ∈ {None, 'missing', 'unsupported_country', 'format', 'checksum', 'jurisdiction'}
    """
    t = clean(tax_id)
    out = {"valid": False, "format_ok": False, "checksum_ok": None, "normalized": t,
           "detected_countries": detect_countries(t), "problem": None, "notes": [],
           "label": SUPPORTED.get(country, "tax ID")}
    if not t:
        out["problem"] = "missing"
        return out
    if country not in SUPPORTED:
        out["problem"] = "unsupported_country"
        return out

    rx = _FORMATS[country]
    if not rx.match(t):
        others = [c for c in out["detected_countries"] if c != country]
        out["problem"] = "jurisdiction" if others else "format"
        return out
    out["format_ok"] = True

    if country == "US":
        out["normalized"] = f"{t[:2]}-{t[2:]}"
        if t[:2] in _EIN_INVALID_PREFIXES:
            out["checksum_ok"] = False
            out["problem"] = "checksum"
            out["notes"].append(f"EIN prefix {t[:2]} is never issued by the IRS")
            return out
        out["checksum_ok"] = True  # EINs carry no check digit; prefix table is the strongest test
    elif country == "GB":
        digits = t[2:] if t.startswith("GB") else t
        out["normalized"] = "GB" + digits
        out["checksum_ok"] = gb_vat_checksum_ok(digits[:9])
    elif country == "DE":
        out["checksum_ok"] = de_vat_checksum_ok(t[2:])
    elif country == "IN":
        out["checksum_ok"] = gstin_checksum_ok(t)
        state = int(t[:2])
        if not 1 <= state <= 38:
            out["checksum_ok"] = False
            out["notes"].append(f"State code {t[:2]} does not exist")
        pan = t[2:12]
        out["pan"] = pan
        if entity_is_company and pan[3] == "P":
            out["notes"].append("Embedded PAN is an individual's PAN (4th char 'P'), not a company's ('C')")
            out["pan_individual"] = True

    if not out["checksum_ok"]:
        out["problem"] = "checksum"
        return out
    out["valid"] = True
    return out


def edit_distance(a: str, b: str) -> int:
    a, b = clean(a), clean(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
