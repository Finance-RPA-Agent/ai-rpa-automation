"""G02: genuine isolated-process crash recovery with real financial tools and HTTP.

The only injected behavior is a process exit at a documented commit boundary, or
an explicitly corrupted synthetic stored row. No tool result is fabricated.
This file doubles as a subprocess worker; raw auth tables are never exported.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import time

import pytest


FIELDS = ["supplier_id", "supplier_name", "order_id", "amount", "date", "payment_status", "record_status"]
ROWS = [
    ["001", "Synthetic Acme", "0001", "100.10", "2026-10-01", "pending", "active"],
    ["002", "Synthetic Cedar", "0002", "200.20", "2026-10-02", "paid", "active"],
]
CENTRAL_TABLES = ("jobs", "archive", "decisions", "events", "batches", "batch_jobs")


def csv_bytes():
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(FIELDS)
    writer.writerows(ROWS)
    return stream.getvalue().encode("utf-8-sig")


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_rows(path, tables):
    if not Path(path).is_file():
        return {}
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {table: [dict(row) for row in connection.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
                for table in tables if table in existing}


def snapshot(root):
    data = Path(root) / "data"
    return {
        "central": read_rows(data / "finance-flow.sqlite", CENTRAL_TABLES),
        "financial": {path.parent.name: read_rows(path, ("tasks", "oa_reconciliation_records", "bi_financial_records", "task_logs"))
                      for path in sorted((data / "jobs").glob("*/financial.sqlite"))},
        "financial_sha256": {path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in sorted((data / "jobs").glob("*/financial.sqlite"))},
    }


def receipts(value, identifier=1):
    return value["financial"].get(str(identifier), {}).get("oa_reconciliation_records", [])


def worker(mode, root, output, repository):
    """Only called in a separate child process; never exits the pytest parent."""
    root, output, repository = Path(root).resolve(), Path(output), Path(repository).resolve()
    sys.path.insert(0, str(repository))
    root.mkdir(parents=True, exist_ok=True)
    from product.api import create_app
    import product.service as product_service
    from backend.app.tools import dispatcher
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    assert Path(product_service.__file__).resolve().is_relative_to(repository)
    identity = {"pid": os.getpid(), "mode": mode, "source": product_service.__file__, "repository": str(repository)}
    data = root / "data"

    def make(service, title="Synthetic recovery", plan=True):
        source = service.upload(title + "-source.csv", csv_bytes(), "source")
        reference = service.upload(title + "-reference.csv", csv_bytes(), "reference")
        job = service.create(title, "Reconcile these synthetic records against the fixed BI import.", source["id"], reference["id"], False)
        if plan:
            service.schedule(job["id"], "plan", "R2B recovery owner")
            service.future.result(timeout=30)
        return job["id"]

    if mode.startswith("seed_"):
        service = product_service.ProductService(data)
        inputs = root / "inputs"
        inputs.mkdir(exist_ok=True)
        (inputs / "source.csv").write_bytes(csv_bytes())
        (inputs / "reference.csv").write_bytes(csv_bytes())
        batch_id = None
        if mode == "seed_batch":
            for role, name in (("source", "orders.csv"), ("reference", "bi.csv")):
                folder = inputs / role
                folder.mkdir(exist_ok=True)
                (folder / name).write_bytes(csv_bytes())
            # Root-level duplicate inputs are outside the selected folder.
            batch_inbox = root / "batch_inbox"
            for role, name in (("source", "orders.csv"), ("reference", "bi.csv")):
                folder = batch_inbox / role
                folder.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(csv_bytes())
            batch = service.batches.scan(str(batch_inbox), "R2B recovery owner")
            batch_id = batch["id"]
            service.future.result(timeout=30)
            identifier = None
        else:
            identifier = make(service)
            # Independent pending task proves one damaged job cannot prevent all reads.
            make(service, "Unaffected pending task", plan=False)
        if mode == "seed_pending":
            save(output, {**identity, "job_id": identifier, "snapshot": snapshot(root)})
            service.executor.shutdown(wait=True)
            return

        original = dispatcher.execute_tool
        recorded = []

        def dispatch(name, arguments, **kwargs):
            if name == "submit_to_oa" and mode == "seed_before":
                save(output, {**identity, "job_id": arguments["task_id"], "boundary": "before_real_oa_call",
                              "arguments": arguments, "snapshot": snapshot(root)})
                os._exit(85)
            response = original(name, arguments, **kwargs)
            if name == "submit_to_oa" and response.get("status") == "success" and not recorded:
                recorded.append(response)
                if mode == "seed_live_conflict":
                    actual = receipts(snapshot(root), arguments["task_id"])[0]
                    with service.store.connect() as db:
                        db.execute("INSERT INTO archive VALUES(?,?,?,?,?,?)", (
                            f"FF-{arguments['task_id']:05d}-{actual['id']:05d}", arguments["task_id"], actual["operation_id"],
                            actual["record_id"], '{"conflicting":"synthetic central payload"}', "synthetic-original-time"))
                    return response
                save(output, {**identity, "job_id": arguments["task_id"], "batch_id": batch_id,
                              "boundary": "after_real_oa_commit_before_product_mirror", "actual_response": response,
                              "arguments": arguments, "snapshot": snapshot(root)})
                os._exit(86)
            return response

        dispatcher.execute_tool = dispatch
        try:
            if batch_id is not None:
                service.batches.start(batch_id, "R2B recovery owner")
            else:
                service.schedule(identifier, "run", "R2B recovery owner")
            service.future.result(timeout=30)
            if mode != "seed_live_conflict":
                raise AssertionError("The genuine OA crash boundary was never reached")
            save(output, {**identity, "job_id": identifier, "snapshot": snapshot(root), "actual_first_response": recorded})
        finally:
            dispatcher.execute_tool = original
            service.executor.shutdown(wait=True)
        return

    before = snapshot(root)
    attempts = []
    original_dispatch = dispatcher.execute_tool
    original_database = product_service.ProductService.job_database

    def observe_dispatch(name, arguments, **kwargs):
        attempts.append({"tool": name, "arguments": arguments})
        return original_dispatch(name, arguments, **kwargs)

    def forbidden_database(*args, **kwargs):
        raise AssertionError("Read-only receipt recovery called the DB creation/execution path")

    dispatcher.execute_tool = observe_dispatch
    product_service.ProductService.job_database = forbidden_database
    try:
        application = create_app(data)
        service = application.state.service
        responses = []
        with TestClient(application, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
            credential = {"username": "R2B recovery owner", "password": os.environ["R2B_RECOVERY_TEST_PASSWORD"]}
            route = "/api/setup" if client.get("/api/session").json()["setup_required"] else "/api/login"
            signed = client.post(route, json=credential)
            assert signed.status_code == 200, signed.text

            def http(method, path):
                response = client.request(method, path)
                responses.append({"method": method, "path": path, "status": response.status_code, "body": response.json()})
                return response

            if mode == "cancel":
                http("POST", "/api/tasks/1/cancel")
            elif mode == "retry":
                product_service.ProductService.job_database = original_database
                for operation in ("plan", "run"):
                    response = http("POST", "/api/tasks/1/" + operation)
                    assert response.status_code == 200, response.text
                    service.future.result(timeout=30)
            # Query archive first, without a preceding task read that could hide startup omissions.
            for path in ("/api/archive", "/api/tasks/1", "/api/tasks/1/report", "/api/tasks/2"):
                http("GET", path)
            if mode in ("observe", "cancel"):
                http("POST", "/api/tasks/1/run")
            workbook_details = None
            if before["central"].get("batches"):
                batch_id = before["central"]["batches"][0]["id"]
                http("GET", f"/api/batches/{batch_id}")
                response = client.get(f"/api/batches/{batch_id}/report")
                assert response.status_code == 200, response.text
                xlsx_path = output.with_suffix(".xlsx")
                xlsx_path.write_bytes(response.content)
                book = load_workbook(io.BytesIO(response.content), data_only=False)
                workbook_details = {sheet.title: list(sheet.values) for sheet in book.worksheets}
                book.close()
        save(output, {**identity, "before": before, "after": snapshot(root), "responses": responses,
                      "dispatcher_calls": attempts, "workbook": workbook_details})
    finally:
        dispatcher.execute_tool = original_dispatch
        product_service.ProductService.job_database = original_database


@pytest.fixture
def scenario(tmp_path, request):
    import product.service as product_service
    repository = Path(product_service.__file__).resolve().parents[1]
    expected = os.environ.get("R2B_EXPECT_SOURCE")
    if expected:
        assert repository == Path(expected).resolve()
    key = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
    evidence = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / key
    evidence.mkdir(parents=True, exist_ok=False)
    save(evidence / "identity.json", {"test": request.node.nodeid, "source": str(repository)})
    (evidence / "source.csv").write_bytes(csv_bytes())
    (evidence / "reference.csv").write_bytes(csv_bytes())
    root = tmp_path / "scenario"
    environment = os.environ.copy()
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "R2B_RECOVERY_TEST_PASSWORD": secrets.token_urlsafe(24),
                        "RPA_BASE_DIR": str(tmp_path / "unused-default"),
                        "RPA_DATABASE_URL": "sqlite:///" + (tmp_path / "unused-default.sqlite").as_posix(),
                        "RPA_UPLOAD_DIR": str(tmp_path / "unused-default/uploads"),
                        "RPA_DEMO_DATA_DIR": str(tmp_path / "unused-default/demo"),
                        "RPA_OUTPUT_DIR": str(tmp_path / "unused-default/outputs")})
    commands = []

    def run(mode, label=None, expected_exit=0):
        label = label or mode
        output = evidence / (label + ".json")
        command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                   "--worker", mode, str(root), str(output), str(repository)]
        started = time.time()
        completed = subprocess.run(command, env=environment, cwd=repository, capture_output=True, timeout=60)
        (evidence / (label + ".stdout")).write_bytes(completed.stdout)
        (evidence / (label + ".stderr")).write_bytes(completed.stderr)
        commands.append({"command": command, "started_unix": started, "seconds": time.time()-started,
                         "exit_code": completed.returncode, "expected_exit_code": expected_exit})
        save(evidence / "commands.json", commands)
        assert completed.returncode == expected_exit, completed.stderr.decode("utf-8", errors="replace")
        return json.loads(output.read_text(encoding="utf-8"))

    return root, evidence, run


def response(value, path, method="GET"):
    return next(item for item in value["responses"] if item["path"] == path and item["method"] == method)


def assert_consistent(value, count, status):
    task = response(value, "/api/tasks/1")
    report = response(value, "/api/tasks/1/report")
    archive = response(value, "/api/archive")
    assert task["status"] == report["status"] == archive["status"] == 200
    assert task["body"]["status"] == report["body"]["status"] == status
    assert task["body"]["archive_count"] == report["body"]["archive_count"] == len(archive["body"]["records"]) == count
    assert len(receipts(value["after"])) == len(value["after"]["central"]["archive"]) == count
    assert report["body"]["report_kind"] == ("final" if status == "completed" else "interim")
    assert {row["operation_id"] for row in archive["body"]["records"]} == {row["operation_id"] for row in receipts(value["after"])}


def test_crash_after_commit_recovers_all_views_twice_without_reexecution(scenario):
    _, _, run = scenario
    seed = run("seed_after", expected_exit=86)
    assert len(receipts(seed["snapshot"])) == 1
    assert seed["snapshot"]["central"]["archive"] == []
    first = run("observe", "restart_one")
    second = run("observe", "restart_two")
    assert first["pid"] != second["pid"] != seed["pid"]
    for value in (first, second):
        assert_consistent(value, 1, "failed")
        assert response(value, "/api/tasks/1")["body"]["plan_status"] == "interrupted"
        assert response(value, "/api/tasks/1/run", "POST")["status"] == 409
        assert value["dispatcher_calls"] == []
        assert value["after"]["financial"] == seed["snapshot"]["financial"]
        assert value["after"]["financial_sha256"] == seed["snapshot"]["financial_sha256"]
    assert second["after"]["central"] == first["after"]["central"]


def test_crash_before_commit_does_not_invent_a_receipt(scenario):
    _, _, run = scenario
    seed = run("seed_before", expected_exit=85)
    observed = run("observe")
    assert_consistent(observed, 0, "failed")
    assert observed["dispatcher_calls"] == []
    assert observed["after"]["financial"] == seed["snapshot"]["financial"]


def test_reading_pending_task_does_not_create_financial_database(scenario):
    root, _, run = scenario
    seed = run("seed_pending")
    observed = run("observe_pending")
    assert_consistent(observed, 0, "pending")
    assert seed["snapshot"]["financial"] == observed["after"]["financial"] == {}
    assert not list((root / "data/jobs").glob("*/financial.sqlite"))
    assert observed["dispatcher_calls"] == []


def test_cancelled_partial_archive_survives_another_restart(scenario):
    _, _, run = scenario
    seed = run("seed_after", expected_exit=86)
    cancelled = run("cancel")
    restarted = run("observe", "restart_cancelled")
    for value in (cancelled, restarted):
        assert_consistent(value, 1, "cancelled")
        assert response(value, "/api/tasks/1/run", "POST")["status"] == 409
        assert value["dispatcher_calls"] == []
        assert value["after"]["financial"] == seed["snapshot"]["financial"]


def test_explicit_retry_retains_original_receipt_and_replays_idempotently(scenario):
    _, _, run = scenario
    seed = run("seed_after", expected_exit=86)
    observed = run("retry")
    assert_consistent(observed, 2, "completed")
    assert receipts(observed["after"])[0] == receipts(seed["snapshot"])[0]
    report = response(observed, "/api/tasks/1/report")["body"]
    submits = [item for item in report["trace"] if item["tool"] == "submit_to_oa"]
    assert len(submits) == 2
    assert submits[0]["envelope"]["result"]["idempotent_replay"] is True
    assert len({item["operation_id"] for item in receipts(observed["after"])}) == 2


def test_batch_crash_report_is_interim_and_displays_durable_receipt(scenario):
    _, _, run = scenario
    seed = run("seed_batch", expected_exit=86)
    observed = run("observe_batch")
    assert_consistent(observed, 1, "failed")
    batch = response(observed, f"/api/batches/{seed['batch_id']}")["body"]
    assert batch["status"] == "failed"
    assert batch["archive_receipts"] == 1 and batch["matched_rows"] == 0
    summary = {row[0]: row[1] for row in observed["workbook"]["Summary"] if row[0]}
    assert str(summary["Report status"]).startswith("INTERIM")
    assert summary["Unique archive receipts"] == 1
    rows = observed["workbook"]["Reconciliation"][5:]
    assert len(rows) == 2
    assert rows[0][0] == "Partial archive" and rows[0][22] == observed["after"]["central"]["archive"][0]["id"]
    assert rows[1][0] != "Reconciled" and not rows[1][22]
    assert observed["dispatcher_calls"] == []


@pytest.mark.parametrize("damage", ["task", "task_instruction", "old_revision", "future_revision", "operation", "source_row", "payload_hash", "payload_content", "approved_field", "review_status_field", "record_type", "central_content", "central_identity"])
def test_recovery_rejects_identity_or_content_conflict_without_hiding_it(scenario, damage):
    root, evidence, run = scenario
    seed = run("seed_after", expected_exit=86)
    financial = root / "data/jobs/1/financial.sqlite"
    if damage.startswith("central_"):
        row = receipts(seed["snapshot"])[0]
        with sqlite3.connect(root / "data/finance-flow.sqlite") as db:
            db.execute("INSERT INTO archive VALUES(?,?,?,?,?,?)", (
                "FF-00001-00001", 1, row["operation_id"] if damage == "central_content" else "conflicting-operation",
                row["record_id"], '{"conflicting":"synthetic payload"}' if damage == "central_content" else row["payload"], "do-not-rewrite"))
    else:
        with sqlite3.connect(financial) as db:
            if damage == "task":
                db.execute("UPDATE oa_reconciliation_records SET task_id=2")
            elif damage == "task_instruction":
                db.execute("UPDATE tasks SET description='Different synthetic instruction'")
            elif damage in ("old_revision", "future_revision", "operation", "source_row"):
                operation = {"old_revision": "task-1-revision-0:result:2", "future_revision": "task-1-revision-2:result:2", "operation": "task-2-revision-1:result:2", "source_row": "task-1-revision-1:result:999"}[damage]
                db.execute("UPDATE oa_reconciliation_records SET operation_id=?", (operation,))
            elif damage in ("payload_hash", "payload_content", "approved_field", "review_status_field"):
                payload = json.loads(receipts(seed["snapshot"])[0]["payload"])
                if damage == "approved_field":
                    payload["approved"] = True
                elif damage == "review_status_field":
                    payload["review_status"] = "approved"
                else:
                    payload["amount"] = "999.99"
                if damage != "payload_hash":
                    from backend.app.tools.oa_submitter import _content_hash
                    db.execute("UPDATE oa_reconciliation_records SET payload=?,content_hash=?", (json.dumps(payload, sort_keys=True), _content_hash(payload)))
                else:
                    db.execute("UPDATE oa_reconciliation_records SET payload=?", (json.dumps(payload, sort_keys=True),))
            else:
                db.execute("UPDATE oa_reconciliation_records SET record_type='reconciliation_exception'")
    damaged = snapshot(root)
    save(evidence / "synthetic_damage_before_recovery.json", damaged)
    observed = run("observe_conflict")
    for path in ("/api/tasks/1", "/api/tasks/1/report", "/api/archive"):
        assert response(observed, path)["status"] == 409, response(observed, path)
    assert response(observed, "/api/tasks/2")["status"] == 200
    assert response(observed, "/api/tasks/2")["body"]["status"] == "pending"
    assert observed["after"]["financial"] == damaged["financial"]
    assert observed["after"]["financial_sha256"] == damaged["financial_sha256"]
    assert observed["after"]["central"]["archive"] == damaged["central"]["archive"]
    assert observed["after"]["central"]["jobs"][0]["status"] == "failed"
    assert observed["dispatcher_calls"] == []


def test_missing_child_database_with_existing_archive_is_not_silently_accepted(scenario):
    root, evidence, run = scenario
    seeded = run("seed_after", expected_exit=86)
    receipt = receipts(seeded["snapshot"])[0]
    with sqlite3.connect(root / "data/finance-flow.sqlite") as db:
        db.execute("INSERT INTO archive VALUES(?,?,?,?,?,?)", (
            "FF-00001-00001", 1, receipt["operation_id"], receipt["record_id"], receipt["payload"], "retained-original-time"))
    financial = root / "data/jobs/1/financial.sqlite"
    # Preserve the synthetic original instead of deleting evidence while making
    # the application's expected child DB genuinely absent.
    retained = root / "retained_missing_financial.sqlite"
    financial.rename(retained)
    damaged = snapshot(root)
    save(evidence / "missing_database_before_recovery.json", {"snapshot": damaged,
        "retained_db_sha256": hashlib.sha256(retained.read_bytes()).hexdigest()})
    observed = run("observe_conflict")
    assert not financial.exists()
    for path in ("/api/tasks/1", "/api/tasks/1/report", "/api/archive"):
        assert response(observed, path)["status"] == 409
    assert response(observed, "/api/tasks/2")["status"] == 200
    assert observed["after"]["central"]["archive"] == damaged["central"]["archive"]
    assert observed["dispatcher_calls"] == []


def test_normal_sync_cannot_silently_ignore_a_central_payload_conflict(scenario):
    _, _, run = scenario
    seeded = run("seed_live_conflict")
    state = seeded["snapshot"]
    assert len(receipts(state)) == 2
    assert state["central"]["jobs"][0]["status"] == "failed"
    assert len(state["central"]["archive"]) == 1
    assert state["central"]["archive"][0]["payload_json"] == '{"conflicting":"synthetic central payload"}'
    observed = run("observe_conflict")
    assert response(observed, "/api/tasks/1")["status"] == 409
    assert observed["after"]["central"]["archive"] == state["central"]["archive"]


def quarantine_write_snapshot(root):
    """Capture all durable bytes and business rows, without exporting auth data."""
    data = root / "data"
    value = snapshot(root)
    value["central"] = read_rows(data / "finance-flow.sqlite", CENTRAL_TABLES + (
        "files", "settings", "batch_entries", "commands", "data_chats", "data_turns",
        "data_artifacts", "sqlite_sequence"))
    value["directories"] = sorted(path.relative_to(data).as_posix() for path in data.rglob("*") if path.is_dir())
    value["files"] = {path.relative_to(data).as_posix(): {
        "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in sorted(data.rglob("*")) if path.is_file()}
    return value


@pytest.mark.parametrize("operation", ["cancel", "review"])
def test_quarantined_http_write_has_no_side_effects_and_healthy_task_works(tmp_path, request, operation):
    from fastapi.testclient import TestClient
    from product.api import create_app
    import product.service as product_service

    expected = os.getenv("R2B_EXPECT_SOURCE")
    if expected:
        assert Path(product_service.__file__).resolve().is_relative_to(Path(expected).resolve())
    evidence = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
    evidence.mkdir(parents=True, exist_ok=False)
    root = tmp_path / "quarantine"
    data = root / "data"
    credential = {"username": "Synthetic quarantine reviewer", "password": secrets.token_urlsafe(24)}
    options = {"base_url": "http://127.0.0.1", "headers": {"X-Requested-With": "FinanceFlow"}}
    app = create_app(data)
    service = app.state.service

    def make(client, title, execute):
        identifiers = []
        for role in ("source", "reference"):
            content = csv_bytes()
            if operation == "review" and role == "source":
                content = content.replace(b"100.10", b"125.10")
            uploaded = client.post("/api/files", files={"file": (role + ".csv", content)}, data={"role": role})
            assert uploaded.status_code == 201, uploaded.text
            identifiers.append(uploaded.json()["id"])
            (evidence / (title + "-" + role + ".csv")).write_bytes(content)
        created = client.post("/api/tasks", json={"title": title, "instruction": "Reconcile synthetic quarantine inputs",
            "source_id": identifiers[0], "reference_id": identifiers[1], "ai": False})
        assert created.status_code == 201, created.text
        identifier = created.json()["id"]
        if execute:
            for step in ("plan", "run"):
                scheduled = client.post(f"/api/tasks/{identifier}/{step}")
                assert scheduled.status_code == 200, scheduled.text
                service.future.result(timeout=30)
        detail = client.get(f"/api/tasks/{identifier}")
        assert detail.status_code == 200, detail.text
        return detail.json()

    def review_payload(detail):
        assert detail["status"] == "waiting_confirmation"
        assert len(detail["issues"]) == 1 and detail["issues"][0]["can_correct"]
        return {"revision": detail["revision"], "evidence_digest": detail["evidence_digest"],
            "changes": [{"issue_id": detail["issues"][0]["id"], "mode": "reference", "value": None}],
            "reason": "Synthetic reviewer verified the immutable reference."}

    with TestClient(app, **options) as client:
        assert client.post("/api/setup", json=credential).status_code == 200
        affected = make(client, "affected", execute=True)
        healthy = make(client, "healthy", execute=operation == "review")
        identifier = affected["id"]
        if operation == "cancel":
            assert affected["status"] == "completed" and affected["archive_count"] == 2
            # Model a failed task after durable receipts, then corrupt only its
            # synthetic central mirror. The real financial receipts remain intact.
            job, state = service.get_job(identifier)
            service.store.save_job(job, state, "failed")
            with service.store.connect() as db:
                db.execute("UPDATE archive SET payload_json=? WHERE job_id=?",
                           ('{"conflicting":"synthetic central payload"}', identifier))
            payload = None
        else:
            payload = review_payload(affected)
            with service.store.connect() as db:
                db.execute("INSERT INTO archive VALUES(?,?,?,?,?,?)", (
                    f"FF-{identifier:05d}-99999", identifier, f"task-{identifier}-revision-1:result:99999",
                    "synthetic-orphan-receipt", '{"synthetic":"orphan mirror"}', "preserve-original-time"))
        save(evidence / "seed.json", {"test": request.node.nodeid, "source": product_service.__file__,
            "operation": operation, "affected": affected, "healthy": healthy, "review_payload": payload,
            "snapshot": quarantine_write_snapshot(root)})

    # A fresh real application detects the conflict at startup; no error-map mock.
    app = create_app(data)
    service = app.state.service
    with TestClient(app, **options) as client:
        assert client.post("/api/login", json=credential).status_code == 200
        assert identifier in service.archive_recovery_errors
        assert healthy["id"] not in service.archive_recovery_errors
        before = quarantine_write_snapshot(root)
        reply = client.post(f"/api/tasks/{identifier}/{operation}", **({"json": payload} if payload else {}))
        after = quarantine_write_snapshot(root)
        repeated = client.post(f"/api/tasks/{identifier}/{operation}", **({"json": payload} if payload else {}))
        after_repeat = quarantine_write_snapshot(root)
        save(evidence / "quarantine_write.json", {"operation": operation, "conflicts": service.archive_recovery_errors,
            "http_status": reply.status_code, "response": reply.json(), "before": before, "after": after,
            "repeat_http_status": repeated.status_code, "repeat_response": repeated.json(), "after_repeat": after_repeat,
            "unchanged": before == after == after_repeat, "cancel_signal": service.cancel_signal.is_set()})

        healthy_id = healthy["id"]
        healthy_reply = client.post(f"/api/tasks/{healthy_id}/{operation}",
            **({"json": review_payload(healthy)} if operation == "review" else {}))
        assert healthy_reply.status_code == 200, healthy_reply.text
        revised = healthy_reply.json()
        if operation == "review":
            assert revised["revision"] == 2 and not revised["issues"] and len(revised["decisions"]) == 1
            assert client.post(f"/api/tasks/{healthy_id}/run").status_code == 200
            service.future.result(timeout=30)
        final = client.get(f"/api/tasks/{healthy_id}")
        assert final.status_code == 200, final.text
        final = final.json()
        assert final["status"] == ("cancelled" if operation == "cancel" else "completed")
        assert final["archive_count"] == (0 if operation == "cancel" else 2)
        if operation == "cancel":
            assert final["stage"] == "Cancelled" and not final["cancel_requested"]
        after_healthy = quarantine_write_snapshot(root)
        for table in ("jobs", "events", "decisions", "archive"):
            field = "id" if table == "jobs" else "job_id"
            assert [row for row in after_healthy["central"][table] if row[field] == identifier] == [
                row for row in after_repeat["central"][table] if row[field] == identifier]
        assert after_healthy["financial"].get(str(identifier)) == after_repeat["financial"].get(str(identifier))
        assert {p: v for p, v in after_healthy["files"].items() if p.startswith(f"jobs/{identifier}/")} == {
            p: v for p, v in after_repeat["files"].items() if p.startswith(f"jobs/{identifier}/")}
        save(evidence / "healthy_write.json", {"http_status": healthy_reply.status_code, "revised": revised,
            "final": final, "after": after_healthy, "affected_task_unchanged_by_healthy_operation": True})

        assert reply.status_code == repeated.status_code == 409
        assert "Archive recovery conflict" in reply.json()["detail"]
        assert not service.cancel_signal.is_set()
        assert after == before, "Quarantined HTTP write changed durable database rows or file contents"
        assert after_repeat == before, "Repeated rejected write changed durable state"


if __name__ == "__main__":
    assert len(sys.argv) == 6 and sys.argv[1] == "--worker"
    worker(*sys.argv[2:])
