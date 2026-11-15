"""Real single-owner HTTP/SQLite review integrity regressions; synthetic data only."""
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets

from fastapi.testclient import TestClient
import pytest

from product.api import create_app
import product.service as service_module
from product.service import FIELDS


ROWS = [["001", "Synthetic Supplier", "0001", "125.00", "2026-10-01", "pending", "active"]]
REFERENCE = [["001", "Synthetic Supplier", "0001", "100.00", "2026-10-01", "pending", "active"]]


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


@pytest.fixture
def local(tmp_path, request):
    expected = os.getenv("R2B_EXPECT_SOURCE")
    if expected:
        assert Path(service_module.__file__).resolve().is_relative_to(Path(expected).resolve())
    app = create_app(tmp_path / "workspace")
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        assert client.post("/api/setup", json={"username": "R2B owner", "password": secrets.token_urlsafe(24)}).status_code == 200
        evidence = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
        evidence.mkdir(parents=True)
        (evidence / "input.csv").write_bytes(csv_bytes(ROWS))
        (evidence / "reference.csv").write_bytes(csv_bytes(REFERENCE))
        (evidence / "identity.json").write_text(json.dumps({"test": request.node.nodeid, "source": service_module.__file__}), encoding="utf-8")
        yield client, app.state.service, evidence


def save(local, name, value):
    (local[2] / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def upload(local, rows, role):
    response = local[0].post("/api/files", files={"file": (role + ".csv", csv_bytes(rows))}, data={"role": role})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def task(local, pair=None):
    source, reference = pair or (upload(local, ROWS, "source"), upload(local, REFERENCE, "reference"))
    response = local[0].post("/api/tasks", json={"title": "R2B synthetic review", "instruction": "Reconcile synthetic files", "source_id": source, "reference_id": reference, "ai": False})
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    for op in ("plan", "run"):
        assert local[0].post(f"/api/tasks/{identifier}/{op}").status_code == 200
        local[1].future.result(timeout=30)
    return local[0].get(f"/api/tasks/{identifier}").json()


def body(detail, value=None):
    return {"revision": detail["revision"], "evidence_digest": detail["evidence_digest"],
            "changes": [{"issue_id": detail["issues"][0]["id"], "mode": "reference" if value is None else "manual", "value": value}],
            "reason": "Synthetic reviewer checked the displayed evidence."}


def snapshot(local):
    service = local[1]
    return {"tables": {table: service.store.all("SELECT * FROM " + table) for table in ("jobs", "decisions", "events", "archive")},
            "files": {str(path.relative_to(service.store.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for folder in ("files", "jobs") for path in (service.store.root / folder).rglob("*") if path.is_file()}}


def rejected_unchanged(local, identifier, payload, name="rejected"):
    before = snapshot(local)
    response = local[0].post(f"/api/tasks/{identifier}/review", json=payload)
    after = snapshot(local)
    save(local, name, {"before": before, "after": after, "http_status": response.status_code, "response": response.json()})
    assert response.status_code == 409
    assert after == before


@pytest.mark.parametrize("shared", [True, False])
def test_cross_task_evidence_is_rejected(local, shared):
    pair = (upload(local, ROWS, "source"), upload(local, REFERENCE, "reference")) if shared else None
    first, second = task(local, pair), task(local, pair)
    save(local, "tasks", {"a": first, "b": second})
    rejected_unchanged(local, second["id"], body(first))
    assert first["evidence_digest"] != second["evidence_digest"]


def test_copied_stored_digest_cannot_authorize_another_task(local):
    pair = (upload(local, ROWS, "source"), upload(local, REFERENCE, "reference"))
    first, second = task(local, pair), task(local, pair)
    assert first["issues"][0]["id"] == second["issues"][0]["id"]
    _, state = local[1].get_job(second["id"])
    original_state = copy.deepcopy(state)
    state["evidence_digest"] = first["evidence_digest"]
    with local[1].store.connect() as db:
        db.execute("UPDATE jobs SET state_json=? WHERE id=?", (json.dumps(state), second["id"]))
    save(local, "copied_stored_digest", {"a": first, "b": second, "original_b_state": original_state,
                                        "tampered_b_state": state})
    rejected_unchanged(local, second["id"], body(first))


@pytest.mark.parametrize("shared", [True, False])
def test_partial_correction_collision_is_task_bound(local, shared):
    pair = (upload(local, ROWS, "source"), upload(local, REFERENCE, "reference")) if shared else None
    first, second = task(local, pair), task(local, pair)
    updated = []
    for detail in (first, second):
        response = local[0].post(f"/api/tasks/{detail['id']}/review", json=body(detail, "not-money"))
        assert response.status_code == 200
        updated.append(response.json())
    a, b = updated
    assert a["revision"] == b["revision"] == 2
    assert a["issues"][0]["id"] == b["issues"][0]["id"]
    save(local, "corrected_tasks", {"a": a, "b": b})
    rejected_unchanged(local, b["id"], body(a))
    assert a["evidence_digest"] != b["evidence_digest"]


def test_valid_same_task_and_old_credentials(local):
    detail = task(local)
    original = snapshot(local)["files"]
    stale = dict(body(detail), evidence_digest="0" * 64)
    rejected_unchanged(local, detail["id"], stale, "wrong_digest")
    rejected_unchanged(local, detail["id"], dict(body(detail), revision=detail["revision"]+1), "wrong_revision")
    response = local[0].post(f"/api/tasks/{detail['id']}/review", json=body(detail))
    assert response.status_code == 200
    revised = response.json()
    assert revised["revision"] == 2 and not revised["issues"]
    assert len(revised["decisions"]) == 1 and revised["archive_count"] == 0
    assert all(snapshot(local)["files"][p] == v for p, v in original.items())
    rejected_unchanged(local, detail["id"], body(detail), "old_after_revision")
    assert local[0].post(f"/api/tasks/{detail['id']}/run").status_code == 200
    local[1].future.result(timeout=30)
    completed = local[0].get(f"/api/tasks/{detail['id']}").json()
    save(local, "completed", completed)
    assert completed["status"] == "completed" and completed["archive_count"] == 1


@pytest.mark.parametrize("damage", ["working", "reference", "reference_identity", "issues"])
def test_recompute_bound_evidence_before_any_writes(local, damage):
    detail = task(local)
    job, state = local[1].get_job(detail["id"])
    if damage == "working":
        local[1].path(state["working_file"]).write_bytes(csv_bytes(REFERENCE))
    elif damage == "reference":
        file = local[1].file(job["reference_id"])
        local[1].path(file["canonical_path"]).write_bytes(csv_bytes(ROWS))
    else:
        with local[1].store.connect() as db:
            if damage == "reference_identity":
                replacement = upload(local, REFERENCE, "reference")
                db.execute("UPDATE jobs SET reference_id=? WHERE id=?", (replacement, detail["id"]))
            else:
                state["issues"][0]["reference_value"] = "99.00"
                db.execute("UPDATE jobs SET state_json=? WHERE id=?", (json.dumps(state), detail["id"]))
    rejected_unchanged(local, detail["id"], body(detail))


def test_legacy_waiting_task_refreshes_without_writing_or_approving(local):
    detail = task(local)
    job, state = local[1].get_job(detail["id"])
    legacy = hashlib.sha256(local[1].path(state["working_file"]).read_bytes()).hexdigest()
    state["evidence_digest"] = legacy
    with local[1].store.connect() as db:
        db.execute("UPDATE jobs SET state_json=? WHERE id=?", (json.dumps(state), detail["id"]))
    before = snapshot(local)
    refreshed = local[0].get(f"/api/tasks/{detail['id']}").json()
    save(local, "legacy_refresh", {"legacy": legacy, "refreshed": refreshed, "before": before, "after": snapshot(local)})
    assert snapshot(local) == before
    rejected_unchanged(local, detail["id"], dict(body(refreshed), evidence_digest=legacy), "legacy_rejected")
    assert refreshed["evidence_digest"] != legacy
    assert local[0].post(f"/api/tasks/{detail['id']}/review", json=body(refreshed)).status_code == 200
