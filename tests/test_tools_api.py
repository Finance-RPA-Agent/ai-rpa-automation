"""HTTP integration tests for the /tools FastAPI entry points."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.database import SessionLocal
from backend.app.main import app
from backend.app.models import FinancialRecord, Task

client = TestClient(app)

CORE_FIELDS = [
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
]

NORMAL_ROW = [
    "SUP-001",
    "ABC Ltd",
    "ORD-1001",
    "5000.00",
    "2026-09-18",
    "pending",
    "active",
]


def _csv_bytes(rows):
    import io
    import csv

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _upload(name, content, content_type="text/csv"):
    return client.post(
        "/tools/files",
        files={"file": (name, content, content_type)},
    )


def test_list_tools_endpoint():
    response = client.get("/tools")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    names = {tool["name"] for tool in body["result"]["tools"]}
    assert names == {
        "read_data_file",
        "validate_data",
        "query_bi",
        "submit_to_oa",
    }


def test_upload_and_read_through_http():
    upload = _upload("orders.csv", _csv_bytes([CORE_FIELDS, NORMAL_ROW]))

    assert upload.status_code == 200
    upload_body = upload.json()
    assert upload_body["status"] == "success"
    file_reference = upload_body["result"]

    read = client.post(
        "/tools/execute",
        json={
            "tool": "read_data_file",
            "arguments": {"file_path": file_reference["file_path"]},
        },
    )

    assert read.status_code == 200
    read_body = read.json()
    assert read_body["status"] == "success"
    assert read_body["result"]["row_count"] == 1
    assert (
        read_body["result"]["records"][0]["data"]["supplier_id"] == "SUP-001"
    )


def test_same_name_upload_does_not_overwrite():
    first = _upload(
        "same-name.csv",
        _csv_bytes([CORE_FIELDS, NORMAL_ROW]),
    ).json()["result"]
    second_row = list(NORMAL_ROW)
    second_row[0] = "SUP-002"
    second_row[2] = "ORD-2001"
    second = _upload(
        "same-name.csv",
        _csv_bytes([CORE_FIELDS, second_row]),
    ).json()["result"]

    assert first["file_id"] != second["file_id"]
    assert first["file_path"] != second["file_path"]

    first_read = client.post(
        "/tools/execute",
        json={
            "tool": "read_data_file",
            "arguments": {"file_path": first["file_path"]},
        },
    ).json()
    second_read = client.post(
        "/tools/execute",
        json={
            "tool": "read_data_file",
            "arguments": {"file_path": second["file_path"]},
        },
    ).json()

    assert (
        first_read["result"]["records"][0]["data"]["supplier_id"]
        == "SUP-001"
    )
    assert (
        second_read["result"]["records"][0]["data"]["supplier_id"]
        == "SUP-002"
    )


def test_upload_rejects_unsupported_extension():
    response = _upload("notes.txt", b"hello")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_empty_file():
    response = _upload("empty.csv", b"")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "EMPTY_FILE"


def test_unknown_tool_returns_tool_envelope_not_http_error():
    response = client.post(
        "/tools/execute",
        json={"tool": "drop_database", "arguments": {}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error_code"] == "UNKNOWN_TOOL"


def test_malformed_request_uses_http_422():
    response = client.post("/tools/execute", json={"arguments": {}})

    assert response.status_code == 422


def test_query_bi_over_http():
    with SessionLocal() as session:
        existing = (
            session.query(FinancialRecord)
            .filter(FinancialRecord.order_id == "HTTP-ORD-1")
            .first()
        )
        if existing is None:
            session.add(
                FinancialRecord(
                    supplier_id="SUP-HTTP",
                    supplier_name="HTTP Ltd",
                    order_id="HTTP-ORD-1",
                    amount="321.00",
                    date="2026-09-18",
                    payment_status="pending",
                    record_status="active",
                    source="test",
                )
            )
            session.commit()

    response = client.post(
        "/tools/execute",
        json={
            "tool": "query_bi",
            "arguments": {"order_id": "HTTP-ORD-1"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["count"] == 1
    assert body["result"]["records"][0]["supplier_id"] == "SUP-HTTP"


def test_query_bi_empty_result_over_http_is_success():
    response = client.post(
        "/tools/execute",
        json={
            "tool": "query_bi",
            "arguments": {"order_id": "NO-SUCH-ORDER"},
        },
    )

    body = response.json()
    assert body["status"] == "success"
    assert body["result"]["records"] == []


def test_validate_over_http_returns_business_issues():
    upload = _upload(
        "validate-http.csv",
        _csv_bytes([CORE_FIELDS, ["SUP-001", "", "ORD-1", "bad", "bad", "", ""]]),
    ).json()["result"]

    response = client.post(
        "/tools/execute",
        json={
            "tool": "validate_data",
            "arguments": {"file_path": upload["file_path"]},
        },
    )

    body = response.json()
    assert body["status"] == "success"
    issues = body["result"]["issues"]
    assert len(issues) >= 4
    assert body["result"]["invalid_rows"] == 1


def test_submit_and_read_back_over_http():
    with SessionLocal() as session:
        task = Task(
            description="HTTP OA task",
            status="running",
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        task_id = task.id

    submit = client.post(
        "/tools/execute",
        json={
            "tool": "submit_to_oa",
            "arguments": {
                "task_id": task_id,
                "record_type": "reconciliation_result",
                "operation_id": "http-op-1",
                "data": {
                    "supplier_id": "SUP-001",
                    "supplier_name": "ABC Ltd",
                    "order_id": "ORD-1001",
                    "amount": 5000.00,
                    "date": "2026-09-18",
                    "payment_status": "pending",
                    "record_status": "matched",
                },
            },
        },
    )

    assert submit.status_code == 200
    submit_body = submit.json()
    assert submit_body["status"] == "success"
    record_id = submit_body["result"]["record_id"]

    read = client.get(f"/tools/oa/records/{record_id}")
    assert read.status_code == 200
    read_body = read.json()
    assert read_body["status"] == "success"
    record = read_body["result"]["record"]
    assert record["task_id"] == task_id
    assert record["data"]["order_id"] == "ORD-1001"

    listing = client.get(f"/tools/oa/records?task_id={task_id}")
    listing_body = listing.json()
    assert listing_body["status"] == "success"
    assert listing_body["result"]["count"] >= 1
