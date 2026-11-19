"""Vendor-facing email and internal reviewer summary.

The *content* that matters (which items are requested) is always assembled by code. The LLM, if
configured, only writes the greeting/closing sentences around it.
"""
from __future__ import annotations

from . import llm

FRAUD_CODES = {"BANK_ACCOUNT_IN_USE", "BEC_PATTERN", "TAX_ID_IN_USE"}


def _recipient(r) -> tuple[str, str | None]:
    """If the contact's email domain changed mid-onboarding, write to the contact we already trusted."""
    to = r.sub.get("contact_email", "")
    codes = {f.code for f in r.findings}
    if r.prior and "CONTACT_DOMAIN_CHANGED" in codes:
        original = r.prior["submission"].get("contact_email")
        if original:
            return original, f"Sent to the original contact {original}, not the new address {to}."
    if "BAD_EMAIL" in codes:
        phone = r.sub.get("contact_phone")
        return to, ("This address cannot receive mail. Contact the vendor by phone"
                    + (f" ({phone})" if phone else "") + " to get a working email address.")
    return to, None


async def build_email(r, d: dict) -> dict:
    s = r.sub
    name = s.get("contact_name") or "there"
    vendor = s.get("legal_name") or "your company"
    to, routing_note = _recipient(r)
    status = d["status"]
    codes = {f.code for f in r.findings}
    requests = list(dict.fromkeys(f.request for f in r.findings if f.request and f.severity in ("action", "review")))
    conditions = [f.title for f in r.findings if f.severity == "info" and f.code in ("INSURANCE_EXPIRING",)]

    if status == "APPROVED":
        subject = f"{vendor} — vendor onboarding approved"
        opening = f"Good news — {vendor} has been approved as a vendor and is now set up in our payment system."
        items = [f"Please note: {c}. We will contact you for the renewal certificate." for c in conditions]
        closing = "You can now submit invoices against purchase orders. Thank you for completing onboarding."
    elif status == "PENDING":
        subject = f"{vendor} — action needed to complete vendor onboarding"
        opening = (f"Thank you for your onboarding submission for {vendor}. We have reviewed it and need a few more "
                   "things before we can approve it:")
        items = requests or []
        if not items:
            opening = (f"Thank you for your onboarding submission for {vendor}. It is with our procurement team for a "
                       "final review; you do not need to do anything right now.")
        closing = "Once we receive these, we will re-run the checks straight away. Reply to this email if anything is unclear."
    else:
        if "DUPLICATE_VENDOR" in codes and not codes & FRAUD_CODES:
            dup = next(f for f in r.findings if f.code == "DUPLICATE_VENDOR")
            subject = f"{vendor} — you are already registered"
            opening = (f"{vendor} is already registered as an approved vendor (reference {dup.evidence.get('vendor_id')}), "
                       "so we have not created a second record.")
            items, closing = [], "If you need to update your existing details, please contact our procurement team."
        else:
            # Never explain fraud rules to the counter-party; that only teaches how to evade them.
            subject = f"{vendor} — vendor onboarding update"
            opening = (f"Thank you for your interest in working with us. We are unable to complete onboarding for "
                       f"{vendor} on the basis of the information provided.")
            items, closing = [], "If you believe this is an error, please contact our procurement team directly by phone."

    used_llm = False
    if items and status == "PENDING" and llm.enabled():
        worded = await llm.write_vendor_email(vendor, name, status, items)
        if worded:
            subject, opening, closing, used_llm = worded["subject"], worded["opening"], worded["closing"], True

    bullets = "\n".join(f"  {i}. {it}" for i, it in enumerate(items, 1))
    body = f"Hi {name},\n\n{opening}\n\n" + (f"{bullets}\n\n" if bullets else "") + f"{closing}\n\nBest regards,\nProcurement Team"
    return {"to": to, "subject": subject, "body": body, "items": items, "llm": used_llm, "routing_note": routing_note}


async def reviewer_summary(r, d: dict) -> dict:
    s = r.sub
    flags = [f for f in r.findings if f.severity in ("critical", "review", "action")]
    flags.sort(key=lambda f: -f.risk())
    passed = [f.title for f in r.findings if f.severity == "pass"]
    template = (f"{s.get('legal_name')} ({s.get('country')}) → {d['status']} at risk {d['risk_score']}/100. "
                + (f"Main issue: {flags[0].title}. " if flags else "No open issues. ")
                + (f"{len(flags) - 1} other open item(s). " if len(flags) > 1 else "")
                + f"{len(passed)} checks passed.")
    text, used = template, False
    if llm.enabled():
        facts = {"vendor": s.get("legal_name"), "country": s.get("country"), "decision": d["status"],
                 "risk_score": d["risk_score"], "reason": d["reason"],
                 "open_issues": [{"severity": f.severity, "title": f.title, "detail": f.detail} for f in flags[:6]],
                 "checks_passed": passed[:8]}
        out = await llm.write_reviewer_summary(facts)
        if out:
            text, used = out, True
            r.llm_used.append("wrote reviewer summary")
    return {"text": text, "llm": used}
