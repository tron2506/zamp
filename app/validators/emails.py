"""Contact-email checks. Deterministic and offline: a bundled copy of the IANA top-level-domain list
(app/validators/tlds.txt, refresh from https://data.iana.org/TLD/tlds-alpha-by-domain.txt) and
look-alike detection for the big free-mail providers."""
from __future__ import annotations

import re
from pathlib import Path

from . import names

REAL_TLDS = {ln.strip().lower() for ln in Path(__file__).with_name("tlds.txt").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")}

FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in", "yahoo.in", "yahoo.de", "ymail.com",
    "hotmail.com", "hotmail.co.uk", "hotmail.de", "outlook.com", "outlook.de", "live.com", "live.co.uk", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "gmx.de", "gmx.com", "gmx.net",
    "web.de", "yandex.com", "mail.com", "rediffmail.com", "zoho.com",
}
# Provider name -> its real domain. Brands that only ever use one domain are flagged on *any* other ending
# (gmail.co, gmail.vo); the rest only on one-character typos (hotmial.com), since they have many regional domains.
BRANDS = {"gmail": "gmail.com", "googlemail": "googlemail.com", "icloud": "icloud.com", "protonmail": "protonmail.com",
          "yahoo": "yahoo.com", "hotmail": "hotmail.com", "outlook": "outlook.com", "yandex": "yandex.com",
          "rediffmail": "rediffmail.com"}
SINGLE_DOMAIN = {"gmail", "googlemail", "icloud", "protonmail"}

def _typo_distance(a: str, b: str) -> int:
    """Edit distance where swapping two neighbouring letters counts as one typo (hotmial vs hotmail)."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


_SYNTAX = re.compile(r"[^@\s]+@([a-z0-9-]+\.)+[a-z]{2,}")


def check(email: str | None) -> dict:
    e = (email or "").strip().lower()
    domain = e.rsplit("@", 1)[-1] if "@" in e else ""
    tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
    free = domain in FREE_EMAIL_DOMAINS
    lookalike = None
    if domain and not free:
        label = domain.split(".")[0]
        for brand, real in BRANDS.items():
            if (label == brand and brand in SINGLE_DOMAIN) or (label != brand and len(label) >= 5
                                                              and _typo_distance(label, brand) == 1):
                lookalike = real
                break
    return {"email": e, "domain": domain, "tld": tld, "syntax_ok": bool(_SYNTAX.fullmatch(e)),
            "tld_ok": tld in REAL_TLDS, "free": free, "lookalike": lookalike}


def related_to_company(domain: str, company_names: list[str | None]) -> bool:
    """Does the email domain look like it belongs to this company? (a name word in it, or its initials)"""
    labels = domain.lower().split(".")
    flat = re.sub(r"[^a-z0-9]", "", domain.lower())
    for n in company_names:
        toks = [t for t in names.tokens(n) if t not in names.LEGAL_SUFFIXES]
        if any(len(t) >= 3 and t in flat for t in toks):
            return True
        initials = "".join(t[0] for t in toks)
        if len(initials) >= 2 and initials in labels:
            return True
    return False
