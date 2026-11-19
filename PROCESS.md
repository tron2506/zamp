# Vendor Onboarding — Process Map

**Input:** a vendor submission = web form fields (company, contact, tax, banking) + up to 4 PDF documents.
**Output:** one of `APPROVED` · `PENDING` · `REJECTED`, with every finding and its reasoning visible, a
vendor-facing message listing exactly what is needed (for anything not approved), and an internal reviewer summary.

The **decision is 100% deterministic** (rules + checksums + fuzzy-name scoring). The LLM is used only where
text is messy and human-like: (1) pulling fields out of unstructured PDF text when the regex extractors
come up empty, (2) classifying a document the keyword classifier is unsure about, (3) wording the vendor
email and reviewer summary. Any value the LLM extracts must appear literally in the document text or it is
discarded. If a document can't be read at all, the process never falls back to trusting the vendor's own form
entry; it holds the case for review instead. The LLM never decides, and the list of requested items in the email is
inserted verbatim by code. With no API key configured everything falls back to deterministic logic.

---

## Stages

| # | Stage | Input | What happens | Can produce |
|---|-------|-------|--------------|-------------|
| 1 | **Intake & normalise** | raw form + files | Trim/case-fold, map country to ISO-2, strip spaces from IBAN/tax ID, detect resubmission (same tax ID / prior run id) | – |
| 2 | **Completeness** | normalised form | Required fields per country (e.g. IBAN+BIC for GB/DE, routing+account for US, IFSC+account for IN). Required docs: tax registration, bank letter, insurance certificate. Incorporation cert recommended. | `action` per missing item |
| 3 | **Document intelligence** | PDFs | Extract text (pypdf) → classify (keyword scoring; LLM if ambiguous) → extract fields (regex label variants; LLM fills gaps). Unreadable/scanned PDFs flagged. Wrong document in a slot detected. | `action` (wrong/unreadable doc) |
| 4 | **Tax ID verification** | tax ID + country + tax doc | Country format + checksum (US EIN prefix table, GB VAT mod-97, DE USt-IdNr ISO 7064, IN GSTIN base-36 + embedded PAN). Detect which *other* country's format it matches. Cross-check against tax certificate. | `action` (typo), `review` (jurisdiction mismatch, form≠doc) |
| 5 | **Bank verification** | bank fields + bank letter | IBAN mod-97 + length, BIC format & country, ABA routing checksum, IFSC format. Account on letter = account on form. Account holder vs legal name via fuzzy matching (legal suffixes stripped, distinctive tokens). | `action`, `review`, `critical` |
| 6 | **Document validity** | extracted doc fields | Insurance expiry (expired → action, <30 days → note), coverage ≥ minimum for currency, bank letter ≤ 6 months old, name on each doc matches vendor. | `action`, `info` |
| 7 | **Cross-reference & fraud** | everything + vendor master + run history | Bank account already paid to another approved vendor; tax ID already registered to someone else; duplicate vendor; resubmission diff (bank details changed when nobody asked, contact email moved to free-mail domain); IBAN country ≠ vendor country; free-mail contact. | `review`, `critical` |
| 7b | **AI second look** | documents + rule findings | AI reads the documents for concrete inconsistencies the rules don't cover. Each note must quote real text, be high-confidence and not repeat a rule finding. Notes only. | `info` (AI note), never affects the decision |
| 8 | **Decision** | all findings | `critical` → REJECTED. Risk score ≥ 75 (compounding red flags) → REJECTED. Any `action`/`review` → PENDING. Otherwise APPROVED (infos become conditions). | status |
| 9 | **Communicate & record** | decision | Vendor email (requested items listed verbatim), reviewer summary, audit trail; approved vendors written to the vendor master; superseded runs linked. | email, master record |

Severity weights for the risk score: `info` 0 · `action` 10 · `review` 25 · `critical` 100.

## Human in the loop
A PENDING run can be resolved by a reviewer (approve / reject with a note). That override is stored with
the run, so the audit trail shows what the machine found, what the reviewer decided, and why.

## Edge cases (deliberately designed)

1. **Bank account holder ≠ vendor name** — `Helios Solar GmbH` submits a bank letter for
   `Helios Energy Holding GmbH`. Not an exact match, not unrelated: they share a distinctive token, so it's a
   *plausible parent/subsidiary*. → PENDING, ask for a third-party payment authorisation. If the vendor had
   declared that parent in the form, it passes with a note. A completely unrelated holder is a `review` flag
   and compounds with other signals toward rejection.
2. **Tax ID vs country** — (a) `Brightpath Consulting` (IN) types a GSTIN that fails the checksum, but the GST
   certificate shows a valid GSTIN one character away → classified as a *typo*, vendor asked to confirm.
   (b) `Lumen Design GmbH` claims Germany but supplies a **GB** VAT number and a **GB** IBAN → not a typo but a
   *jurisdiction mismatch*; asks for German registration and routes to review.
3. **Expired / wrong document** — `Cobalt Freight Inc` uploads an insurance certificate that expired last month,
   and the "tax certificate" slot contains a W-9 for a *different company*. Each problem produces its own
   specific request.
4. **Resubmission & fraud signals** — `Kestrel Logistics` is pending (missing insurance). (a) It resubmits with
   the missing items → previous requests marked resolved → APPROVED. (b) Alternative resubmission where the
   bank account silently changed **and** the contact moved to a gmail address → classic business-email-
   compromise pattern → REJECTED. Separately, `Apex Industrial Supplies` submits a bank account that already
   belongs to approved vendor `Pinnacle Office Products` → REJECTED.
