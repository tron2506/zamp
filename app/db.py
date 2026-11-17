"""SQLite persistence: runs, stage events (audit trail), vendor master, outbound email."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created_at TEXT, finished_at TEXT, status TEXT, vendor_name TEXT, country TEXT,
  risk_score INTEGER, vendor_key TEXT, previous_run_id TEXT, superseded_by TEXT, source TEXT,
  submission TEXT, result TEXT, reviewer TEXT
);
CREATE TABLE IF NOT EXISTS events (
  run_id TEXT, seq INTEGER, ts TEXT, stage TEXT, state TEXT, data TEXT, PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS vendors (
  id TEXT PRIMARY KEY, legal_name TEXT, country TEXT, tax_id TEXT, account_fp TEXT, account_masked TEXT,
  contact_email TEXT, approved_at TEXT, run_id TEXT, seeded INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, to_addr TEXT, subject TEXT, body TEXT, created_at TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("submission", "result", "reviewer", "data"):
        if k in d and d[k]:
            d[k] = json.loads(d[k])
    return d


# ---------------------------------------------------------------- runs
def create_run(run_id: str, submission: dict, source: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO runs (id, created_at, status, vendor_name, country, source, submission, previous_run_id)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (run_id, now(), "RUNNING", submission.get("legal_name"), submission.get("country"), source,
                   json.dumps(submission), submission.get("previous_run_id") or None))


def update_run(run_id: str, **fields) -> None:
    if not fields:
        return
    for k in ("submission", "result", "reviewer"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k], default=str)
    cols = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), run_id))


def get_run(run_id: str) -> dict | None:
    with conn() as c:
        return _row(c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())


def list_runs(limit: int = 500) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id, created_at, finished_at, status, vendor_name, country, risk_score, vendor_key, "
                         "previous_run_id, superseded_by, source, result, reviewer FROM runs "
                         "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        res = d.pop("result") or {}
        d["top_issue"] = res.get("top_issue")
        d["counts"] = res.get("counts")
        d["duration_ms"] = res.get("duration_ms")
        d["llm_used"] = res.get("llm_used")
        d["issues"] = [{"code": f["code"], "severity": f["severity"]} for f in res.get("findings", [])
                       if f["severity"] in ("action", "review", "critical")]
        d["waiting_on"] = res.get("waiting_on")
        out.append(d)
    return out


def runs_for_vendor_key(key: str, exclude: str | None = None) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM runs WHERE vendor_key=? AND id!=? AND status!='RUNNING' "
                         "ORDER BY created_at DESC", (key, exclude or "")).fetchall()
    return [_row(r) for r in rows]


# ---------------------------------------------------------------- events
def add_event(run_id: str, seq: int, stage: str, state: str, data: dict) -> dict:
    ev = {"run_id": run_id, "seq": seq, "ts": now(), "stage": stage, "state": state, "data": data}
    with conn() as c:
        c.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                  (run_id, seq, ev["ts"], stage, state, json.dumps(data, default=str)))
    return ev


def get_events(run_id: str, after: int = -1) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after)).fetchall()
    return [_row(r) for r in rows]


# ---------------------------------------------------------------- vendor master
def list_vendors() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM vendors ORDER BY approved_at DESC").fetchall()]


def find_vendor_by_account(fp: str) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM vendors WHERE account_fp=?", (fp,)).fetchall()]


def find_vendor_by_tax(tax_id: str) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM vendors WHERE tax_id=?", (tax_id,)).fetchall()]


def add_vendor(v: dict) -> str:
    with conn() as c:
        n = c.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] + 1
        vid = v.get("id") or f"V-{n:04d}"
        c.execute("INSERT OR REPLACE INTO vendors (id, legal_name, country, tax_id, account_fp, account_masked, "
                  "contact_email, approved_at, run_id, seeded) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (vid, v["legal_name"], v["country"], v["tax_id"], v.get("account_fp"), v.get("account_masked"),
                   v.get("contact_email"), v.get("approved_at") or now(), v.get("run_id"), int(v.get("seeded", 0))))
    return vid


# ---------------------------------------------------------------- outbox
def add_email(run_id: str, to_addr: str, subject: str, body: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO outbox (run_id, to_addr, subject, body, created_at) VALUES (?,?,?,?,?)",
                  (run_id, to_addr, subject, body, now()))


def reset_all() -> None:
    with conn() as c:
        c.executescript("DELETE FROM runs; DELETE FROM events; DELETE FROM outbox; DELETE FROM vendors WHERE seeded=0;")
