"""Tests for the submit_to_oa tool and OA read-back helpers."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from backend.app.models import OaReconciliationRecord, Task, TaskLog
from backend.app.tools import (
    list_oa_records,
    read_oa_record,
    submit_to_oa,
)

RESULT_DATA = {
    "supplier_id": "SUP-001",
    "supplier_name": "ABC Ltd",
    "order_id": "ORD-1001",
    "amount": 5000.00,
    "date": "2026-09-18",
    "payment_status": "pending",
    "record_status": "matched",
}

EXCEPTION_DATA = {
    "supplier_id": "SUP-001",
    "supplier_name": "ABC Ltd",
    "order_id": "ORD-1001",
    "issue_type": "amount_mismatch",
    "excel_amount": 5200.00,
    "bi_amount": 5000.00,
}


def _task(db):
    task = Task(description="Reconcile supplier orders", status="running")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def test_submit_result_and_read_back(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-normal-1",
        db=db_session,
    )

    assert response["status"] == "success"
    result = response["result"]
    assert result["submitted"] is True
    assert result["record_type"] == "reconciliation_result"
    assert result["record_id"].startswith("OA-")
    assert result["idempotent_replay"] is False
    assert result["review_status"] == "archived"

    read = read_oa_record(record_id=result["record_id"], db=db_session)
    assert read["status"] == "success"
    record = read["result"]["record"]
    assert record["task_id"] == task.id
    assert record["record_type"] == "reconciliation_result"
    assert record["data"]["supplier_id"] == "SUP-001"
    assert record["data"]["order_id"] == "ORD-1001"
    assert float(record["data"]["amount"]) == 5000.00
    assert record["data"]["date"] == "2026-09-18"
    assert record["data"]["record_status"] == "matched"


def test_submit_exception_keeps_pending_review_semantics(db_session):
    task = _task(db_session)
    data = dict(EXCEPTION_DATA, confirmed=True, review_status="approved")

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_exception",
        data=data,
        operation_id="op-conflict-1",
        db=db_session,
    )

    assert response["status"] == "success"
    result = response["result"]
    assert result["review_status"] == "pending_review"
    assert "confirmed" in result["ignored_fields"]
    assert "review_status" in result["ignored_fields"]

    read = read_oa_record(record_id=result["record_id"], db=db_session)
    record = read["result"]["record"]
    assert record["review_status"] == "pending_review"
    stored = record["data"]
    assert "confirmed" not in stored
    assert stored.get("review_status") == "pending_review"


def test_repeat_same_operation_and_content_is_idempotent(db_session):
    task = _task(db_session)

    first = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-same",
        db=db_session,
    )
    second = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=dict(RESULT_DATA),
        operation_id="op-same",
        db=db_session,
    )

    assert first["result"]["record_id"] == second["result"]["record_id"]
    assert second["result"]["idempotent_replay"] is True
    count = db_session.query(OaReconciliationRecord).count()
    assert count == 1


def test_same_operation_with_different_content_conflicts(db_session):
    task = _task(db_session)

    first = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-conflict",
        db=db_session,
    )
    assert first["status"] == "success"

    changed = dict(RESULT_DATA, amount=9999.00)
    second = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=changed,
        operation_id="op-conflict",
        db=db_session,
    )

    assert second["status"] == "error"
    assert second["error_code"] == "CONFLICTING_OPERATION"
    assert db_session.query(OaReconciliationRecord).count() == 1


def test_without_operation_id_identical_content_is_replay(db_session):
    task = _task(db_session)

    first = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        db=db_session,
    )
    reordered = {
        "record_status": "matched",
        "payment_status": "pending",
        "date": "2026-09-18",
        "amount": "5000.0",
        "order_id": "ORD-1001",
        "supplier_name": "ABC Ltd",
        "supplier_id": "SUP-001",
    }
    second = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=reordered,
        db=db_session,
    )

    assert second["status"] == "success"
    assert second["result"]["idempotent_replay"] is True
    assert first["result"]["record_id"] == second["result"]["record_id"]
    assert db_session.query(OaReconciliationRecord).count() == 1


def test_without_operation_id_different_content_creates_new_record(
    db_session,
):
    task = _task(db_session)

    submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        db=db_session,
    )
    submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=dict(RESULT_DATA, order_id="ORD-1002"),
        db=db_session,
    )

    assert db_session.query(OaReconciliationRecord).count() == 2


def test_submit_to_missing_task_is_rejected(db_session):
    response = submit_to_oa(
        task_id=987654,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "TASK_NOT_FOUND"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_invalid_record_type_is_rejected(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="unpaid_payment",
        data=RESULT_DATA,
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_RECORD_TYPE"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_missing_data_fields_leave_no_partial_record(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data={"supplier_id": "SUP-001"},
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_DATA"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_unresolved_result_cannot_be_submitted_as_matched(db_session):
    task = _task(db_session)
    conflict = dict(RESULT_DATA, record_status="amount_mismatch")

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=conflict,
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "RECORD_NOT_RECONCILED"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_exception_requires_issue_type(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_exception",
        data={"supplier_id": "SUP-001", "order_id": "ORD-1001"},
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_DATA"


def test_amount_mismatch_exception_requires_both_sides(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_exception",
        data={
            "supplier_id": "SUP-001",
            "order_id": "ORD-1001",
            "issue_type": "amount_mismatch",
            "excel_amount": 5200.00,
        },
        db=db_session,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_DATA"


def test_submission_writes_task_log(db_session):
    task = _task(db_session)

    response = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-log",
        db=db_session,
    )

    assert response["status"] == "success"
    logs = (
        db_session.query(TaskLog)
        .filter(TaskLog.task_id == task.id)
        .all()
    )
    assert len(logs) == 1
    assert "op-log" in logs[0].message
    assert logs[0].status == "submitted"


def test_read_unknown_record_is_error(db_session):
    response = read_oa_record(record_id="OA-19700101-0001", db=db_session)

    assert response["status"] == "error"
    assert response["error_code"] == "OA_RECORD_NOT_FOUND"


def test_list_records_by_task(db_session):
    task = _task(db_session)
    submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-list-1",
        db=db_session,
    )
    submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_exception",
        data=EXCEPTION_DATA,
        operation_id="op-list-2",
        db=db_session,
    )

    response = list_oa_records(task_id=task.id, db=db_session)

    assert response["status"] == "success"
    records = response["result"]["records"]
    assert len(records) == 2
    assert {record["record_type"] for record in records} == {
        "reconciliation_result",
        "reconciliation_exception",
    }


def test_commit_failure_returns_error_and_no_record_then_retry_works(
    db_session,
):
    task = _task(db_session)
    original_commit = db_session.commit

    def broken_commit():
        raise OperationalError(
            "COMMIT", {}, Exception("simulated OA outage")
        )

    db_session.commit = broken_commit
    try:
        response = submit_to_oa(
            task_id=task.id,
            record_type="reconciliation_result",
            data=RESULT_DATA,
            operation_id="op-retry",
            db=db_session,
        )
    finally:
        db_session.commit = original_commit

    assert response["status"] == "error"
    assert response["error_code"] == "OA_SUBMISSION_FAILED"
    assert db_session.query(OaReconciliationRecord).count() == 0

    retry = submit_to_oa(
        task_id=task.id,
        record_type="reconciliation_result",
        data=RESULT_DATA,
        operation_id="op-retry",
        db=db_session,
    )
    assert retry["status"] == "success"
    assert retry["result"]["idempotent_replay"] is False
    assert db_session.query(OaReconciliationRecord).count() == 1
