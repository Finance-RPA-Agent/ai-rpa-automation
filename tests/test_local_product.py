"""Real local workflow, permission, revision and persistence integration tests."""
import csv
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from product.api import create_app
from product.model import MODEL, OllamaProvider
from product.service import FIELDS
from product.storage import digest
from start_product import restore_backup

PASSWORD = "123456"
ROWS = [
    ["001", "Acme Supplies", "0001", "100.00", "2026-10-01", "pending", "active"],
    ["002", "Cedar Trading", "0002", "200.50", "2026-10-02", "paid", "active"],
]


def csv_bytes(rows, headers=FIELDS):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "workspace")
    yield application
    application.state.service.cancel_signal.set()
    application.state.service.executor.shutdown(wait=True)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as instance:
        response = instance.post("/api/setup", json={"username": "owner", "password": PASSWORD})
        assert response.status_code == 200
        yield instance


def upload(client, rows, role="source", name="orders.csv"):
    response = client.post("/api/files", files={"file": (name, csv_bytes(rows))}, data={"role": role})
    assert response.status_code == 201, response.text
    return response.json()


def create(client, rows=None, *, ai=False):
    source = upload(client, rows or ROWS)
    reference = upload(client, ROWS, "reference", "BI.csv")
    response = client.post("/api/tasks", json={"title": "Supplier reconciliation", "instruction": "Reconcile these orders against the reference export.",
                                             "source_id": source["id"], "reference_id": reference["id"], "ai": ai})
    assert response.status_code == 201, response.text
    return response.json()


def operation(client, app, job_id, kind):
    response = client.post(f"/api/tasks/{job_id}/{kind}")
    assert response.status_code == 200, response.text
    app.state.service.future.result(timeout=20)
    return client.get(f"/api/tasks/{job_id}").json()


def test_authentication_csrf_and_real_account(app):
    with TestClient(app, base_url="http://127.0.0.1") as browser:
        assert browser.get("/api/tasks").status_code == 401
        assert browser.post("/api/setup", json={"username": "owner", "password": PASSWORD}).status_code == 403
        headers = {"X-Requested-With": "FinanceFlow", "Origin": "http://malicious.example"}
        assert browser.post("/api/setup", headers=headers, json={"username": "owner", "password": PASSWORD}).status_code == 403
        browser.headers["X-Requested-With"] = "FinanceFlow"
        assert browser.post("/api/setup", json={"username": "owner", "password": "short"}).status_code == 422
        invalid = browser.post("/api/setup", json={"username": "Richard/Xu", "password": PASSWORD})
        assert invalid.status_code == 422
        assert "Username may contain" in invalid.json()["detail"][0]["msg"]
        assert browser.post("/api/setup", json={"username": " Richard Xu ", "password": PASSWORD}).status_code == 200
        assert browser.get("/api/session").json()["username"] == "Richard Xu"
        assert browser.post("/api/setup", json={"username": "other", "password": PASSWORD}).status_code == 409
        assert browser.post("/api/logout").status_code == 200
        assert browser.get("/api/files").status_code == 401
        assert browser.post("/api/login", json={"username": "Richard Xu", "password": "incorrect"}).status_code == 401
        assert browser.post("/api/login", json={"username": "Richard Xu", "password": PASSWORD}).status_code == 200


def test_clean_reconciliation_uses_runtime_and_real_imported_reference(client, app):
    task = create(client)
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 409
    planned = operation(client, app, task["id"], "plan")
    assert planned["plan"]["mode"] == "deterministic"
    done = operation(client, app, task["id"], "run")
    assert done["status"] == "completed", done
    assert done["archive_count"] == done["row_count"] == 2
    assert done["records"][0]["data"]["supplier_id"] == "001"
    assert done["records"][0]["data"]["order_id"] == "0001"
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 409
    report = client.get(f"/api/tasks/{task['id']}/report").json()
    assert report["reference_source"] == "User-imported BI export"
    assert report["trace"][0]["tool"] == "read_data_file"
    assert report["report_kind"] == "final"
    assert "Acme Supplies" in client.get(f"/api/tasks/{task['id']}/export").text


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_both_import_formats_complete_real_workflow(client, app, extension):
    if extension == ".csv":
        content = csv_bytes(ROWS)
    else:
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(FIELDS)
        for row in ROWS:
            workbook.active.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        content = buffer.getvalue()
    files = []
    for role in ("source", "reference"):
        response = client.post("/api/files", files={"file": (role + extension, content)}, data={"role": role})
        assert response.status_code == 201, response.text
        files.append(response.json())
    response = client.post("/api/tasks", json={"title": "Format check", "instruction": "Reconcile the imported order files.",
        "source_id": files[0]["id"], "reference_id": files[1]["id"], "ai": False})
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    operation(client, app, job_id, "plan")
    done = operation(client, app, job_id, "run")
    assert done["status"] == "completed", done
    assert done["archive_count"] == 2
    assert done["records"][0]["data"]["order_id"] == "0001"


def test_invalid_uploads_return_actionable_errors(client):
    for name, content in (("orders.txt", b"text"), ("empty.csv", b""), ("broken.xlsx", b"not an Excel workbook")):
        response = client.post("/api/files", files={"file": (name, content)}, data={"role": "source"})
        assert response.status_code == 422, response.text


def test_conflict_review_is_revision_bound_and_revalidated(client, app):
    rows = [list(row) for row in ROWS]
    rows[0][3] = "125.00"
    task = create(client, rows)
    operation(client, app, task["id"], "plan")
    waiting = operation(client, app, task["id"], "run")
    assert waiting["status"] == "waiting_confirmation"
    assert waiting["archive_count"] == 0
    assert waiting["issues"][0]["type"] == "amount_mismatch"
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 409
    request = {"revision": waiting["revision"], "evidence_digest": waiting["evidence_digest"],
               "changes": [{"issue_id": waiting["issues"][0]["id"], "mode": "reference", "value": None}]}
    stale = dict(request, evidence_digest="0" * 64)
    assert client.post(f"/api/tasks/{task['id']}/review", json=stale).status_code == 409
    fixed = client.post(f"/api/tasks/{task['id']}/review", json=request)
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["status"] == "waiting_confirmation"
    assert fixed.json()["issues"] == []
    assert fixed.json()["revision"] == 2
    assert fixed.json()["decisions"][0]["actor"] == "owner"
    assert fixed.json()["decisions"][0]["reason"] == ""
    assert fixed.json()["decisions"][0]["created_at"]
    assert client.post(f"/api/tasks/{task['id']}/review", json=request).status_code == 409
    done = operation(client, app, task["id"], "run")
    assert done["status"] == "completed"
    source_file = app.state.service.store.one("SELECT * FROM files WHERE id=(SELECT source_id FROM jobs WHERE id=?)", (task["id"],))
    assert digest(app.state.service.path(source_file["raw_path"])) == source_file["sha256"]


def test_manual_bad_correction_cannot_be_archived(client, app):
    rows = [list(row) for row in ROWS]
    rows[0][3] = "125.00"
    task = create(client, rows)
    operation(client, app, task["id"], "plan")
    waiting = operation(client, app, task["id"], "run")
    response = client.post(f"/api/tasks/{task['id']}/review", json={"revision": waiting["revision"], "evidence_digest": waiting["evidence_digest"],
        "changes": [{"issue_id": waiting["issues"][0]["id"], "mode": "manual", "value": "not-an-amount"}], "reason": "Intentional invalid correction test."})
    assert response.status_code == 200
    assert response.json()["issue_count"] > 0
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 409
    assert client.get("/api/archive").json()["records"] == []


def test_unknown_reference_does_not_become_success(client, app):
    rows = [list(row) for row in ROWS]
    rows[0][2] = "NOT-IN-BI"
    task = create(client, rows)
    operation(client, app, task["id"], "plan")
    waiting = operation(client, app, task["id"], "run")
    assert waiting["status"] == "waiting_confirmation"
    assert waiting["archive_count"] == 0
    assert any(issue["type"] == "record_not_found" and not issue["can_correct"] for issue in waiting["issues"])
    assert client.post(f"/api/tasks/{task['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/api/tasks/{task['id']}/run").status_code == 409


def test_mapping_and_immutable_file_versions(client, app):
    names = ["Counterparty", "Company", "PO", "Total", "Order day", "Paid", "Status"]
    response = client.post("/api/files", files={"file": ("different-columns.csv", csv_bytes(ROWS, names))}, data={"role": "source"})
    file = response.json()
    assert not file["ready"]
    response = client.post(f"/api/files/{file['id']}/mapping", json={"mapping": dict(zip(FIELDS, names))})
    assert response.status_code == 200 and response.json()["ready"]
    bad = dict(zip(FIELDS, names))
    bad["amount"] = bad["date"]
    assert client.post(f"/api/files/{file['id']}/mapping", json={"mapping": bad}).status_code == 422


def test_password_rotation_revokes_old_sessions(client, app):
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as other:
        assert other.post("/api/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
        assert client.post("/api/password", json={"current_password": PASSWORD, "new_password": "12345"}).status_code == 422
        assert client.post("/api/password", json={"current_password": PASSWORD, "new_password": "654321"}).status_code == 200
        assert other.get("/api/tasks").status_code == 401
        assert client.get("/api/tasks").status_code == 200
        assert client.post("/api/logout").status_code == 200
        assert client.post("/api/login", json={"username": "owner", "password": "654321"}).status_code == 200


def test_backup_restore_preserves_data_and_revokes_sessions(client, app, tmp_path):
    task = create(client)
    operation(client, app, task["id"], "plan")
    operation(client, app, task["id"], "run")
    response = client.post("/api/backup")
    assert response.status_code == 200
    backup = tmp_path / "backup.zip"
    backup.write_bytes(response.content)
    target = tmp_path / "restored"
    restore_backup(backup, target)
    restored = create_app(target)
    with TestClient(restored, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as browser:
        assert browser.get("/api/tasks").status_code == 401
        assert browser.post("/api/login", json={"username": "owner", "password": PASSWORD}).status_code == 200
        assert browser.get(f"/api/tasks/{task['id']}").json()["status"] == "completed"
        assert len(browser.get("/api/archive").json()["records"]) == 2
    with pytest.raises(ValueError):
        restore_backup(backup, target)


def test_real_ollama_adapter_contract_without_network():
    def endpoint(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL}]})
        body = json.loads(request.content)
        assert body["options"]["num_ctx"] == 4096
        assert body["think"] is False
        candidate = json.loads(body["messages"][0]["content"].split("Trusted candidate: ", 1)[1])
        candidate["reason"] = "Reconcile the source orders against the imported BI reference; pause for review before archiving."
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {"content": json.dumps(candidate)}})
    model = OllamaProvider(transport=httpx.MockTransport(endpoint))
    plan = model.plan("Reconcile supplier orders.", "uploads/orders.csv")
    assert plan["mode"] == "local_ai" and plan["model"] == MODEL


def test_restore_rejects_traversal(tmp_path):
    import hashlib
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../escape", b"unsafe")
        archive.writestr("finance-flow.sqlite", b"not sqlite")
        archive.writestr("manifest.json", json.dumps({"version": 1, "files": {"../escape": hashlib.sha256(b"unsafe").hexdigest(), "finance-flow.sqlite": hashlib.sha256(b"not sqlite").hexdigest()}}))
    with pytest.raises(ValueError):
        restore_backup(path, tmp_path / "destination")
    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-range lock behavior")
def test_second_launcher_recognizes_an_existing_workspace(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / "start_product.py"),
               "--no-open", "--port", str(port), "--data-dir", str(tmp_path / "launcher")]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(trust_env=False, timeout=1) as browser:
            for _ in range(100):
                assert process.poll() is None, "The first launcher stopped unexpectedly."
                try:
                    if browser.get(f"http://127.0.0.1:{port}/api/health").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("The first launcher did not become ready.")
        second = subprocess.run(command, capture_output=True, text=True, timeout=20)
        assert second.returncode == 0, second.stdout + second.stderr
        assert "already using this data directory" in second.stdout
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=15)
