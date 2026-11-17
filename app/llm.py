"""Thin OpenAI-compatible chat client (works with GLM / Z.ai, OpenRouter, Groq, vLLM, Ollama…).

Every call is optional: on any error, timeout, or invalid JSON we return None and the pipeline
uses its deterministic fallback. The LLM never produces a decision.
"""
from __future__ import annotations

import json
import re

import httpx

from . import config


def enabled() -> bool:
    return config.LLM_ENABLED


def status() -> dict:
    return {"enabled": config.LLM_ENABLED, "model": config.LLM_MODEL or None,
            "base_url": config.LLM_BASE_URL or None}


async def chat(system: str, user: str, json_mode: bool = False, max_tokens: int = 900) -> str | None:
    if not config.LLM_ENABLED:
        return None
    body = {
        "model": config.LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            r = await client.post(f"{config.LLM_BASE_URL}/chat/completions", json=body, headers=headers)
            if r.status_code == 400 and json_mode:  # provider doesn't support response_format
                body.pop("response_format")
                r = await client.post(f"{config.LLM_BASE_URL}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            choice = r.json()["choices"][0]
            content = (choice["message"].get("content") or "").strip()
            if not content:
                print(f"[llm] empty reply (finish_reason={choice.get('finish_reason')}) — falling back")
            return content or None
    except Exception as e:  # network, auth, quota, schema — all fall back
        print(f"[llm] call failed: {type(e).__name__}: {e}")
        return None


def _parse_json(s: str | None) -> dict | None:
    if not s:
        return None
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S)
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


DOC_FIELDS = {
    "tax_certificate": ["entity_name", "tax_id", "issue_date", "address"],
    "bank_letter": ["entity_name", "iban", "bic", "account_number", "routing_number", "ifsc", "bank_name", "letter_date"],
    "insurance_certificate": ["entity_name", "policy_number", "insurer", "coverage_raw", "effective_date", "expiry_date"],
    "incorporation_certificate": ["entity_name", "company_number", "incorporation_date"],
}


async def classify_and_extract(text: str, hint_type: str | None) -> dict | None:
    """Ask the model what the document is and to copy out fields *verbatim*. Returns
    {"type": ..., "fields": {...}} or None."""
    schema = {k: v for k, v in DOC_FIELDS.items()}
    system = ("You read business documents submitted during vendor onboarding. Identify the document type and "
              "copy field values EXACTLY as written in the text (no reformatting, no guessing). Use null for "
              "anything not present. entity_name = the company the document is about (account holder, insured "
              "party, taxpayer, or registered company). Respond with JSON only.")
    user = (f"Allowed types and their fields: {json.dumps(schema)}. Use type 'other' if none apply.\n"
            f"The keyword classifier's guess was: {hint_type or 'none'}.\n"
            'Respond as {"type": "<type>", "fields": {...}}.\n\nDOCUMENT TEXT:\n"""\n' + text[:6000] + '\n"""')
    data = _parse_json(await chat(system, user, json_mode=True, max_tokens=1200))
    if not data or "type" not in data:
        return None
    allowed = DOC_FIELDS.get(data["type"], [])
    fields = data.get("fields") or {}
    clean = {k: str(v).strip() for k, v in fields.items() if k in allowed and v not in (None, "", "null")}
    # Guard against hallucination: a value must literally occur in the document text.
    flat = re.sub(r"\s+", "", text).lower()
    clean = {k: v for k, v in clean.items() if re.sub(r"\s+", "", v).lower() in flat}
    return {"type": data["type"], "fields": clean}


async def write_vendor_email(vendor: str, contact: str, status: str, requests: list[str]) -> dict | None:
    """Model writes only the opening and closing paragraphs; the request list is inserted by code."""
    system = ("You write short, warm, professional emails from a procurement team to a vendor. Plain English, no "
              "jargon, no promises about timelines, no mention of fraud or internal risk scores. The greeting line "
              "('Hi <name>,') and the sign-off are added by the system: do NOT include them. JSON only.")
    user = (f"Vendor: {vendor}. Contact: {contact}. Onboarding status: {status}. The email will contain this exact "
            f"bulleted list of {len(requests)} items, which you must NOT repeat or rephrase: {json.dumps(requests)}.\n"
            'Return {"subject": "...", "opening": "1-2 sentences before the list", "closing": "1-2 sentences after the list"}.')
    data = _parse_json(await chat(system, user, json_mode=True, max_tokens=900))
    if data and all(isinstance(data.get(k), str) and data[k].strip() for k in ("subject", "opening", "closing")):
        data["opening"] = re.sub(r"^\s*(hi|hello|dear|good (morning|afternoon))\b[^,.!\n]{0,60}[,.!]\s*", "", data["opening"],
                                 flags=re.I).strip()
        data["opening"] = data["opening"][:1].upper() + data["opening"][1:]
        data["closing"] = re.sub(r"\s*(best|kind)? ?regards,?.*$", "", data["closing"], flags=re.I | re.S).strip()
        return data if data["opening"] and data["closing"] else None
    return None


async def write_reviewer_summary(facts: dict) -> str | None:
    system = ("You brief a procurement reviewer on a vendor onboarding case in 2-3 plain sentences. Only use the facts "
              "given; do not add new concerns or change the decision. Respond as JSON: {\"summary\": \"...\"}")
    data = _parse_json(await chat(system, json.dumps(facts, default=str), json_mode=True, max_tokens=900))
    out = data.get("summary") if data else None
    return out.strip() if isinstance(out, str) and out.strip() else None
