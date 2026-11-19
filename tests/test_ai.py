"""AI features with a fake LLM: the guardrails are what's under test, not the model."""
import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import ai, config, db, llm, main, pipeline, samples


@pytest.fixture(scope="module")
def metas():
    db.init()
    return {m["key"]: m for m in samples.generate()}


def fake_llm(monkeypatch, reply: dict):
    async def chat(system, user, **kw):
        return json.dumps(reply)
    monkeypatch.setattr(llm, "enabled", lambda: True)
    monkeypatch.setattr(llm, "chat", chat)


def files_for(meta):
    folder = config.SAMPLES_DIR / meta["key"]
    return [{"slot": s, "filename": fn, "path": str(folder / fn)} for s, fn in meta["files"].items()]


def run(meta):
    rid = "T-" + uuid.uuid4().hex[:6]
    sub = samples.to_submission(meta)
    db.create_run(rid, sub, "test")
    asyncio.run(pipeline.run_pipeline(rid, sub, delay=0))
    return db.get_run(rid)


# ------------------------------------------------------------------ AI second look
def test_ai_notes_are_grounded_filtered_and_never_change_the_decision(metas, monkeypatch):
    db.reset_all()
    fake_llm(monkeypatch, {"observations": [
        {"title": "Address differs", "detail": "VAT certificate is London.", "quote": "71 Shoreditch High St",
         "source": "vat_certificate.pdf", "category": "address", "confidence": "high"},
        {"title": "Invented", "detail": "Made up.", "quote": "this text is not anywhere", "source": "form",
         "category": "other", "confidence": "high"},                                   # ungrounded → dropped
        {"title": "Unsure", "detail": "Maybe.", "quote": "LUMEN DESIGN LTD", "source": "vat_certificate.pdf",
         "category": "name", "confidence": "medium"},                                  # not high → dropped
        {"title": "Repeat of a rule", "detail": "Tax ID is from the UK.", "quote": "445 1027", "source":
         "vat_certificate.pdf", "category": "jurisdiction", "confidence": "high"},     # rules covered it → dropped
    ]})
    r = run(metas["lumen_wrong_jurisdiction"])
    notes = [f for f in r["result"]["findings"] if f["code"] == pipeline.AI_NOTE]
    assert [n["title"] for n in notes] == ["Address differs"]
    assert notes[0]["severity"] == "info" and notes[0]["request"] is None
    assert r["status"] == "PENDING" and r["risk_score"] == 50        # identical to the rules-only outcome


def test_decide_ignores_ai_notes_even_if_mislabelled():
    F = pipeline.Finding
    d = pipeline.decide([F("TAX_VALID", "pass", ""), F(pipeline.AI_NOTE, "critical", "x", weight=100)])
    assert d["status"] == "APPROVED" and d["risk_score"] == 0


def test_happy_path_unchanged_when_ai_says_nothing(metas, monkeypatch):
    db.reset_all()
    fake_llm(monkeypatch, {"observations": []})
    assert run(metas["northwind_happy"])["status"] == "APPROVED"


# ------------------------------------------------------------------ autofill
def test_autofill_rules_only(metas):
    out = asyncio.run(ai.autofill(files_for(metas["northwind_happy"])))
    f = {k: v["value"] for k, v in out["fields"].items()}
    assert f["legal_name"] == "Northwind Analytics Ltd"            # naturally-cased variant preferred
    assert f["country"] == "GB" and f["tax_id"] == samples.GB_VAT_NORTHWIND
    assert f["iban"] == samples.IBAN_NORTHWIND and f["bic"] == "BARCGB22"
    assert all(v["source"] == "rule" for v in out["fields"].values()) and out["llm"] is False


def test_autofill_ai_fills_gaps_but_cannot_invent(metas, monkeypatch):
    fake_llm(monkeypatch, {"fields": {
        "iban": {"value": samples.IBAN_ORCHARD, "file": "lloyds_confirmation.pdf"},
        "account_holder": {"value": "Orchard & Vine Catering Ltd", "file": "lloyds_confirmation.pdf"},
        "bic": {"value": "FAKEGB99", "file": "lloyds_confirmation.pdf"},              # not in the document
    }})
    out = asyncio.run(ai.autofill(files_for(metas["orchard_narrative_letter"])))
    assert out["fields"]["iban"] == {"value": samples.IBAN_ORCHARD, "source": "ai", "from": "lloyds_confirmation.pdf"}
    assert out["fields"]["account_holder"]["from"] == "lloyds_confirmation.pdf"
    assert "bic" not in out["fields"]



# ------------------------------------------------------------------ ask about this case
def test_ask_filters_citations_and_masks_numbers(metas, monkeypatch):
    db.reset_all()
    r = run(metas["cobalt_bad_documents"])
    fake_llm(monkeypatch, {"answer": "Account 3849201177 is fine; insurance expired on 2026-10-14.",
                           "cites": ["INSURANCE_EXPIRED", "MADE_UP_CODE"]})
    out = asyncio.run(ai.ask_case(r, "why?", []))
    assert out["cites"] == ["INSURANCE_EXPIRED"]
    assert "3849201177" not in out["answer"] and "••••1177" in out["answer"]
    assert "2026-10-14" in out["answer"]                       # dates are not mistaken for account numbers


def test_ask_endpoint_requires_ai(metas):
    db.reset_all()
    r = run(metas["northwind_happy"])
    with TestClient(main.app) as c:
        resp = c.post(f"/api/runs/{r['id']}/ask", json={"question": "why approved?"})
    assert resp.status_code == 503


def test_autofill_endpoint(metas):
    m = metas["brightpath_gstin_typo"]
    folder = config.SAMPLES_DIR / m["key"]
    with TestClient(main.app) as c:
        files = {slot: (fn, (folder / fn).read_bytes(), "application/pdf") for slot, fn in m["files"].items()}
        resp = c.post("/api/autofill", files=files)
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"]["tax_id"]["value"] == samples.GSTIN_BRIGHTPATH     # the certificate's, i.e. the correct one
    assert body["fields"]["ifsc"]["value"] == "HDFC0001234"
