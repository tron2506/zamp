"""Importing vendors from a JSON file: shapes, per-vendor validation, in-order cross-checks."""
import base64
import time

import pytest
from fastapi.testclient import TestClient

from app import config, db, main, samples


@pytest.fixture(scope="module")
def metas():
    db.init()
    return {m["key"]: m for m in samples.generate()}


def vendor(meta, with_docs=True):
    sub = samples.to_submission(meta)
    v = {k: sub[k] for k in main.FIELDS if sub.get(k)}
    if with_docs:
        v["documents"] = [{"slot": d["slot"], "filename": d["filename"],
                           "content_base64": base64.b64encode(open(d["path"], "rb").read()).decode()}
                          for d in sub["documents"]]
    return v


def wait(ids, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        runs = [db.get_run(i) for i in ids]
        if all(r["status"] != "RUNNING" for r in runs):
            return runs
        time.sleep(0.1)
    raise AssertionError("runs did not finish")


def test_batch_runs_in_order_and_skips_invalid_entries(metas):
    db.reset_all()
    body = {"vendors": [vendor(metas["northwind_happy"]),
                        {"country": "GB"},                                                     # no legal_name
                        {"legal_name": "Bad Doc Ltd", "documents": [{"slot": "passport", "filename": "x.pdf",
                                                                     "content_base64": "AAAA"}]},
                        vendor(metas["apex_shared_account"]),
                        {**vendor(metas["northwind_happy"], with_docs=False), "colour": "blue"}]}
    with TestClient(main.app) as c:
        resp = c.post("/api/submissions/batch", json=body)
        assert resp.status_code == 200
        out = resp.json()
        assert [a["index"] for a in out["accepted"]] == [1, 4, 5]
        assert [e["index"] for e in out["errors"]] == [2, 3]
        assert "legal_name" in out["errors"][0]["error"] and "passport" in out["errors"][1]["error"]
        assert out["accepted"][2]["warnings"] == ["ignored unknown field(s): colour"]
        runs = wait([a["run_id"] for a in out["accepted"]])
    assert runs[0]["status"] == "APPROVED" and runs[0]["source"] == "json-import"
    assert runs[1]["status"] == "REJECTED"                       # Apex: bank account belongs to Pinnacle
    assert runs[2]["previous_run_id"] == runs[0]["id"]          # same vendor later in the file is linked to the first


def test_single_object_and_plain_list_are_accepted(metas):
    db.reset_all()
    with TestClient(main.app) as c:
        one = c.post("/api/submissions/batch", json=vendor(metas["brightpath_gstin_typo"])).json()
        many = c.post("/api/submissions/batch", json=[{"legal_name": "A Ltd"}, {"legal_name": "B Ltd"}]).json()
        wait([a["run_id"] for a in one["accepted"] + many["accepted"]])
    assert len(one["accepted"]) == 1 and len(many["accepted"]) == 2


@pytest.mark.parametrize("body,code", [
    ([], 422), ("text", 422), ([{"country": "GB"}], 422), ([{"legal_name": "x"}] * (main.MAX_BATCH + 1), 413),
    ([{"legal_name": "x", "documents": [{"slot": "bank_letter", "filename": "a.pdf", "content_base64": "@@"}]}], 422),
])
def test_rejected_files(body, code):
    with TestClient(main.app) as c:
        assert c.post("/api/submissions/batch", json=body).status_code == code


def test_nothing_written_for_a_rejected_file():
    before = set(p.name for p in config.UPLOAD_DIR.iterdir()) if config.UPLOAD_DIR.exists() else set()
    with TestClient(main.app) as c:
        c.post("/api/submissions/batch", json=[{"country": "GB"}])
    after = set(p.name for p in config.UPLOAD_DIR.iterdir()) if config.UPLOAD_DIR.exists() else set()
    assert after == before


def test_example_file_imports_cleanly(metas):
    db.reset_all()
    with TestClient(main.app) as c:
        ex = c.get("/api/submissions/batch/example")
        assert ex.status_code == 200 and "attachment" in ex.headers["content-disposition"]
        out = c.post("/api/submissions/batch", content=ex.content, headers={"Content-Type": "application/json"}).json()
        assert out["errors"] == [] and len(out["accepted"]) == 3
        runs = wait([a["run_id"] for a in out["accepted"]])
    assert [r["status"] for r in runs] == ["APPROVED", "PENDING", "PENDING"]   # Northwind, Helios, no-docs vendor


def test_single_vendor_json_endpoint_still_works(metas):
    db.reset_all()
    with TestClient(main.app) as c:
        r = c.post("/api/submissions/json", json=vendor(metas["northwind_happy"]))
        assert r.status_code == 200
        assert c.post("/api/submissions/json", json={"country": "GB"}).status_code == 422
        wait([r.json()["run_id"]])
