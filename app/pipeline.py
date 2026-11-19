"""The onboarding pipeline. Each stage appends Findings; the decision is a pure function of the findings."""
from __future__ import annotations

import asyncio
import re
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date

from . import ai, bus, comms, config, db, documents, llm, rules
from .validators import bank, emails, names, tax

STAGES = [
    ("intake", "Intake & normalisation", "Clean the submission, detect resubmissions"),
    ("completeness", "Completeness check", "Every required field present and well-formed"),
    ("documents", "Document intelligence", "Read each PDF, identify it, extract its fields"),
    ("tax", "Tax ID verification", "Country format, checksum, cross-check with certificate"),
    ("bank", "Bank verification", "Account validity and who actually owns the account"),
    ("validity", "Document validity", "Right company, not expired, sufficient cover"),
    ("crossref", "Cross-reference & fraud screen", "Vendor master, history, resubmission changes"),
    ("ai_review", "AI second look", "AI reads the documents for anything the rules missed — notes only, never changes the decision"),
    ("decision", "Decision", "Deterministic rules → approved / pending / rejected"),
    ("communicate", "Vendor communication", "Tell the vendor exactly what is needed"),
]
STAGE_TITLES = {s[0]: s[1] for s in STAGES}


@dataclass
class Finding:
    code: str
    severity: str  # pass | info | action | review | critical
    title: str
    detail: str = ""
    request: str | None = None  # vendor-facing ask, verbatim into the email
    evidence: dict = field(default_factory=dict)
    stage: str = ""
    weight: int | None = None

    def risk(self) -> int:
        return self.weight if self.weight is not None else rules.SEVERITY_WEIGHT[self.severity]


class Run:
    def __init__(self, run_id: str, sub: dict):
        self.id = run_id
        self.sub = sub
        self.findings: list[Finding] = []
        self.seq = 0
        self.docs: dict[str, dict] = {}
        self.llm_used: list[str] = []
        self.doc_texts: dict[str, str] = {}
        self.prior: dict | None = None
        self.stage = ""
        self.started = time.perf_counter()

    def emit(self, state: str, data: dict | None = None, stage: str | None = None):
        ev = db.add_event(self.id, self.seq, stage or self.stage, state, data or {})
        self.seq += 1
        bus.publish(self.id, ev)

    def log(self, msg: str):
        self.emit("log", {"message": msg})

    def add(self, code, severity, title, detail="", request=None, evidence=None, weight=None) -> Finding:
        f = Finding(code, severity, title, detail, request, evidence or {}, self.stage, weight)
        self.findings.append(f)
        self.emit("finding", asdict(f))
        return f

    def stage_findings(self, stage):
        return [f for f in self.findings if f.stage == stage]


# ====================================================================== stages
def s_intake(r: Run):
    s = r.sub
    for k, v in list(s.items()):
        if isinstance(v, str):
            s[k] = re.sub(r"\s+", " ", v).strip()
    raw_country = s.get("country", "")
    s["country"] = rules.COUNTRY_ALIASES.get(raw_country.lower(), raw_country.upper()[:2] if raw_country else "")
    if raw_country and s["country"] != raw_country:
        r.log(f"Country “{raw_country}” normalised to {s['country']}")
    s["contact_email"] = (s.get("contact_email") or "").lower()
    s["entity_type"] = s.get("entity_type") or "company"
    s["vendor_key"] = f"{s['country']}:{names.normalize(s.get('legal_name'))}"
    r.log(f"Vendor key {s['vendor_key']}; {len(s.get('documents', []))} document(s) attached")

    prev_id = s.get("previous_run_id")
    prior = db.get_run(prev_id) if prev_id else None
    if not prior:
        history = [h for h in db.runs_for_vendor_key(s["vendor_key"], exclude=r.id)
                   if not h.get("superseded_by") and h["status"] in ("PENDING", "REJECTED", "APPROVED")]
        prior = history[0] if history else None
    if prior and prior.get("result"):
        r.prior = prior
        s["previous_run_id"] = prior["id"]
        r.add("RESUBMISSION", "info", f"Resubmission — previous run {prior['id']} was {prior['status']}",
              f"Linked to earlier submission from {prior['created_at'][:10]}. Changes will be compared against it.",
              evidence={"previous_run_id": prior["id"], "previous_status": prior["status"]})
    db.update_run(r.id, vendor_key=s["vendor_key"], country=s["country"], previous_run_id=s.get("previous_run_id"))


def s_completeness(r: Run):
    s = r.sub
    missing = [label for k, label in rules.REQUIRED_FIELDS.items() if not s.get(k)]
    scheme = bank.BANK_SCHEME.get(s["country"]) or ("iban" if s.get("iban") else None)
    s["_bank_scheme"] = scheme
    if scheme:
        missing += [label for k, label in rules.BANK_FIELDS[scheme].items() if not s.get(k)]
    else:
        r.add("BANK_SCHEME_UNKNOWN", "review", f"No automated bank rules for country {s['country'] or '—'}",
              "Bank details will need manual verification by the payments team.")
    missing += [label for k, label in rules.COMMON_BANK_FIELDS.items() if not s.get(k)]
    for label in missing:
        r.add("MISSING_FIELD", "action", f"Missing: {label}", request=f"Please provide your {label.lower()}.",
              evidence={"field": label})
    if s.get("contact_email"):
        em = emails.check(s["contact_email"])
        if not em["syntax_ok"]:
            r.add("BAD_EMAIL", "action", "Contact email is not a valid address", evidence={"email": em["email"]},
                  request="Please provide a valid contact email address.")
        elif not em["tld_ok"]:
            hint = f" Did you mean {em['lookalike']}?" if em["lookalike"] else ""
            r.add("BAD_EMAIL", "action", f"Contact email domain {em['domain']} does not exist",
                  f"“.{em['tld']}” is not a real domain ending (checked against the IANA list), so no email can be "
                  f"delivered to {em['email']}.{hint}", evidence={"email": em["email"], "tld": em["tld"]},
                  request=f"Your contact email {em['email']} cannot receive mail: “.{em['tld']}” is not a valid domain "
                          f"ending.{hint} Please provide a working contact email address.")
    if s.get("country") and s["country"] not in rules.COUNTRIES:
        r.add("COUNTRY_UNSUPPORTED", "review", f"Country {s['country']} is outside the standard onboarding rules",
              "Tax and banking checks for this country need a manual review.")
    if not missing:
        r.add("FIELDS_COMPLETE", "pass", "All required fields present")


async def s_documents(r: Run):
    s, country = r.sub, r.sub["country"]
    uploads = s.get("documents", [])
    for d in uploads:
        slot_name = documents.DOC_TYPES.get(d["slot"], d["slot"])
        r.log(f"Reading {d['filename']} (uploaded as {slot_name})")
        text = documents.extract_text(d["path"])
        if len(text) < 40:
            r.add("DOC_UNREADABLE", "action", f"Could not read {d['filename']}",
                  "No machine-readable text (likely a scanned image or a corrupted file).",
                  request=f"The file “{d['filename']}” could not be read. Please upload a text-based PDF or a clearer scan "
                          f"of your {slot_name.lower()}.", evidence={"file": d["filename"], "slot": d["slot"]})
            continue
        r.doc_texts[d["filename"]] = text
        cls = documents.classify(text)
        doc_type, source = cls["type"], "keywords"
        fields = {}
        if doc_type.startswith("uncertain:") or doc_type == "unknown":
            guess = doc_type.split(":")[-1]
            ai = await llm.classify_and_extract(text, guess) if llm.enabled() else None
            if ai and ai["type"] in documents.DOC_TYPES:
                doc_type, source, fields = ai["type"], "llm", ai["fields"]
                r.llm_used.append(f"classified {d['filename']}")
                r.log(f"Keyword classifier unsure; LLM identified it as {documents.DOC_TYPES[doc_type]}")
            elif guess != "unknown":
                doc_type = guess
                r.log(f"Low-confidence classification for {d['filename']}: best guess {documents.DOC_TYPES[guess]}")
        if doc_type not in documents.DOC_TYPES:
            r.add("DOC_UNRECOGNISED", "action", f"{d['filename']} is not a document we recognise",
                  request=f"The file “{d['filename']}” does not look like a {slot_name.lower()}. Please upload the correct document.",
                  evidence={"file": d["filename"], "slot": d["slot"]})
            continue

        regex_fields = documents.extract_fields(doc_type, text, country)
        field_source = {k: "regex" for k in regex_fields}
        expected = llm.DOC_FIELDS[doc_type]
        merged = {**fields, **regex_fields}  # deterministic extraction wins on conflict
        for k in fields:
            field_source.setdefault(k, "llm")
        gaps = [k for k in expected if k not in merged and k in ("entity_name", "tax_id", "iban", "account_number",
                                                                 "expiry_date", "coverage_raw", "letter_date")]
        if gaps and llm.enabled() and source != "llm":
            ai = await llm.classify_and_extract(text, doc_type)
            if ai:
                for k, v in ai["fields"].items():
                    if k not in merged:
                        merged[k], field_source[k] = v, "llm"
                filled = [k for k in gaps if k in merged]
                if filled:
                    r.llm_used.append(f"extracted {', '.join(filled)} from {d['filename']}")
                    r.log(f"LLM filled {', '.join(filled)} from {d['filename']}")
        final = documents.finalize_fields(doc_type, merged, country)
        info = {"filename": d["filename"], "slot": d["slot"], "path": d["path"], "type": doc_type,
                "classified_by": source, "confidence": cls["confidence"], "fields": final, "field_source": field_source}
        r.emit("document", {k: v for k, v in info.items() if k != "path"})

        if doc_type != d["slot"] and d["slot"] in documents.DOC_TYPES:
            slot_has_correct = any(x["slot"] == doc_type for x in uploads if x is not d)
            if doc_type in r.docs or slot_has_correct:
                r.add("DOC_WRONG_SLOT", "action", f"Wrong document uploaded as {slot_name}",
                      f"{d['filename']} is a {documents.DOC_TYPES[doc_type]}, not a {slot_name}.",
                      request=f"The file uploaded as your {slot_name.lower()} (“{d['filename']}”) is actually a "
                              f"{documents.DOC_TYPES[doc_type].lower()}. Please upload your {slot_name.lower()}.",
                      evidence={"file": d["filename"], "slot": d["slot"], "uploaded_as": slot_name,
                                "detected": documents.DOC_TYPES[doc_type]})
                continue
            r.add("DOC_RESLOTTED", "info", f"{d['filename']} re-filed as {documents.DOC_TYPES[doc_type]}",
                  f"Uploaded under “{slot_name}” but its content is a {documents.DOC_TYPES[doc_type]}; used where it belongs.")
        if doc_type in r.docs:
            r.log(f"Second {documents.DOC_TYPES[doc_type]} received; keeping the first")
            continue
        r.docs[doc_type] = info

    # A slot whose upload was unreadable / wrong has already produced a specific request — don't ask twice.
    already_asked = {f.evidence.get("slot") for f in r.stage_findings("documents")
                     if f.code in ("DOC_WRONG_SLOT", "DOC_UNREADABLE", "DOC_UNRECOGNISED")}
    for t in rules.REQUIRED_DOCS:
        if t in r.docs or t in already_asked:
            continue
        name = rules.TAX_DOC_NAME.get(s["country"], "tax registration certificate") if t == "tax_certificate" \
            else documents.DOC_TYPES[t].lower()
        r.add("MISSING_DOC", "action", f"Missing document: {documents.DOC_TYPES[t]}",
              request=f"Please upload your {name}.", evidence={"document": documents.DOC_TYPES[t], "slot": t})
    for t in rules.RECOMMENDED_DOCS:
        if t not in r.docs:
            r.add("RECOMMENDED_DOC", "info", f"Not provided (optional): {documents.DOC_TYPES[t]}")
    if all(t in r.docs for t in rules.REQUIRED_DOCS):
        r.add("DOCS_COMPLETE", "pass", f"All {len(rules.REQUIRED_DOCS)} required documents identified",
              evidence={documents.DOC_TYPES[k]: v["filename"] for k, v in r.docs.items()})


_FORMAT_HINT = {"US": "NN-NNNNNNN (9 digits)", "GB": "GB followed by 9 digits", "DE": "DE followed by 9 digits",
                "IN": "15 characters, e.g. 27AAPFU0939F1ZV"}


def _tid_key(t: str) -> str:
    return tax.clean(t).removeprefix("GB")


def s_tax(r: Run):
    s = r.sub
    country, tid = s["country"], s.get("tax_id")
    if not tid:
        r.log("No tax ID on form — already requested")
        return
    res = tax.validate(country, tid, s["entity_type"] == "company")
    s["_tax"] = res
    label = res["label"]
    cert = r.docs.get("tax_certificate", {}).get("fields", {})
    cert_tid = tax.clean(cert.get("tax_id")) if cert.get("tax_id") else None
    if cert_tid and cert.get("entity_name") and not names.is_match(names.compare(cert["entity_name"], s.get("legal_name"))["verdict"]):
        r.log(f"Tax certificate is issued to “{cert['entity_name']}” — not used for cross-checking (flagged in validity stage)")
        cert_tid = None
    r.log(f"Validating {label} {res['normalized']} for {rules.COUNTRIES.get(country, country)}")

    if res["problem"] == "unsupported_country":
        r.add("TAX_UNVERIFIABLE", "review", f"No automated tax ID rules for {country}",
              "Tax registration must be checked manually against the national registry.")
    elif res["problem"] == "jurisdiction":
        other = ", ".join(rules.COUNTRIES.get(c, c) for c in res["detected_countries"])
        r.add("TAX_JURISDICTION_MISMATCH", "review", f"Tax ID belongs to {other}, vendor is in {rules.COUNTRIES.get(country, country)}",
              f"{res['normalized']} is a valid-looking {other} tax ID, not a {label}. This is not a typo: either the vendor "
              f"registered the wrong country, or is invoicing through a foreign entity.",
              request=f"The tax ID provided ({res['normalized']}) is registered in {other}. Please provide your "
                      f"{rules.COUNTRIES.get(country, country)} {label}, or tell us if you are contracting through your {other} entity.",
              evidence={"tax_id": res["normalized"], "claimed_country": country, "id_matches": res["detected_countries"]})
    elif res["problem"] == "format":
        r.add("TAX_FORMAT", "action", f"Tax ID is not a valid {label} format",
              f"Expected {_FORMAT_HINT.get(country, label)}; got “{tid}”.",
              request=f"Your {label} “{tid}” is not in the expected format ({_FORMAT_HINT.get(country)}). Please check and resend it.",
              evidence={"tax_id": tid})
    elif res["problem"] == "checksum":
        hint = ""
        if cert_tid and tax.validate(country, cert_tid)["valid"]:
            dist = tax.edit_distance(cert_tid, res["normalized"])
            if dist <= 2:
                hint = f" The certificate shows {cert_tid} ({dist} character(s) different), which is valid — almost certainly a typing error."
        notes = (" " + "; ".join(res["notes"])) if res["notes"] else ""
        r.add("TAX_CHECKSUM", "action", f"{label} fails its check-digit test — likely typo",
              f"{res['normalized']} has the right shape but an invalid check digit.{notes}{hint}",
              request=f"The {label} on your form ({res['normalized']}) fails validation"
                      + (f"; your certificate shows {cert_tid}. Please confirm which is correct." if hint else ". Please double-check and resend it."),
              evidence={"form": res["normalized"], "certificate": cert_tid})
    else:
        r.add("TAX_VALID", "pass", f"Valid {label}: {res['normalized']}",
              "Format and check digit verified." if country != "US" else "Format and IRS prefix verified.")
        if res.get("pan_individual"):
            r.add("TAX_INDIVIDUAL_PAN", "review", "GSTIN is linked to an individual, not a company",
                  "The PAN embedded in the GSTIN is an individual's (4th character ‘P’). The vendor says it is a company.",
                  evidence={"pan": res.get("pan")})
        if cert_tid and _tid_key(cert_tid) != _tid_key(res["normalized"]):
            r.add("TAX_DOC_MISMATCH", "review", "Tax ID on form ≠ tax ID on certificate",
                  f"Form: {res['normalized']} · certificate: {cert_tid}. Both cannot be right for one company.",
                  request="The tax ID on your form does not match the one on your tax certificate. Please confirm the correct "
                          "number and upload the matching certificate.",
                  evidence={"form": res["normalized"], "certificate": cert_tid})
        elif cert_tid:
            r.add("TAX_DOC_MATCH", "pass", "Tax ID matches the certificate")


def _same_account(form: dict, letter: dict, scheme: str) -> bool | None:
    if scheme == "iban":
        a, b = bank.clean(form.get("iban")), bank.clean(letter.get("iban"))
    else:
        a, b = bank.clean(form.get("account_number")), bank.clean(letter.get("account_number"))
    if not a or not b:
        return None
    return a == b


def s_bank(r: Run):
    s, country = r.sub, r.sub["country"]
    scheme = s.get("_bank_scheme")
    ok = True
    if scheme == "iban" and s.get("iban"):
        iv = bank.iban_validate(s["iban"])
        r.log(f"IBAN {bank.mask(s['iban'])}: {'valid' if iv['valid'] else iv['problem']}")
        if not iv["valid"]:
            ok = False
            why = {"checksum": "its check digits are wrong", "length": f"it should be {iv.get('expected_length')} characters",
                   "format": "it is not in IBAN format"}.get(iv["problem"], iv["problem"])
            r.add("IBAN_INVALID", "action", f"IBAN is invalid ({iv['problem']})", f"The IBAN fails validation: {why}.",
                  request=f"Your IBAN ending {bank.mask(s['iban'])} is not valid ({why}). Please check and resend it.")
        elif iv["country"] != country:
            r.add("IBAN_COUNTRY_MISMATCH", "review", f"Account held in {iv['country']}, vendor registered in {country}",
                  "Cross-border payment destinations are a common feature of invoice-redirection fraud and need a reason.",
                  request=f"Your bank account is held in {rules.COUNTRIES.get(iv['country'], iv['country'])}, but your company "
                          f"is registered in {rules.COUNTRIES.get(country, country)}. Please explain or provide a domestic account.",
                  evidence={"iban_country": iv["country"], "vendor_country": country})
        if s.get("bic"):
            bv = bank.bic_validate(s["bic"])
            if not bv["valid"]:
                r.add("BIC_INVALID", "action", "BIC / SWIFT code is invalid", request="Please check your BIC / SWIFT code.")
            elif iv.get("country") and bv["country"] != iv["country"]:
                r.add("BIC_IBAN_MISMATCH", "review", "BIC country does not match IBAN country",
                      f"BIC is for {bv['country']}, IBAN is {iv['country']}.", evidence={"bic": bv["normalized"]})
    elif scheme == "aba":
        av = bank.aba_validate(s.get("routing_number"))
        if s.get("routing_number") and not av["valid"]:
            ok = False
            r.add("ROUTING_INVALID", "action", f"ABA routing number invalid ({av['problem']})",
                  request=f"The routing number {s['routing_number']} is not a valid US ABA number. Please check it.")
        acv = bank.account_number_validate(s.get("account_number"), country)
        if s.get("account_number") and not acv["valid"]:
            ok = False
            r.add("ACCOUNT_INVALID", "action", "Account number format invalid", f"Expected {acv.get('expected')}.",
                  request="Your bank account number does not look right. Please check it.")
    elif scheme == "ifsc":
        fv = bank.ifsc_validate(s.get("ifsc"))
        if s.get("ifsc") and not fv["valid"]:
            ok = False
            r.add("IFSC_INVALID", "action", "IFSC code invalid", request="Your IFSC code is not valid. Please check it.")
        acv = bank.account_number_validate(s.get("account_number"), country)
        if s.get("account_number") and not acv["valid"]:
            ok = False
            r.add("ACCOUNT_INVALID", "action", "Account number format invalid", f"Expected {acv.get('expected')}.",
                  request="Your bank account number does not look right. Please check it.")
    if ok and scheme and all(s.get(k) for k in rules.BANK_FIELDS[scheme]):
        r.add("BANK_FORMAT_OK", "pass", "Bank identifiers pass format & checksum validation")

    letter = r.docs.get("bank_letter", {}).get("fields", {})
    has_letter = "bank_letter" in r.docs
    if has_letter and scheme:
        same = _same_account(s, letter, scheme)
        if same is False:
            shown = bank.mask(letter.get("iban") or letter.get("account_number"))
            r.add("BANK_LETTER_ACCOUNT_MISMATCH", "review", "Bank letter is for a different account",
                  f"Form account {bank.mask(s.get('iban') or s.get('account_number'))}, letter shows {shown}.",
                  request="The account on your bank letter does not match the account on your form. Please upload a bank "
                          "letter for the account you want to be paid into.", evidence={"letter_account": shown})
        elif same:
            r.add("BANK_LETTER_ACCOUNT_MATCH", "pass", "Bank letter confirms the same account number")

    if has_letter and not letter.get("entity_name"):  # supplied but unreadable: never silently trust the form
        r.add("BANK_HOLDER_UNREAD", "review", "Could not read the account holder on the bank letter",
              "Falling back to the name typed on the form, which the vendor controls — a reviewer should confirm the letter.")
    holder = letter.get("entity_name") or s.get("account_holder")
    if not holder:
        return
    src = "bank letter" if letter.get("entity_name") else "form"
    legal = s.get("legal_name")
    candidates = [("legal name", legal), ("trading name", s.get("trading_name"))]
    best = max((names.compare(holder, n) | {"against": lbl} for lbl, n in candidates if n), key=lambda c: c["score"],
               default=names.compare(holder, legal))
    ev = {"account_holder": holder, "vendor": legal, "source": src, "match": best["verdict"], "similarity": best["score"]}
    r.log(f"Account holder on {src}: “{holder}” vs “{legal}” → {best['verdict']}")
    if names.is_match(best["verdict"]):
        sev = "pass" if best["verdict"] != "near" else "info"
        r.add("BANK_HOLDER_MATCH", sev, f"Account holder matches the vendor ({best['verdict']})", best["reason"], evidence=ev)
        return
    parent = s.get("parent_company")
    if parent and names.is_match(names.compare(holder, parent)["verdict"]):
        r.add("BANK_HOLDER_DECLARED_PARENT", "info", "Account held by the parent company declared on the form",
              f"“{holder}” matches the declared parent “{parent}”. Paying a declared group treasury account is accepted; noted for audit.",
              evidence=ev)
        return
    if best["verdict"] == "related":
        r.add("BANK_HOLDER_RELATED", "review", "Account holder is a different but related-looking entity",
              f"“{holder}” vs “{legal}”: {best['reason']}. Paying a third party needs written authorisation.",
              request=f"Your bank letter names “{holder}” as the account holder, not “{legal}”. If payments should go to a "
                      "related company, please send a signed third-party payment authorisation on company letterhead (or "
                      "declare the parent company on the form), or provide an account held in your own name.",
              evidence=ev)
    else:
        r.add("BANK_HOLDER_MISMATCH", "review", "Account holder is an unrelated name",
              f"“{holder}” has no meaningful overlap with “{legal}” ({best['reason']}). Paying an unrelated party's account is "
              "the core pattern of payment fraud.",
              request=f"The account holder on your bank details (“{holder}”) does not match your company name. Please provide "
                      "an account held in your company's name.", evidence=ev, weight=50)


def s_validity(r: Run):
    s, country = r.sub, r.sub["country"]
    legal = s.get("legal_name")
    today = documents.today()
    for t in ("tax_certificate", "insurance_certificate", "incorporation_certificate"):
        d = r.docs.get(t)
        if not d:
            continue
        nm = d["fields"].get("entity_name")
        doc_label = documents.DOC_TYPES[t]
        if not nm:
            r.add("DOC_NAME_UNREAD", "info", f"Could not read the company name on the {doc_label.lower()}",
                  "Flagged for the reviewer to eyeball.")
            continue
        cmp = max((names.compare(nm, n) for n in (legal, s.get("trading_name")) if n), key=lambda c: c["score"])
        if names.is_match(cmp["verdict"]):
            r.add("DOC_NAME_MATCH", "pass", f"{doc_label} is issued to {nm}")
        else:
            req_name = rules.TAX_DOC_NAME.get(country, doc_label) if t == "tax_certificate" else doc_label.lower()
            r.add("DOC_WRONG_COMPANY", "action", f"{doc_label} belongs to a different company",
                  f"Issued to “{nm}”, not “{legal}” ({cmp['reason']}).",
                  request=f"The {doc_label.lower()} you sent (“{d['filename']}”) is issued to “{nm}”. Please upload the "
                          f"{req_name} issued to {legal}.", evidence={"document_name": nm, "vendor": legal, "file": d["filename"]})

    ins = r.docs.get("insurance_certificate", {}).get("fields")
    if ins:
        exp = ins.get("expiry_date_parsed")
        if not exp:
            r.add("INSURANCE_NO_EXPIRY", "action", "Insurance certificate has no readable expiry date",
                  request="Please upload a certificate of insurance that shows the policy period / expiry date.")
        else:
            days = (date.fromisoformat(exp) - today).days
            if days < 0:
                r.add("INSURANCE_EXPIRED", "action", f"Insurance expired {-days} days ago ({exp})",
                      request=f"Your certificate of insurance expired on {exp}. Please upload your current certificate.",
                      evidence={"expiry": exp})
            elif days <= rules.INSURANCE_EXPIRY_WARNING_DAYS:
                r.add("INSURANCE_EXPIRING", "info", f"Insurance expires in {days} days ({exp})",
                      "Approved, with an automatic reminder to collect the renewal certificate.", evidence={"expiry": exp})
            else:
                r.add("INSURANCE_VALID", "pass", f"Insurance valid until {exp}")
        cur = ins.get("coverage_currency") or rules.CURRENCY.get(country, "USD")
        amt = ins.get("coverage_amount")
        minimum = rules.MIN_LIABILITY_COVER.get(cur)
        if amt and minimum:
            if amt < minimum:
                r.add("INSURANCE_COVER_LOW", "action", f"Liability cover {cur} {amt:,.0f} below minimum {cur} {minimum:,.0f}",
                      request=f"Our minimum general-liability cover is {cur} {minimum:,.0f}; your certificate shows {cur} {amt:,.0f}. "
                              "Please provide evidence of sufficient cover.", evidence={"cover": amt, "minimum": minimum})
            else:
                r.add("INSURANCE_COVER_OK", "pass", f"Liability cover {cur} {amt:,.0f} meets minimum")
        elif not amt:
            r.add("INSURANCE_COVER_UNREAD", "info", "Coverage amount could not be read", "Reviewer to confirm limit.")

    letter = r.docs.get("bank_letter", {}).get("fields")
    if letter and letter.get("letter_date_parsed"):
        age = (today - date.fromisoformat(letter["letter_date_parsed"])).days
        if age > rules.BANK_LETTER_MAX_AGE_DAYS:
            r.add("BANK_LETTER_STALE", "action", f"Bank letter is {age // 30} months old",
                  request="Your bank confirmation letter is more than 6 months old. Please provide one dated within the last 6 months.")
    for t, d in r.docs.items():
        for k in ("issue_date_parsed", "letter_date_parsed", "incorporation_date_parsed"):
            v = d["fields"].get(k)
            if v and date.fromisoformat(v) > today:
                r.add("DOC_FUTURE_DATED", "review", f"{documents.DOC_TYPES[t]} is dated in the future ({v})",
                      "Genuine documents are not dated in the future; possible alteration.", evidence={"date": v})


def s_crossref(r: Run):
    s = r.sub
    fp = bank.account_fingerprint(s["country"], s.get("iban", ""), s.get("routing_number", ""), s.get("ifsc", ""),
                                  s.get("account_number", ""))
    s["_account_fp"] = fp
    tax_norm = (s.get("_tax") or {}).get("normalized") or tax.clean(s.get("tax_id"))
    me = names.normalize(s.get("legal_name"))
    dup = None
    r.log(f"Screening against {len(db.list_vendors())} vendors in the vendor master")
    if fp:
        for v in db.find_vendor_by_account(fp):
            if names.normalize(v["legal_name"]) == me or (tax_norm and v["tax_id"] == tax_norm):
                dup = v
            else:
                r.add("BANK_ACCOUNT_IN_USE", "critical", f"Bank account already belongs to approved vendor {v['legal_name']}",
                      f"Account {v['account_masked']} is on file for {v['id']} “{v['legal_name']}” ({v['country']}). Two unrelated "
                      "vendors sharing one payment account is a strong fraud indicator.",
                      evidence={"vendor_id": v["id"], "vendor": v["legal_name"], "account": v["account_masked"]})
    if tax_norm:
        for v in db.find_vendor_by_tax(tax_norm):
            if names.normalize(v["legal_name"]) == me:
                dup = dup or v
            elif not any(f.code == "BANK_ACCOUNT_IN_USE" for f in r.findings):
                r.add("TAX_ID_IN_USE", "review", f"Tax ID already registered to {v['legal_name']}",
                      f"{v['id']} uses the same tax ID. Could be a rename or a group entity — needs a reviewer.",
                      evidence={"vendor_id": v["id"], "vendor": v["legal_name"]}, weight=50)
    if dup:
        r.add("DUPLICATE_VENDOR", "critical", f"Already onboarded as {dup['id']}",
              f"{dup['legal_name']} was approved on {dup['approved_at'][:10]}. A second record would split payment history.",
              evidence={"vendor_id": dup["id"]})

    em = emails.check(s.get("contact_email"))
    domain = em["domain"]
    if em["free"]:
        r.add("FREE_EMAIL", "info", f"Contact uses a free email provider ({domain})",
              "Weak signal on its own: many small businesses use one. Noted for the reviewer; it escalates only "
              "together with other signals (e.g. a changed bank account).")
    elif em["lookalike"] and em["tld_ok"]:
        r.add("EMAIL_LOOKALIKE", "review", f"Contact email domain {domain} imitates {em['lookalike']}",
              f"{domain} is not {em['lookalike']} but is one typo away from it. Look-alike domains are a common way to "
              "impersonate a trusted sender, so confirm this contact on an independently sourced phone number.",
              evidence={"domain": domain, "imitates": em["lookalike"]})
    site = re.sub(r"^(https?://)?(www\.)?", "", (s.get("website") or "").lower()).split("/")[0]
    business = domain and em["tld_ok"] and not em["free"] and not em["lookalike"]
    if business and site and not (domain == site or domain.endswith("." + site) or site.endswith("." + domain)):
        r.add("EMAIL_SITE_MISMATCH", "info", f"Email domain {domain} differs from website {site}")
    elif business and not site and not emails.related_to_company(
            domain, [s.get("legal_name"), s.get("trading_name"), s.get("parent_company")]):
        r.add("EMAIL_DOMAIN_UNRELATED", "info", f"Email domain {domain} doesn't resemble the company name",
              "Companies often use abbreviations or group domains, so this is a note for the reviewer, not a blocker.",
              evidence={"domain": domain})

    p = r.prior
    if p:
        psub, pres = p["submission"], p.get("result") or {}
        prev_findings = pres.get("findings", [])
        now_codes = {(f.code, f.title) for f in r.findings}
        open_before = [f for f in prev_findings if f["severity"] in ("action", "review")]
        resolved = [f["title"] for f in open_before if (f["code"], f["title"]) not in now_codes]
        s["_resolved"] = resolved
        if resolved:
            r.add("RESOLVED_ITEMS", "pass", f"{len(resolved)} item(s) resolved since the last submission",
                  "; ".join(resolved), evidence={"resolved": resolved})
        prev_fp = (pres.get("account_fp") or bank.account_fingerprint(
            psub.get("country", ""), psub.get("iban", ""), psub.get("routing_number", ""), psub.get("ifsc", ""),
            psub.get("account_number", "")))
        bank_was_asked = any(f["stage"] == "bank" and f["severity"] in ("action", "review") for f in prev_findings) or \
            any(f["code"] in ("MISSING_FIELD",) and any(w in f["title"].lower() for w in ("iban", "account", "routing", "ifsc", "bic"))
                for f in prev_findings)
        changed_bank = prev_fp and fp and prev_fp != fp
        prev_domain = (psub.get("contact_email") or "").split("@")[-1]
        changed_domain = prev_domain and domain and prev_domain != domain
        if changed_bank and not bank_was_asked:
            r.add("BANK_CHANGED_UNPROMPTED", "review", "Bank details changed between submissions — nobody asked for that",
                  f"Previous account {bank.mask(prev_fp)} → now {bank.mask(fp)}. We only requested: "
                  f"{'; '.join(f['title'] for f in open_before) or 'nothing bank-related'}.",
                  request="We noticed your bank details changed since your last submission. For your security we will confirm "
                          "the change by phone with the contact on your original submission before proceeding.",
                  evidence={"previous": bank.mask(prev_fp), "current": bank.mask(fp)}, weight=40)
        elif changed_bank:
            r.add("BANK_CHANGED_AS_REQUESTED", "info", "Bank details updated in response to our request")
        if changed_domain:
            sev_note = " (now a free email provider)" if em["free"] else ""
            r.add("CONTACT_DOMAIN_CHANGED", "review", f"Contact email moved from @{prev_domain} to @{domain}{sev_note}",
                  "A change of contact domain mid-onboarding is a common sign of a hijacked or spoofed conversation.",
                  evidence={"previous": prev_domain, "current": domain})
        if changed_bank and not bank_was_asked and changed_domain:
            r.add("BEC_PATTERN", "critical", "Business-email-compromise pattern",
                  "Unrequested bank change + new contact email domain in the same resubmission. This is the textbook "
                  "invoice-redirection fraud pattern; the original contact must be called on a known number.",
                  evidence={"previous_email_domain": prev_domain, "new_email_domain": domain})
        if p["status"] == "REJECTED":
            r.add("PREVIOUSLY_REJECTED", "review", f"This vendor was rejected on {p['created_at'][:10]}",
                  pres.get("top_issue") or "", weight=40)
    if not any(f.severity in ("review", "critical") for f in r.stage_findings("crossref")):
        r.add("SCREEN_CLEAR", "pass", "No conflicts with vendor master or submission history")


AI_NOTE = "AI_OBSERVATION"


async def s_ai_review(r: Run):
    if not llm.enabled():
        r.log("AI assist is off — skipped (rule checks above are complete on their own)")
        return
    r.log(f"Asking {config.LLM_MODEL} for a second look at {len(r.doc_texts)} document(s); bank numbers masked")
    notes = await ai.observations(r.sub, r.docs, r.doc_texts, r.findings)
    r.llm_used.append(f"second look: {len(notes)} note(s)")
    for n in notes:
        r.add(AI_NOTE, "info", n["title"], n["detail"], evidence={"quote": n["quote"], "source": n["source"]})
    if not notes:
        r.log("AI found nothing beyond what the rules already checked")


def decide(findings: list[Finding]) -> dict:
    """Pure function: findings → decision. This is the whole policy.
    AI observations are excluded explicitly: they are notes for humans and can never move the status or score."""
    findings = [f for f in findings if f.code != AI_NOTE]
    risk = min(100, sum(f.risk() for f in findings))
    crit = [f for f in findings if f.severity == "critical"]
    action = [f for f in findings if f.severity == "action"]
    review = [f for f in findings if f.severity == "review"]
    if crit:
        status, why = "REJECTED", f"{len(crit)} critical issue(s): " + "; ".join(f.title for f in crit)
    elif risk >= rules.REJECT_RISK_THRESHOLD:
        status, why = "REJECTED", (f"Compounding risk {risk}/100 (threshold {rules.REJECT_RISK_THRESHOLD}) from "
                                   f"{len(review)} review flag(s) and {len(action)} open item(s)")
    elif action or review:
        status = "PENDING"
        parts = []
        if action:
            parts.append(f"{len(action)} item(s) needed from the vendor")
        if review:
            parts.append(f"{len(review)} item(s) for internal review")
        why = " and ".join(parts)
    else:
        status, why = "APPROVED", "All checks passed" + (
            f" with {sum(1 for f in findings if f.severity == 'info')} note(s)" if any(f.severity == "info" for f in findings) else "")
    owner = None
    if status == "PENDING":
        owner = "vendor" if any(f.request for f in action + review) else "procurement reviewer"
    ranked = sorted(findings, key=lambda f: (-f.risk(), f.code == "DUPLICATE_VENDOR"))  # fraud outranks duplicate
    top = next((f.title for f in ranked if f.severity in ("critical", "review", "action")), None)
    return {"status": status, "risk_score": risk, "reason": why, "waiting_on": owner, "top_issue": top}


def s_decision(r: Run) -> dict:
    d = decide(r.findings)
    r.log(f"Risk score {d['risk_score']}/100 → {d['status']}")
    return d


async def s_communicate(r: Run, d: dict) -> dict:
    s = r.sub
    email = await comms.build_email(r, d)
    r.log(f"{'LLM-worded' if email.get('llm') else 'Templated'} email to {email['to'] or '(no contact email)'}")
    if email.get("llm"):
        r.llm_used.append("worded vendor email")
    if email["to"]:
        db.add_email(r.id, email["to"], email["subject"], email["body"])
    summary = await comms.reviewer_summary(r, d)
    vendor_id = None
    if d["status"] == "APPROVED":
        vendor_id = db.add_vendor({"legal_name": s["legal_name"], "country": s["country"],
                                   "tax_id": (s.get("_tax") or {}).get("normalized"), "account_fp": s.get("_account_fp"),
                                   "account_masked": bank.mask(s.get("_account_fp")), "contact_email": s.get("contact_email"),
                                   "run_id": r.id})
        r.log(f"Vendor created in master as {vendor_id} — ready for payment")
    if r.prior and r.prior["status"] == "PENDING":
        db.update_run(r.prior["id"], superseded_by=r.id)
        r.log(f"Earlier run {r.prior['id']} marked as superseded")
    return {"email": email, "reviewer_summary": summary, "vendor_id": vendor_id}


# ====================================================================== orchestration
async def run_pipeline(run_id: str, sub: dict, delay: float | None = None):
    r = Run(run_id, sub)
    delay = config.STAGE_DELAY_MS / 1000 if delay is None else delay
    decision, comm = None, None
    try:
        for key, title, desc in STAGES:
            r.stage = key
            r.emit("start", {"title": title})
            t0 = time.perf_counter()
            await asyncio.sleep(delay)
            if key == "intake":
                s_intake(r)
            elif key == "completeness":
                s_completeness(r)
            elif key == "documents":
                await s_documents(r)
            elif key == "tax":
                s_tax(r)
            elif key == "bank":
                s_bank(r)
            elif key == "validity":
                s_validity(r)
            elif key == "crossref":
                s_crossref(r)
            elif key == "ai_review":
                await s_ai_review(r)
            elif key == "decision":
                decision = s_decision(r)
            elif key == "communicate":
                comm = await s_communicate(r, decision)
            fs = r.stage_findings(key)
            worst = max((rules.SEVERITY_WEIGHT[f.severity] for f in fs), default=0)
            verdict = "fail" if worst >= 100 else "warn" if worst > 0 else "pass"
            if key == "decision":
                verdict = {"APPROVED": "pass", "PENDING": "warn", "REJECTED": "fail"}[decision["status"]]
            r.emit("done", {"verdict": verdict, "ms": round((time.perf_counter() - t0) * 1000),
                            **({"decision": decision} if key == "decision" else {})})
        result = build_result(r, decision, comm)
        db.update_run(run_id, status=decision["status"], risk_score=decision["risk_score"], finished_at=db.now(),
                      result=result, submission=public_submission(r.sub))
        r.emit("complete", {"status": decision["status"], "risk_score": decision["risk_score"]}, stage="end")
    except Exception as e:
        traceback.print_exc()
        db.update_run(run_id, status="ERROR", finished_at=db.now(),
                      result={"error": f"{type(e).__name__}: {e}", "findings": [asdict(f) for f in r.findings]})
        r.emit("error", {"message": f"{type(e).__name__}: {e}"}, stage=r.stage)


def public_submission(s: dict) -> dict:
    return {k: v for k, v in s.items() if not k.startswith("_")}


def build_result(r: Run, d: dict, comm: dict) -> dict:
    counts = {k: sum(1 for f in r.findings if f.severity == k) for k in ("pass", "info", "action", "review", "critical")}
    requests = list(dict.fromkeys(f.request for f in r.findings if f.request and f.severity in ("action", "review")))
    return {
        **d,
        "findings": [asdict(f) for f in r.findings],
        "counts": counts,
        "requests": requests,
        "documents": {t: {k: v for k, v in info.items() if k != "path"} for t, info in r.docs.items()},
        "email": comm["email"],
        "reviewer_summary": comm["reviewer_summary"],
        "vendor_id": comm["vendor_id"],
        "account_fp": r.sub.get("_account_fp"),
        "tax_id_normalized": (r.sub.get("_tax") or {}).get("normalized"),
        "resolved": r.sub.get("_resolved", []),
        "previous_run_id": r.sub.get("previous_run_id"),
        "llm_used": r.llm_used,
        "llm_model": config.LLM_MODEL if config.LLM_ENABLED else None,
        "duration_ms": round((time.perf_counter() - r.started) * 1000),
    }
