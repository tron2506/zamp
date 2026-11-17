"""Company-name matching. Deterministic and explainable: every verdict says *why*."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "inc", "incorporated", "corp", "corporation", "co", "company", "plc",
    "gmbh", "ag", "kg", "ug", "ohg", "mbh", "pvt", "private", "pte", "lp", "llp", "sa", "sas", "sarl",
    "bv", "nv", "srl", "spa", "oy", "ab", "as", "pty", "&", "and",
}
# Words that appear in thousands of company names; sharing only these proves nothing.
GENERIC = {
    "the", "of", "holding", "holdings", "group", "international", "intl", "global", "services",
    "service", "solutions", "consulting", "trading", "enterprises", "industries", "partners",
    "systems", "technologies", "technology", "tech", "management", "uk", "us", "usa", "india",
    "europe", "deutschland", "germany", "energy", "logistics", "supplies", "products", "office",
}


def _ascii(s: str) -> str:
    s = s.replace("ß", "ss")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def tokens(name: str | None) -> list[str]:
    s = _ascii(name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [t for t in s.split() if t]


def normalize(name: str | None) -> str:
    return " ".join(t for t in tokens(name) if t not in LEGAL_SUFFIXES)


def distinctive(name: str | None) -> set[str]:
    return {t for t in tokens(name) if t not in LEGAL_SUFFIXES and t not in GENERIC and len(t) >= 3}


def compare(a: str | None, b: str | None) -> dict:
    """verdict ∈ exact | normalized | near (typo-level) | related (shares distinctive words) | mismatch"""
    if not a or not b:
        return {"verdict": "missing", "score": 0.0, "shared": [], "reason": "one of the names is missing"}
    if a.strip().casefold() == b.strip().casefold():
        return {"verdict": "exact", "score": 1.0, "shared": [], "reason": "identical"}
    na, nb = normalize(a), normalize(b)
    if na and na == nb:
        return {"verdict": "normalized", "score": 0.98, "shared": [],
                "reason": "identical once legal suffixes / punctuation are ignored"}
    ratio = SequenceMatcher(None, na, nb).ratio()
    if ratio >= 0.9:
        return {"verdict": "near", "score": round(ratio, 2), "shared": [],
                "reason": f"{ratio:.0%} similar — looks like a spelling variation"}
    shared = sorted(distinctive(a) & distinctive(b))
    if shared:
        return {"verdict": "related", "score": round(max(ratio, 0.5), 2), "shared": shared,
                "reason": f"different entities that share the distinctive word(s) {', '.join(shared)} "
                          "— possibly parent / subsidiary / trading name"}
    return {"verdict": "mismatch", "score": round(ratio, 2), "shared": [],
            "reason": f"no meaningful overlap ({ratio:.0%} character similarity)"}


def is_match(verdict: str) -> bool:
    return verdict in {"exact", "normalized", "near"}
