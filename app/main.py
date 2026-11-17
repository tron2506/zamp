"""HTTP API + static UI. Run with:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import bus, config, db, documents, llm, pipeline, rules, samples

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


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Single shared login when APP_PASSWORD is set. Vendor data (bank details, tax IDs) must not be public."""
    if not config.APP_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
            if secrets.compare_digest(user, config.APP_USERNAME) and secrets.compare_digest(pwd, config.APP_PASSWORD):
                return await call_next(request)
        except (binascii.Error, UnicodeDecodeError):
            pass
    return PlainTextResponse("Authentication required", 401, headers={"WWW-Authenticate": 'Basic realm="Onboarding"'})


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


class JsonDoc(BaseModel):
    slot: str
    filename: str
    content_base64: str


class JsonSubmission(BaseModel):
    model_config = {"extra": "allow"}
    legal_name: str = ""
    country: str = ""
    documents: list[JsonDoc] = []


@app.post("/api/submissions/json")
async def submit_json(body: JsonSubmission):
    """Machine-to-machine intake (e.g. from a vendor portal or email parser)."""
    run_id = _new_id()
    folder = config.UPLOAD_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    raw = body.model_dump()
    sub = {k: str(raw.get(k) or "") for k in FIELDS}
    sub["documents"] = []
    for d in body.documents:
        if d.slot not in SLOTS:
            raise HTTPException(422, f"unknown document slot {d.slot}; use one of {SLOTS}")
        path = folder / f"{d.slot}__{_safe(d.filename)}"
        path.write_bytes(base64.b64decode(d.content_base64))
        sub["documents"].append({"slot": d.slot, "filename": d.filename, "path": str(path)})
    _start(run_id, sub, "api")
    return {"run_id": run_id}


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
async def run_sample(key: str):
    run_id = _new_id()
    _start(run_id, _sample_submission(key, run_id), f"sample:{key}")
    return {"run_id": run_id}


@app.post("/api/samples/run-all")
async def run_all():
    """Seed the dashboard: every scenario in order (Kestrel resubmissions after the first attempt)."""
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
