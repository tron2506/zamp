# Vendor Onboarding Autopilot

Takes a vendor submission (web form plus PDF documents) and returns **APPROVED · PENDING · REJECTED**. Every finding shows its reasoning, and the vendor gets an email listing exactly what is still needed. A live run view streams each stage as it executes, and a dashboard covers every run.

See **[PROCESS.md](PROCESS.md)** for the full process map (stages, decision rules, edge cases).

## Run it

```bash
./run.sh                 # creates .venv on first run, then serves http://localhost:8000
```

Open http://localhost:8000. Then either:
- go to **Dashboard → Run all test scenarios** to fill the dashboard, or
- go to **New submission**, pick a scenario, click **Load into form** (or **Run now**), and watch it execute.

### Importing vendors from a JSON file

**New submission → Import vendors from JSON** takes a `.json` file with one or more vendors (up to 25). It accepts a single vendor object, a list of vendors, or `{"vendors": [...]}`. Field names match the form (`legal_name` is required). Documents are optional and are embedded as base64:

```json
{"vendors": [
  {"legal_name": "Northwind Analytics Ltd", "country": "GB", "tax_id": "GB...", "iban": "GB...", "bic": "BARCGB22",
   "contact_email": "ap@northwind.example",
   "documents": [{"slot": "bank_letter", "filename": "letter.pdf", "content_base64": "JVBERi0..."}]}
]}
```

Document slots: `tax_certificate`, `bank_letter`, `insurance_certificate`, `incorporation_certificate`. Invalid entries are skipped and listed with the reason, and the valid ones still run. Vendors run one after another in file order, so a later entry is cross-checked against earlier ones (shared bank account, duplicate, resubmission). **Download example file** in the same panel gives a ready-to-import file.

Tests (unit tests plus every scenario end to end through real PDFs and SQLite):

```bash
.venv/bin/python -m pytest -q
```

## AI assist (optional)

Fill in `.env`:

```
LLM_API_KEY=...            # your key
LLM_BASE_URL=...           # OpenAI-compatible base URL, without /chat/completions
LLM_MODEL=glm-4.6          # model name as your provider spells it
```

Restart the app. The sidebar pill shows whether AI assist is on. With no key, or if the provider is down, every step still runs on rules alone.

| The LLM does | The LLM never does |
|---|---|
| **Autofill:** fills the submission form from the vendor's documents (rules extract first, AI fills gaps) | Decide a status or change a severity |
| **AI second look:** notes inconsistencies the rules don't cover (e.g. a certificate for a different entity or address) | Count towards the risk score (AI notes are excluded from the decision by code) |
| **Ask AI:** answers a reviewer's questions about one case, citing the findings it used | See full bank numbers (masked before every non-extraction call) |
| Extracts fields from documents the regex extractors can't parse; classifies unusual documents | Choose which items the vendor is asked for (inserted verbatim by code) |
| Writes the email greeting and sign-off, and the reviewer brief | Do checksum maths, date maths, name matching, or the fraud screen |

Guardrails: every value the AI extracts or autofills must appear **literally in a document**, and every AI note must quote real text, or it is discarded. AI notes must be high-confidence, and notes restating something the rules already flagged are dropped by code. Fields and notes are tagged `AI` or `RULE` throughout the UI.

## What's checked

| Area | Checks |
|---|---|
| Completeness | Country-specific required fields (IBAN+BIC for GB/DE, ABA routing+account for US, IFSC+account for IN), required documents |
| Documents | Text extraction, type detection even when uploaded in the wrong slot, field extraction, unreadable or scanned files |
| Tax ID | US EIN (IRS prefix table), GB VAT (mod-97), DE USt-IdNr (ISO 7064), IN GSTIN (base-36 check char, embedded PAN); typo vs wrong jurisdiction; form vs certificate |
| Bank | IBAN mod-97 and length, BIC, ABA checksum, IFSC; letter account = form account; **account holder vs vendor** (exact / suffix-normalised / typo / related entity / unrelated) |
| Validity | Right company on each document, insurance expiry and minimum cover per currency, bank letter age, future-dated documents |
| Cross-reference | Bank account already used by another approved vendor, tax ID reuse, duplicates, resubmission diff (unrequested bank change, contact-domain change, BEC pattern), previously rejected |
| Contact email | Domain ending must be real (bundled IANA list, offline), look-alike provider domains (`gmail.vo`, `gmai1.com`) go to review, free-mail and unrelated domains are reviewer notes |

**Decision rule:** any critical finding → REJECTED. Risk score ≥ 75 (compounding flags) → REJECTED. Any fixable or review item → PENDING. Otherwise APPROVED.

## Test scenarios

| Scenario | Edge case | Outcome |
|---|---|---|
| Northwind Analytics | Happy path | APPROVED, written to the vendor master |
| Helios Solar: bank letter in parent's name | 1 · Bank name mismatch | PENDING: third-party payment authorisation requested |
| Helios Solar: parent declared on the form | 1 · Bank name mismatch | APPROVED with an audit note |
| Brightpath Consulting: GSTIN typo | 2 · Tax ID vs country | PENDING: "your certificate shows X, please confirm" |
| Lumen Design: German company with a UK VAT number and UK IBAN | 2 · Tax ID vs country | PENDING: jurisdiction mismatch, internal review |
| Cobalt Freight: expired insurance, another company's W-9 | 3 · Expired / wrong document | PENDING: two specific requests |
| Apex Industrial: bank account belongs to Pinnacle | 4 · Fraud signal | REJECTED; the email does not reveal why |
| Kestrel Logistics: first attempt, then resubmission | 4 · Resubmission | PENDING, then APPROVED (previous items marked resolved) |
| Kestrel Logistics: resubmission with new bank + gmail | 4 · Resubmission fraud | REJECTED; the email goes to the *original* contact |
| Orchard & Vine: bank letter written as prose | AI assist · messy document | AI on: holder and IBAN extracted → APPROVED. Rules only: held for review (PENDING), never trusting the form |

## Deploying

The app is a single container (`Dockerfile`). Production needs three things:

1. **A persistent disk mounted at `/data`.** It holds the SQLite database and uploaded documents. Without it, run history resets on every redeploy. Sample PDFs regenerate on startup either way.
2. **Exactly one instance and one worker.** The live view streams from an in-process event bus, and SQLite wants a single writer.
3. **Environment variables:** `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. Optional: `STAGE_DELAY_MS` and `RUNS_PER_HOUR_PER_IP` (default 60).

The app deliberately has **no login**, so a tester can open the link and start immediately. All data in it is synthetic test data. To bound LLM spend if the link is shared, each visitor can start at most `RUNS_PER_HOUR_PER_IP` runs per hour; "Run all test scenarios" counts as one run per scenario.

The health check is `GET /healthz`, which needs no login.

## Project layout

```
app/
  main.py          FastAPI: submissions (form / JSON / JSON batch), SSE live stream, runs, reviewer override, vendor master
  pipeline.py      the 9 stages + decide() (a pure function of the findings)
  rules.py         policy in one place: required fields/docs, thresholds, weights
  validators/      tax.py, bank.py, names.py: deterministic, unit-tested
  documents.py     PDF text → type → fields; date and amount parsing (US/EU/IN formats)
  llm.py           OpenAI-compatible client with fallbacks and the hallucination guard
  comms.py         vendor email + reviewer brief
  samples.py       generates realistic test PDFs (dates relative to today) and seeds the vendor master
  static/          UI (vanilla JS, no build step)
tests/             validators + every scenario end to end
data/              SQLite db, uploads, generated samples (git-ignored)
```

### API

`POST /api/submissions` (multipart) · `POST /api/submissions/json` (one vendor, base64 documents) · `POST /api/submissions/batch` (one or more vendors) · `GET /api/submissions/batch/example` · `GET /api/runs` · `GET /api/runs/{id}` · `GET /api/runs/{id}/stream` (SSE) · `POST /api/runs/{id}/review` · `GET /api/vendors` · `GET /api/outbox`

## Known limits

- Scanned (image-only) PDFs are flagged as unreadable and the vendor is asked for a text PDF. There is no OCR or vision model yet.
- Tax and bank rules are built for US, GB, DE and IN. Other countries are routed to manual review instead of being guessed.
- Emails are queued in an outbox table, not sent. An SMTP provider would plug into `db.add_email`.
- Tax IDs are validated by format and check digit, not against live registries (HMRC, VIES, GSTN, IRS TIN matching). Those APIs are the natural next step.
