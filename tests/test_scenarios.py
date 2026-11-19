"""End-to-end: every test scenario through the real pipeline (real PDFs, real SQLite)."""
import asyncio
import uuid

import pytest

from app import db, pipeline, samples


@pytest.fixture(scope="module")
def metas():
    db.init()
    return {m["key"]: m for m in samples.generate()}


def run(meta):
    rid = "T-" + uuid.uuid4().hex[:6]
    sub = samples.to_submission(meta)
    db.create_run(rid, sub, "test")
    asyncio.run(pipeline.run_pipeline(rid, sub, delay=0))
    return db.get_run(rid)


def codes(r, sev=None):
    return {f["code"] for f in r["result"]["findings"] if sev is None or f["severity"] in sev}


@pytest.mark.parametrize("key", ["northwind_happy", "helios_related_holder", "helios_declared_parent",
                                 "brightpath_gstin_typo", "lumen_wrong_jurisdiction", "cobalt_bad_documents",
                                 "apex_shared_account", "kestrel_initial", "orchard_narrative_letter"])
def test_scenario_outcome(metas, key):
    db.reset_all()
    r = run(metas[key])
    assert r["status"] == samples.expected(metas[key], llm_on=False), r["result"]["reason"]


def test_unparseable_document_is_held_not_trusted(metas):
    """Rules-only: if the bank letter can't be read we must NOT fall back to trusting the vendor's own form."""
    db.reset_all()
    r = run(metas["orchard_narrative_letter"])
    assert "BANK_HOLDER_UNREAD" in codes(r, {"review"})


def test_happy_path_is_clean(metas):
    db.reset_all()
    r = run(metas["northwind_happy"])
    assert codes(r, {"action", "review", "critical"}) == set()
    assert r["result"]["vendor_id"]                       # written to vendor master
    assert "approved" in r["result"]["email"]["subject"]


def test_edge_bank_holder_related(metas):
    db.reset_all()
    r = run(metas["helios_related_holder"])
    assert "BANK_HOLDER_RELATED" in codes(r)
    assert any("third-party payment authorisation" in q for q in r["result"]["requests"])


def test_edge_tax_typo_vs_jurisdiction(metas):
    db.reset_all()
    typo = run(metas["brightpath_gstin_typo"])
    assert "TAX_CHECKSUM" in codes(typo) and "TAX_JURISDICTION_MISMATCH" not in codes(typo)
    assert any("certificate shows" in q for q in typo["result"]["requests"])
    juris = run(metas["lumen_wrong_jurisdiction"])
    assert {"TAX_JURISDICTION_MISMATCH", "IBAN_COUNTRY_MISMATCH"} <= codes(juris)


def test_edge_wrong_and_expired_documents(metas):
    db.reset_all()
    r = run(metas["cobalt_bad_documents"])
    assert {"DOC_WRONG_COMPANY", "INSURANCE_EXPIRED"} <= codes(r)
    assert "TAX_DOC_MISMATCH" not in codes(r)            # not double-counted
    assert len(r["result"]["requests"]) == 2


def test_edge_shared_bank_account_rejected_without_tipping_off(metas):
    db.reset_all()
    r = run(metas["apex_shared_account"])
    assert "BANK_ACCOUNT_IN_USE" in codes(r, {"critical"})
    assert "Pinnacle" not in r["result"]["email"]["body"]   # never explain fraud rules to the counter-party


def test_edge_resubmission_fixed_then_approved(metas):
    db.reset_all()
    first = run(metas["kestrel_initial"])
    second = run(metas["kestrel_resubmit_fixed"])
    assert first["status"] == "PENDING" and second["status"] == "APPROVED"
    assert second["previous_run_id"] == first["id"]
    assert len(second["result"]["resolved"]) == 2
    assert db.get_run(first["id"])["superseded_by"] == second["id"]
    assert "INSURANCE_EXPIRING" in codes(second)          # approved with a condition


def test_edge_resubmission_hijacked_rejected(metas):
    db.reset_all()
    first = run(metas["kestrel_initial"])
    r = run(metas["kestrel_resubmit_hijacked"])
    assert r["status"] == "REJECTED"
    assert {"BANK_CHANGED_UNPROMPTED", "CONTACT_DOMAIN_CHANGED", "BEC_PATTERN"} <= codes(r)
    # the email goes to the contact we already trusted, not the new gmail address
    assert r["result"]["email"]["to"] == first["submission"]["contact_email"]


def test_duplicate_vendor_rejected(metas):
    db.reset_all()
    run(metas["northwind_happy"])
    again = run(metas["northwind_happy"])
    assert "DUPLICATE_VENDOR" in codes(again) and again["status"] == "REJECTED"
    assert "already registered" in again["result"]["email"]["subject"]


def test_decision_is_pure_function_of_findings():
    F = pipeline.Finding
    assert pipeline.decide([F("A", "pass", "")])["status"] == "APPROVED"
    assert pipeline.decide([F("A", "action", "")])["status"] == "PENDING"
    assert pipeline.decide([F("A", "critical", "")])["status"] == "REJECTED"
    # three review flags compound past the threshold
    assert pipeline.decide([F("A", "review", "")] * 3)["status"] == "REJECTED"


# ------------------------------------------------------------------ contact email
def _kestrel_with_contact(metas, email):
    m = metas["kestrel_resubmit_fixed"]
    sub = samples.to_submission(m)
    sub.update(contact_name="John Doe", contact_email=email, website="", previous_run_id="")
    db.reset_all()
    rid = "E-" + uuid.uuid4().hex[:6]
    db.create_run(rid, sub, "test")
    asyncio.run(pipeline.run_pipeline(rid, sub, delay=0))
    r = db.get_run(rid)
    return r, {f["code"]: f["severity"] for f in r["result"]["findings"]}


def test_contact_email_on_a_fake_domain_holds_the_case(metas):
    r, codes = _kestrel_with_contact(metas, "jondoe@gmail.vo")
    assert r["status"] == "PENDING" and codes["BAD_EMAIL"] == "action"
    assert "phone" in (r["result"]["email"]["routing_note"] or "")


def test_lookalike_free_mail_goes_to_review(metas):
    r, codes = _kestrel_with_contact(metas, "jondoe@gmai1.com")
    assert r["status"] == "PENDING" and codes["EMAIL_LOOKALIKE"] == "review"


def test_genuine_free_mail_alone_is_only_a_note(metas):
    r, codes = _kestrel_with_contact(metas, "jondoe@gmail.com")
    assert r["status"] == "APPROVED" and codes["FREE_EMAIL"] == "info"
