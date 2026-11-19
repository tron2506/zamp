"""HTTP API + static UI. Run with:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, bus, config, db, documents, llm, pipeline, rules, samples

STATIC = Path(__file__).parent / "static"
SLOTS = ["tax_certificate", "bank_letter", "insurance_certificate", "incorporation_certificate"]
FIELDS = ["legal_name", "trading_name", "parent_company", "entity_type", "country", "address", "website",
          "contact_name", "contact_email", "contact_phone", "tax_id", "bank_name", "account_holder", "iban", "bic",
          "routing_number", "account_number", "ifsc", "previous_run_id"]
MAX_UPLOAD = 10 * 1024 * 1024
_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_app):
    db.init()
    samples.generate()
    yield


app = FastAPI(title="Vendor Onboarding Autopilot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


_run_log: dict[str, deque] = defaultdict(deque)


def _rate_limit(request: Request, cost: int = 1) -> None:
    """The app is open (no login), so cap how many runs one visitor can start per hour.
    This bounds LLM spend if the link is shared; a normal demo uses a few dozen runs at most."""
    limit = config.RUNS_PER_HOUR_PER_IP
    if limit <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now, log = time.monotonic(), _run_log[ip]
    while log and now - log[0] > 3600:
        log.popleft()
    if len(log) + cost > limit:
        raise HTTPException(429, f"Run limit reached ({limit} per hour). Please try again later.")
    log.extend([now] * cost)


@app.get("/healthz")
def healthz():
    return {"ok": True, "llm": config.LLM_ENABLED}


def _new_id() -> str:
    return "R-" + uuid.uuid4().hex[:6].upper()


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)[:100] or "document.pdf"


def _start(run_id: str, sub: dict, source: str, delay: float | None = None) -> None:
    db.create_run(run_id, sub, source)
    t = asyncio.create_task(pipeline.run_pipeline(run_id, sub, delay))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    return {
        "countries": rules.COUNTRIES,
        "slots": {s: documents.DOC_TYPES[s] for s in SLOTS},
        "required_docs": rules.REQUIRED_DOCS,
        "stages": [{"key": k, "title": t, "desc": d} for k, t, d in pipeline.STAGES],
        "llm": llm.status(),
        "scenarios": [{**{k: m[k] for k in ("key", "title", "edge", "description", "files", "submission")},
                       "expected": samples.expected(m, llm.enabled())} for m in samples.load_all()],
    }


@app.get("/api/samples/{key}/files/{filename}")
def sample_file(key: str, filename: str):
    p = (config.SAMPLES_DIR / _safe(key) / _safe(filename)).resolve()
    if not p.is_file() or config.SAMPLES_DIR.resolve() not in p.parents:
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf")


# ---------------------------------------------------------------- submissions
@app.post("/api/submissions")
async def submit_form(request: Request):
    """The web form: multipart fields + up to 4 PDF uploads (one per slot)."""
    _rate_limit(request)
    form = await request.form()
    run_id = _new_id()
    folder = config.UPLOAD_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    sub = {k: str(form.get(k) or "") for k in FIELDS}
    sub["documents"] = []
    for slot in SLOTS:
        f = form.get(slot)
        if isinstance(f, UploadFile) or hasattr(f, "read"):
            data = await f.read()
            if not data:
                continue
            if len(data) > MAX_UPLOAD:
                raise HTTPException(413, f"{f.filename} is larger than 10 MB")
            path = folder / f"{slot}__{_safe(f.filename)}"
            path.write_bytes(data)
            sub["documents"].append({"slot": slot, "filename": f.filename, "path": str(path)})
    _start(run_id, sub, str(form.get("source") or "form"))
    return {"run_id": run_id}


@app.post("/api/autofill")
async def autofill(request: Request):
    """Pre-fill the form from uploaded documents: rules first, AI fills gaps; every value is verbatim from a document."""
    _rate_limit(request)
    form = await request.form()
    folder = config.DATA_DIR / "autofill" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        files = []
        for slot in SLOTS:
            f = form.get(slot)
            if hasattr(f, "read"):
                data = await f.read()
                if not data:
                    continue
                if len(data) > MAX_UPLOAD:
                    raise HTTPException(413, f"{f.filename} is larger than 10 MB")
                path = folder / _safe(f.filename)
                path.write_bytes(data)
                files.append({"slot": slot, "filename": f.filename, "path": str(path)})
        if not files:
            raise HTTPException(422, "Attach at least one document first")
        return await ai.autofill(files)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


MAX_BATCH = 25
_DOC_KEYS = {"slot", "filename", "content_base64"}


def _parse_vendor(raw, run_id: str) -> tuple[dict, list[str]]:
    """One vendor object from JSON -> a submission (documents written under the run's upload folder).
    Raises ValueError with a message the person importing can act on. Returns (submission, warnings)."""
    if not isinstance(raw, dict):
        raise ValueError("each vendor must be a JSON object")
    warnings, sub = [], {}
    for k in FIELDS:
        v = raw.get(k)
        if isinstance(v, (dict, list)):
            raise ValueError(f"field '{k}' must be text, not a {type(v).__name__}")
        sub[k] = "" if v is None else str(v)
    if not sub["legal_name"].strip():
        raise ValueError("'legal_name' is required")
    unknown = sorted(set(raw) - set(FIELDS) - {"documents"})
    if unknown:
        warnings.append("ignored unknown field(s): " + ", ".join(unknown))

    docs = raw.get("documents") or []
    if not isinstance(docs, list):
        raise ValueError("'documents' must be a list of {slot, filename, content_base64}")
    if len(docs) > len(SLOTS):
        raise ValueError(f"at most {len(SLOTS)} documents per vendor")
    decoded, seen = [], set()
    for i, d in enumerate(docs, 1):
        if not isinstance(d, dict) or not _DOC_KEYS <= set(d):
            raise ValueError(f"document {i} needs slot, filename and content_base64")
        if d["slot"] not in SLOTS:
            raise ValueError(f"document {i}: unknown slot '{d['slot']}'; use one of {', '.join(SLOTS)}")
        if d["slot"] in seen:
            raise ValueError(f"document {i}: slot '{d['slot']}' is used twice")
        seen.add(d["slot"])
        try:
            data = base64.b64decode(str(d["content_base64"]), validate=True)
        except ValueError:
            raise ValueError(f"document {i} ({d['filename']}): content_base64 is not valid base64") from None
        if not data:
            raise ValueError(f"document {i} ({d['filename']}) is empty")
        if len(data) > MAX_UPLOAD:
            raise ValueError(f"document {i} ({d['filename']}) is larger than 10 MB")
        decoded.append((d["slot"], str(d["filename"]), data))

    sub["documents"] = []
    if decoded:                      # only touch the disk once the whole vendor is valid
        folder = config.UPLOAD_DIR / run_id
        folder.mkdir(parents=True, exist_ok=True)
        for slot, fn, data in decoded:
            path = folder / f"{slot}__{_safe(fn)}"
            path.write_bytes(data)
            sub["documents"].append({"slot": slot, "filename": fn, "path": str(path)})
    return sub, warnings


@app.post("/api/submissions/json")
async def submit_json(request: Request):
    """Machine-to-machine intake for one vendor (e.g. from a vendor portal or email parser)."""
    try:
        raw = await request.json()
    except ValueError:
        raise HTTPException(422, "body is not valid JSON") from None
    run_id = _new_id()
    try:
        sub, warnings = _parse_vendor(raw, run_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    _rate_limit(request)
    _start(run_id, sub, "api")
    return {"run_id": run_id, "warnings": warnings}


@app.post("/api/submissions/batch")
async def submit_batch(request: Request):
    """Import one or more vendors from a JSON file: a single vendor object, a list of them, or {"vendors": [...]}.
    Invalid entries are reported and skipped; valid ones run one after another, in file order, so a later
    entry is cross-checked against earlier ones (shared bank account, duplicate, resubmission)."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(422, "the file is not valid JSON") from None
    if isinstance(body, dict) and isinstance(body.get("vendors"), list):
        items = body["vendors"]
    elif isinstance(body, list):
        items = body
    elif isinstance(body, dict):
        items = [body]
    else:
        raise HTTPException(422, 'expected a vendor object, a list of vendors, or {"vendors": [...]}')
    if not items:
        raise HTTPException(422, "the file contains no vendors")
    if len(items) > MAX_BATCH:
        raise HTTPException(413, f"at most {MAX_BATCH} vendors per file (this one has {len(items)})")

    accepted, errors = [], []
    for i, raw in enumerate(items, 1):
        name = str(raw.get("legal_name") or "").strip() if isinstance(raw, dict) else ""
        run_id = _new_id()
        try:
            sub, warnings = _parse_vendor(raw, run_id)
        except ValueError as e:
            errors.append({"index": i, "legal_name": name, "error": str(e)})
            continue
        accepted.append({"index": i, "legal_name": name, "run_id": run_id, "warnings": warnings, "sub": sub})
    if not accepted:
        raise HTTPException(422, {"message": "no vendor in the file could be imported", "errors": errors})

    try:
        _rate_limit(request, cost=len(accepted))
    except HTTPException:
        for a in accepted:
            shutil.rmtree(config.UPLOAD_DIR / a["run_id"], ignore_errors=True)
        raise
    for a in accepted:
        db.create_run(a["run_id"], a["sub"], "json-import")

    async def go():
        for a in accepted:
            await pipeline.run_pipeline(a["run_id"], a.pop("sub"), delay=0.05)
    t = asyncio.create_task(go())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"accepted": [{k: v for k, v in a.items() if k != "sub"} for a in accepted], "errors": errors}


@app.get("/api/submissions/batch/example")
def batch_example():
    """A ready-to-import example file: two vendors with their documents embedded, one with no documents."""
    vendors = []
    for key in ("northwind_happy", "helios_related_holder"):
        m = next(m for m in samples.load_all() if m["key"] == key)
        sub = samples.to_submission(m)
        v = {k: sub.get(k, "") for k in FIELDS if sub.get(k)}
        v["documents"] = [{"slot": d["slot"], "filename": d["filename"],
                           "content_base64": base64.b64encode(Path(d["path"]).read_bytes()).decode()}
                          for d in sub["documents"]]
        vendors.append(v)
    vendors.append({"legal_name": "Juniper Print Co Ltd", "country": "GB", "address": "4 Mill Lane, Leeds LS1 4AB",
                    "contact_name": "Sam Patel", "contact_email": "sam@juniperprint.co.uk",
                    "contact_phone": "+44 113 496 0555", "tax_id": "GB123456782", "bank_name": "Barclays",
                    "iban": "GB33BUKB20201555555555", "bic": "BUKBGB22", "documents": []})
    return JSONResponse({"vendors": vendors},
                        headers={"Content-Disposition": 'attachment; filename="vendors_example.json"'})


def _sample_submission(key: str, run_id: str) -> dict:
    m = next((m for m in samples.load_all() if m["key"] == key), None)
    if not m:
        raise HTTPException(404, "unknown scenario")
    sub = samples.to_submission(m)
    folder = config.UPLOAD_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    for d in sub["documents"]:
        dst = folder / f"{d['slot']}__{d['filename']}"
        shutil.copy(d["path"], dst)
        d["path"] = str(dst)
    return sub


@app.post("/api/samples/{key}/run")
async def run_sample(key: str, request: Request):
    _rate_limit(request)
    run_id = _new_id()
    _start(run_id, _sample_submission(key, run_id), f"sample:{key}")
    return {"run_id": run_id}


@app.post("/api/samples/run-all")
async def run_all(request: Request):
    """Seed the dashboard: every scenario in order (Kestrel resubmissions after the first attempt)."""
    _rate_limit(request, cost=len(samples.SCENARIOS))
    async def go():
        for m in samples.load_all():
            run_id = _new_id()
            sub = _sample_submission(m["key"], run_id)
            db.create_run(run_id, sub, f"sample:{m['key']}")
            await pipeline.run_pipeline(run_id, sub, delay=0.05)
    t = asyncio.create_task(go())
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return {"queued": len(samples.SCENARIOS)}


# ---------------------------------------------------------------- runs
@app.get("/api/runs")
def runs():
    rows = db.list_runs()
    stats = {s: sum(1 for r in rows if r["status"] == s) for s in ("APPROVED", "PENDING", "REJECTED", "RUNNING", "ERROR")}
    stats["total"] = len(rows)
    stats["open"] = sum(1 for r in rows if r["status"] == "PENDING" and not r["superseded_by"])
    durations = [r["duration_ms"] for r in rows if r.get("duration_ms")]
    stats["avg_ms"] = round(sum(durations) / len(durations)) if durations else None
    return {"runs": rows, "stats": stats}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404)
    r["events"] = db.get_events(run_id)
    for d in r["submission"].get("documents", []):
        d.pop("path", None)
    return r


@app.get("/api/runs/{run_id}/documents/{slot}")
def run_document(run_id: str, slot: str):
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404)
    for d in r["submission"].get("documents", []):
        if d["slot"] == slot and d.get("path") and Path(d["path"]).is_file():
            return FileResponse(d["path"], media_type="application/pdf", filename=d["filename"],
                                content_disposition_type="inline")
    raise HTTPException(404)


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str):
    if not db.get_run(run_id):
        raise HTTPException(404)

    async def gen():
        q = bus.subscribe(run_id)
        last = -1
        try:
            for ev in db.get_events(run_id):
                last = ev["seq"]
                yield f"data: {json.dumps(ev, default=str)}\n\n"
                if ev["state"] in ("complete", "error"):
                    return
            if db.get_run(run_id)["status"] not in ("RUNNING",):
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield f"data: {json.dumps(ev, default=str)}\n\n"
                if ev["state"] in ("complete", "error"):
                    return
        finally:
            bus.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Ask(BaseModel):
    question: str
    history: list[dict] = []


@app.post("/api/runs/{run_id}/ask")
async def ask(run_id: str, body: Ask, request: Request):
    """Reviewer Q&A grounded in this case's findings. Read-only: it cannot change anything."""
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404)
    if run["status"] in ("RUNNING", "ERROR"):
        raise HTTPException(409, "The case must finish running first")
    if not llm.enabled():
        raise HTTPException(503, "AI assist is off: set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL in .env")
    if not body.question.strip():
        raise HTTPException(422, "Ask a question")
    _rate_limit(request)
    out = await ai.ask_case(run, body.question.strip(), body.history)
    if not out:
        raise HTTPException(502, "The AI service did not answer. Please try again.")
    return out


class Review(BaseModel):
    action: str  # approve | reject
    note: str
    reviewer: str = "Procurement reviewer"


@app.post("/api/runs/{run_id}/review")
def review(run_id: str, body: Review):
    """Human-in-the-loop: a reviewer resolves a PENDING case. Recorded alongside the machine's findings."""
    r = db.get_run(run_id)
    if not r:
        raise HTTPException(404)
    if r["status"] != "PENDING":
        raise HTTPException(409, "only pending runs can be reviewed")
    if body.action not in ("approve", "reject") or len(body.note.strip()) < 5:
        raise HTTPException(422, "action must be approve/reject and a note (≥5 chars) is required")
    new_status = "APPROVED" if body.action == "approve" else "REJECTED"
    rec = {"action": body.action, "note": body.note.strip(), "by": body.reviewer, "at": db.now(),
           "machine_status": r["status"]}
    if new_status == "APPROVED":
        s, res = r["submission"], r["result"]
        from .validators import bank as _bank, tax as _tax
        rec["vendor_id"] = db.add_vendor({
            "legal_name": s["legal_name"], "country": s["country"], "tax_id": res.get("tax_id_normalized") or _tax.clean(s.get("tax_id")),
            "account_fp": res.get("account_fp"), "account_masked": _bank.mask(res.get("account_fp")),
            "contact_email": s.get("contact_email"), "run_id": run_id})
    db.update_run(run_id, status=new_status, reviewer=rec)
    events = db.get_events(run_id)
    db.add_event(run_id, (events[-1]["seq"] + 1) if events else 0, "review", "review", rec)
    return {"status": new_status, "reviewer": rec}


@app.get("/api/vendors")
def vendors():
    return {"vendors": db.list_vendors()}


@app.get("/api/outbox")
def outbox():
    with db.conn() as c:
        return {"emails": [dict(r) for r in c.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 200")]}


@app.post("/api/reset")
def reset():
    db.reset_all()
    shutil.rmtree(config.UPLOAD_DIR, ignore_errors=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return {"ok": True}
