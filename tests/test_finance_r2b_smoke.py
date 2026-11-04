"""Fresh deterministic financial smoke: real API, SQLite, receipts and exports."""
import copy
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from product.api import create_app
import product.service as service_module
from product.service import FIELDS


OWNER = "R2B synthetic reviewer"
REASON = "Explicitly compared each synthetic source finding with the frozen reference."


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def csv_content(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Smoke:
    def __init__(self, client, service, artifacts):
        self.client, self.service, self.artifacts = client, service, artifacts
        self.http = []

    def call(self, method, path, **kwargs):
        response = getattr(self.client, method)(path, **kwargs)
        record = {"method": method, "path": path, "http_status": response.status_code}
        if "json" in kwargs:
            record["request"] = kwargs["json"]
        if "application/json" in response.headers.get("content-type", ""):
            record["response"] = response.json()
        else:
            record.update(bytes=len(response.content), sha256=hashlib.sha256(response.content).hexdigest())
        self.http.append(record)
        save(self.artifacts / "http.json", self.http)
        return response

    def operation(self, path, expected=200):
        response = self.call("post", path)
        assert response.status_code == expected, response.text
        self.service.future.result(timeout=90)

    def snapshot(self, name):
        tables = ("files", "jobs", "events", "decisions", "archive", "batches", "batch_entries", "batch_jobs")
        captured = {"product": {table: self.service.store.all("SELECT * FROM " + table) for table in tables},
                    "job_databases": {}, "files": {}}
        for path in sorted((self.service.store.root / "jobs").glob("*/financial.sqlite")):
            with sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True) as database:
                database.row_factory = sqlite3.Row
                captured["job_databases"][path.parent.name] = {
                    table: [dict(row) for row in database.execute("SELECT * FROM " + table)]
                    for table in ("tasks", "bi_financial_records", "oa_reconciliation_records")}
        for folder in ("files", "jobs"):
            for path in (self.service.store.root / folder).rglob("*"):
                if path.is_file():
                    captured["files"][path.relative_to(self.service.store.root).as_posix()] = sha(path)
        save(self.artifacts / (name + ".json"), captured)
        return captured

    def workbook(self, batch_id, name):
        response = self.call("get", f"/api/batches/{batch_id}/report")
        assert response.status_code == 200, response.text
        path = self.artifacts / (name + ".xlsx")
        path.write_bytes(response.content)
        workbook = load_workbook(path, data_only=False)
        save(self.artifacts / (name + "_cells.json"), {
            sheet.title: [{"cell": cell.coordinate, "value": cell.value, "type": cell.data_type,
                           "number_format": cell.number_format}
                          for row in sheet for cell in row if cell.value is not None]
            for sheet in workbook})
        assert not any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
        return workbook


@pytest.fixture
def smoke(tmp_path, request):
    expected = os.getenv("R2B_EXPECT_SOURCE")
    if expected:
        assert Path(service_module.__file__).resolve().is_relative_to(Path(expected).resolve())
    artifacts = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / (
        "smoke_" + hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12])
    artifacts.mkdir(parents=True)
    save(artifacts / "identity.json", {"test": request.node.nodeid, "source": service_module.__file__,
                                      "transport": "real in-process FastAPI ASGI", "plan_mode": "deterministic"})
    app = create_app(tmp_path / "workspace")
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        assert client.post("/api/setup", json={"username": OWNER, "password": secrets.token_urlsafe(24)}).status_code == 200
        harness = Smoke(client, app.state.service, artifacts)
        try:
            yield harness
        finally:
            harness.service.executor.shutdown(wait=True)
            harness.snapshot("on_exit")


def synthetic_rows(size):
    reference = [dict(zip(FIELDS, [f"{index:04d}", f"Synthetic Supplier {index:03d}", f"{index:06d}",
                                  f"{Decimal(100 + index) + Decimal('0.25'):.2f}",
                                  f"2026-10-{1 + index % 28:02d}", "pending", "active"]))
                 for index in range(1, size + 1)]
    source = copy.deepcopy(reference)
    source[0]["amount"] = "126.25"
    source[1]["payment_status"] = "paid"
    source[2]["record_status"] = "inactive"
    return source, reference


def assert_workbook_rows(smoke, workbook, source, reference, *, final, receipt_map):
    sheet = workbook["Reconciliation"]
    headers = [cell.value for cell in sheet[5]]
    rows = [dict(zip(headers, values)) for values in sheet.iter_rows(min_row=6, values_only=True)]
    save(smoke.artifacts / ("final_rows.json" if final else "interim_rows.json"), rows)
    assert len(rows) == len(source)
    assert [row["Source row"] for row in rows] == list(range(2, len(source) + 2))
    for index, (row, original, trusted) in enumerate(zip(rows, source, reference)):
        current = trusted if final else original
        assert row["Supplier ID"] == original["supplier_id"]
        assert row["Order ID"] == original["order_id"]
        assert Decimal(str(row["Source amount"])) == Decimal(original["amount"])
        assert Decimal(str(row["Current amount"])) == Decimal(current["amount"])
        assert Decimal(str(row["BI amount"])) == Decimal(trusted["amount"])
        assert Decimal(str(row["Difference"])) == Decimal(current["amount"]) - Decimal(trusted["amount"])
        for label, field in (("payment", "payment_status"), ("record status", "record_status")):
            assert row["Source " + label] == original[field]
            assert row["Current " + label] == current[field]
            assert row["BI " + label] == trusted[field]
        assert row["Source supplier name"] == original["supplier_name"]
        assert row["Current supplier name"] == current["supplier_name"]
        assert row["Source date"] == original["date"]
        assert row["Current date"] == current["date"]
        assert row["Task"]
        if final or index >= 3:
            assert row["Result"] == "Reconciled"
            receipt = receipt_map[row["Archive receipt"]]
            expected = dict(trusted, record_status="matched")
            assert receipt["data"] == expected
            assert row["Task"] == f"FF-{receipt['job_id']:05d}"
        else:
            assert row["Result"] == "Needs review"
            assert not row["Archive receipt"]
            assert row["Finding / reason"]
    visible_receipts = [row["Archive receipt"] for row in rows if row["Archive receipt"]]
    assert len(visible_receipts) == len(set(visible_receipts)) == (len(source) if final else len(source) - 3)
    summary = {workbook["Summary"].cell(row, 1).value: workbook["Summary"].cell(row, 2).value for row in range(4, 17)}
    assert summary["Report status"] == ("FINAL - completed" if final else "INTERIM - needs review")
    assert summary["Input source rows"] == len(source)
    assert summary["Completed input rows"] == (len(source) if final else len(source) - 3)
    assert summary["Rows not completed"] == (0 if final else 3)
    assert summary["Unique archive receipts"] == len(visible_receipts)
    if final:
        assert workbook["Exceptions"]["A6"].value == "No outstanding items."
        history = list(workbook["Review history"].iter_rows(min_row=6, values_only=True))
        assert len(history) == 3
        assert {row[2] for row in history} == {2, 3, 4}
        assert all(row[8] == OWNER and row[9] == REASON for row in history)
    else:
        assert len(list(workbook["Exceptions"].iter_rows(min_row=6, values_only=True))) == 3


@pytest.mark.parametrize("size", [4, 100])
def test_real_financial_flow_all_rows_and_artifacts(smoke, size):
    source, reference = synthetic_rows(size)
    inbox, bi = smoke.artifacts / "inputs", smoke.artifacts / "reference"
    inbox.mkdir()
    bi.mkdir()
    source_path, reference_path = inbox / "orders.csv", bi / "reference.csv"
    source_path.write_bytes(csv_content(source))
    reference_path.write_bytes(csv_content(reference))
    original_hashes = {str(path): sha(path) for path in (source_path, reference_path)}
    source, reference = read_csv(source_path), read_csv(reference_path)
    response = smoke.call("post", "/api/batches/scan", json={"folder": str(inbox), "bi_folder": str(bi)})
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    smoke.service.future.result(timeout=90)
    scanned = smoke.call("get", f"/api/batches/{batch_id}").json()
    assert scanned["runnable_tables"] == 1 and scanned["scan_complete"]
    smoke.operation(f"/api/batches/{batch_id}/run")
    interim = smoke.call("get", f"/api/batches/{batch_id}").json()
    assert interim["status"] == "needs_review"
    assert (interim["input_rows"], interim["matched_rows"], interim["archive_receipts"], interim["unresolved_rows"]) == (size, size-3, size-3, 3)
    assert len(interim["review_tasks"]) == 1
    assert smoke.service.store.all("SELECT * FROM decisions") == []
    interim_archive = smoke.call("get", "/api/archive").json()["records"]
    assert len(interim_archive) == size - 3
    workbook = smoke.workbook(batch_id, "interim")
    try:
        assert_workbook_rows(smoke, workbook, source, reference, final=False,
                             receipt_map={row["id"]: row for row in interim_archive})
    finally:
        workbook.close()
    smoke.snapshot("interim_database")

    review_id = interim["review_tasks"][0]["job_id"]
    waiting = smoke.call("get", f"/api/tasks/{review_id}").json()
    assert waiting["status"] == "waiting_confirmation" and waiting["issue_count"] == 3
    assert waiting["archive_count"] == 0 and not waiting["decisions"]
    before = smoke.snapshot("before_blocked_run")
    assert smoke.call("post", f"/api/tasks/{review_id}/run").status_code == 409
    assert smoke.snapshot("after_blocked_run") == before
    assert {issue["field"] for issue in waiting["issues"]} == {"amount", "payment_status", "record_status"}
    assert all(issue["can_correct"] for issue in waiting["issues"])
    payload = {"revision": waiting["revision"], "evidence_digest": waiting["evidence_digest"],
               "changes": [{"issue_id": issue["id"], "mode": "reference", "value": None} for issue in waiting["issues"]],
               "reason": REASON}
    response = smoke.call("post", f"/api/tasks/{review_id}/review", json=payload)
    assert response.status_code == 200, response.text
    corrected = response.json()
    assert corrected["revision"] == waiting["revision"] + 1
    assert corrected["status"] == "waiting_confirmation" and corrected["issues"] == []
    assert corrected["archive_count"] == 0 and len(corrected["decisions"]) == 1
    decision = corrected["decisions"][0]
    assert decision["actor"] == OWNER and decision["reason"] == REASON
    assert decision["evidence_digest"] == waiting["evidence_digest"]
    assert len(decision["changes"]) == 3
    smoke.operation(f"/api/tasks/{review_id}/run")
    final = smoke.call("get", f"/api/batches/{batch_id}").json()
    assert final["status"] == "completed"
    assert (final["input_rows"], final["matched_rows"], final["archive_receipts"], final["unresolved_rows"]) == (size, size, size, 0)
    final_archive = smoke.call("get", "/api/archive").json()["records"]
    assert len(final_archive) == size
    assert len({row["id"] for row in final_archive}) == size
    # OA identifiers are scoped to each task's separate financial database.
    assert len({(row["job_id"], row["receipt_id"]) for row in final_archive}) == size
    assert len({row["operation_id"] for row in final_archive}) == size
    workbook = smoke.workbook(batch_id, "final")
    try:
        assert_workbook_rows(smoke, workbook, source, reference, final=True,
                             receipt_map={row["id"]: row for row in final_archive})
    finally:
        workbook.close()

    database = smoke.snapshot("final_database")
    associations = database["product"]["batch_jobs"]
    assert len(associations) == 2
    assert sorted(origin for row in associations for origin in json.loads(row["rows_json"])) == list(range(2, size+2))
    receipt_count = 0
    for association in associations:
        job_id = association["job_id"]
        origins = json.loads(association["rows_json"])
        expected_rows = [reference[origin-2] for origin in origins]
        response = smoke.call("get", f"/api/tasks/{job_id}/report")
        assert response.status_code == 200, response.text
        report_path = smoke.artifacts / f"task-{job_id}-report.json"
        report_path.write_bytes(response.content)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["report_kind"] == "final" and report["status"] == "completed"
        assert report["plan"]["mode"] == "deterministic" and report["ai"] is False
        assert report["row_count"] == report["archive_count"] == len(origins)
        assert report["issues"] == []
        assert [row["data"] for row in report["records"]] == expected_rows
        assert Decimal(report["amount"]) == sum((Decimal(row["amount"]) for row in expected_rows), Decimal(0))
        assert [trace["tool"] for trace in report["trace"]].count("submit_to_oa") == len(origins)
        response = smoke.call("get", f"/api/tasks/{job_id}/export")
        assert response.status_code == 200, response.text
        csv_path = smoke.artifacts / f"task-{job_id}-reconciled.csv"
        csv_path.write_bytes(response.content)
        assert read_csv(csv_path) == expected_rows
        receipts = database["job_databases"][str(job_id)]["oa_reconciliation_records"]
        receipt_count += len(receipts)
        assert len(receipts) == len(origins)
        assert len({receipt["operation_id"] for receipt in receipts}) == len(origins)
        assert len({receipt["record_id"] for receipt in receipts}) == len(origins)
        central = {row["operation_id"]: row for row in final_archive if row["job_id"] == job_id}
        for index, expected_row in enumerate(expected_rows, 2):
            operation = f"task-{job_id}-revision-{report['revision']}:result:{index}"
            receipt = next(row for row in receipts if row["operation_id"] == operation)
            expected_payload = dict(expected_row, record_status="matched")
            assert receipt["task_id"] == job_id and receipt["record_type"] == "reconciliation_result"
            assert json.loads(receipt["payload"]) == central[operation]["data"] == expected_payload
            assert receipt["record_id"] == central[operation]["receipt_id"]
        before = smoke.snapshot(f"before_completed_replay_{job_id}")
        assert smoke.call("post", f"/api/tasks/{job_id}/run").status_code == 409
        assert smoke.snapshot(f"after_completed_replay_{job_id}") == before
    assert receipt_count == size
    assert {str(path): sha(path) for path in (source_path, reference_path)} == original_hashes
    for row in database["product"]["files"]:
        assert sha(smoke.service.path(row["raw_path"])) == row["sha256"]
        assert sha(smoke.service.path(row["canonical_path"])) == row["canonical_sha256"]
    save(smoke.artifacts / "smoke_summary.json", {"rows": size, "interim_receipts": size-3,
         "interim_unresolved": 3, "final_receipts": size, "final_unresolved": 0,
         "original_hashes": original_hashes, "checked_json_csv_tasks": len(associations),
         "checked_excel_rows_per_report": size, "checked_excel_reports": 2})
