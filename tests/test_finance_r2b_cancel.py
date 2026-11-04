"""Cancellation at real tool boundaries; no synthetic tool results."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from backend.app.tools import dispatcher
from product.api import create_app
import product.service as service_module
from product.service import FIELDS


@pytest.mark.parametrize("phase", ["pending", "planned", "waiting", "running_before_receipt", "running_after_receipt"])
def test_cancel_status_stage_and_retained_history(tmp_path, request, monkeypatch, phase):
    expected = os.getenv("R2B_EXPECT_SOURCE")
    if expected:
        assert Path(service_module.__file__).resolve().is_relative_to(Path(expected).resolve())
    artifacts = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
    artifacts.mkdir(parents=True)
    def save(name, value):
        (artifacts / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    def content(amount):
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(FIELDS)
        writer.writerows([["001", "Synthetic supplier", "0001", amount, "2026-10-01", "pending", "active"],
                          ["002", "Synthetic supplier 2", "0002", "2.25", "2026-10-02", "paid", "active"]])
        return stream.getvalue().encode("utf-8-sig")
    app = create_app(tmp_path / "workspace")
    service = app.state.service
    reached, release = threading.Event(), threading.Event()
    try:
        with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
            assert client.post("/api/setup", json={"username": "R2B owner", "password": secrets.token_urlsafe(24)}).status_code == 200
            files = []
            for role in ("source", "reference"):
                data = content("1.01" if phase == "waiting" and role == "source" else "1.00")
                (artifacts / (role + ".csv")).write_bytes(data)
                uploaded = client.post("/api/files", files={"file": (role + ".csv", data)}, data={"role": role})
                assert uploaded.status_code == 201
                files.append(uploaded.json()["id"])
            created = client.post("/api/tasks", json={"title": "Cancellation boundary", "instruction": "Reconcile synthetic rows", "source_id": files[0], "reference_id": files[1], "ai": False})
            assert created.status_code == 201
            identifier = created.json()["id"]
            if phase != "pending":
                assert client.post(f"/api/tasks/{identifier}/plan").status_code == 200
                service.future.result(timeout=30)
            if phase.startswith("running"):
                real_execute = dispatcher.execute_tool
                def controlled_execute(tool=None, arguments=None, **kwargs):
                    result = real_execute(tool, arguments, **kwargs)
                    boundary = "read_data_file" if phase == "running_before_receipt" else "submit_to_oa"
                    if tool == boundary and not reached.is_set():
                        assert result["status"] == "success"
                        reached.set()
                        assert release.wait(30), "Test boundary was not released"
                    return result
                monkeypatch.setattr(dispatcher, "execute_tool", controlled_execute)
                assert client.post(f"/api/tasks/{identifier}/run").status_code == 200
                assert reached.wait(30), "Real execution did not reach cancellation boundary"
            elif phase == "waiting":
                assert client.post(f"/api/tasks/{identifier}/run").status_code == 200
                service.future.result(timeout=30)
            previous_events = service.store.all("SELECT * FROM events ORDER BY id")
            cancel = client.post(f"/api/tasks/{identifier}/cancel")
            assert cancel.status_code == 200
            release.set()
            if phase.startswith("running"):
                service.future.result(timeout=30)
            detail = client.get(f"/api/tasks/{identifier}").json()
            listed = client.get("/api/tasks").json()["tasks"][0]
            report_response = client.get(f"/api/tasks/{identifier}/report")
            (artifacts / "report.json").write_bytes(report_response.content)
            report = json.loads((artifacts / "report.json").read_text(encoding="utf-8"))
            archive = service.store.all("SELECT * FROM archive ORDER BY id")
            financial = service.store.root / "jobs" / str(identifier) / "financial.sqlite"
            receipts = []
            if financial.exists():
                db = sqlite3.connect(financial.as_uri() + "?mode=ro", uri=True)
                db.row_factory = sqlite3.Row
                try:
                    receipts = [dict(row) for row in db.execute("SELECT * FROM oa_reconciliation_records ORDER BY id")]
                finally:
                    db.close()
            repeat = client.post(f"/api/tasks/{identifier}/cancel")
            again = client.post(f"/api/tasks/{identifier}/run")
            new_plan = client.post(f"/api/tasks/{identifier}/plan")
            final_events = service.store.all("SELECT * FROM events ORDER BY id")
            save("observations.json", {"phase": phase, "detail": detail, "list": listed, "archive": archive,
                                      "receipts": receipts, "old_events": previous_events, "events": final_events,
                                      "repeat_cancel": repeat.status_code, "run_again": again.status_code,
                                      "plan_again": new_plan.status_code, "source": service_module.__file__})
            for value in (detail, listed, report):
                assert value["status"] == "cancelled"
                assert value["stage"] == "Cancelled"
                assert value["cancel_requested"] is False
            assert report["report_kind"] == "interim"
            assert detail["archive_count"] == len(archive) == len(receipts) == int(phase == "running_after_receipt")
            assert all(row in final_events for row in previous_events)
            assert repeat.status_code == again.status_code == new_plan.status_code == 409
            assert service.store.all("SELECT * FROM archive ORDER BY id") == archive
            assert service.store.all("SELECT * FROM events ORDER BY id") == final_events
    finally:
        release.set()
        service.executor.shutdown(wait=True)
