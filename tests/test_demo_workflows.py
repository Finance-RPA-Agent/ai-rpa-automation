"""End-to-end tests for the deterministic demo workflows."""

from __future__ import annotations

from backend.app.models import OaReconciliationRecord, Task, TaskLog
from backend.app.services.demo_data import (
    AMOUNT_CONFLICT_CASE,
    NORMAL_CASE,
)
from backend.app.services.demo_workflow import (
    DemoFlowError,
    run_conflict_flow,
    run_normal_flow,
)
from backend.app.tools import read_oa_record


def _latest_task(db) -> Task:
    return db.query(Task).order_by(Task.id.desc()).first()


def test_normal_flow_completes_and_reads_back(
    db_session, temp_settings, make_xlsx
):
    path = make_xlsx(
        NORMAL_CASE.rows,
        name=NORMAL_CASE.filename,
        directory=temp_settings.demo_data_dir,
    )
    before = path.read_bytes()

    summary = run_normal_flow(
        db_session, file_path=path, settings=temp_settings
    )

    task = _latest_task(db_session)
    assert task.status == "completed"
    assert summary["valid_rows"] == 3
    assert summary["invalid_rows"] == 0
    assert len(summary["oa_records"]) == 3
    assert summary["source_unchanged"] is True
    assert path.read_bytes() == before

    records = (
        db_session.query(OaReconciliationRecord)
        .filter(OaReconciliationRecord.task_id == task.id)
        .all()
    )
    assert len(records) == 3
    assert all(
        record.record_type == "reconciliation_result"
        for record in records
    )
    assert all(
        record.review_status == "archived" for record in records
    )

    read_back = read_oa_record(
        summary["oa_records"][0], db=db_session
    )
    assert read_back["status"] == "success"
    assert (
        read_back["result"]["record"]["data"]["record_status"]
        == "matched"
    )

    logs = (
        db_session.query(TaskLog)
        .filter(TaskLog.task_id == task.id)
        .all()
    )
    actions = [log.action for log in logs]
    assert "Demo Flow Start" in actions
    assert "Demo Flow Completed" in actions


def test_conflict_flow_waits_for_confirmation(
    db_session, temp_settings, make_csv
):
    path = make_csv(
        AMOUNT_CONFLICT_CASE.rows,
        name=AMOUNT_CONFLICT_CASE.filename,
        directory=temp_settings.demo_data_dir,
    )
    before = path.read_bytes()

    summary = run_conflict_flow(
        db_session, file_path=path, settings=temp_settings
    )

    task = _latest_task(db_session)
    assert task.status == "waiting_confirmation"
    assert summary["source_unchanged"] is True
    assert summary["normal_result_recorded"] is False
    assert path.read_bytes() == before

    conflict_types = {
        conflict["issue_type"] for conflict in summary["conflicts"]
    }
    assert conflict_types == {
        "amount_mismatch",
        "payment_status_mismatch",
    }

    amount_conflict = next(
        conflict
        for conflict in summary["conflicts"]
        if conflict["issue_type"] == "amount_mismatch"
    )
    assert float(amount_conflict["excel_amount"]) == 5200.00
    assert float(amount_conflict["bi_amount"]) == 5000.00
    assert float(amount_conflict["difference"]) == 200.00

    records = (
        db_session.query(OaReconciliationRecord)
        .filter(OaReconciliationRecord.task_id == task.id)
        .all()
    )
    assert len(records) == 2
    assert all(
        record.record_type == "reconciliation_exception"
        for record in records
    )
    assert all(
        record.review_status == "pending_review" for record in records
    )

    normal_results = (
        db_session.query(OaReconciliationRecord)
        .filter(
            OaReconciliationRecord.task_id == task.id,
            OaReconciliationRecord.record_type
            == "reconciliation_result",
        )
        .count()
    )
    assert normal_results == 0


def test_normal_flow_technical_failure_marks_task_failed(
    db_session, temp_settings
):
    missing = temp_settings.demo_data_dir / "not-created.xlsx"

    try:
        run_normal_flow(
            db_session, file_path=missing, settings=temp_settings
        )
    except DemoFlowError:
        pass
    else:  # pragma: no cover - the demo must fail here
        raise AssertionError("run_normal_flow should have raised")

    task = _latest_task(db_session)
    assert task.status == "failed"
    assert (
        db_session.query(Task)
        .filter(Task.status == "running")
        .count()
        == 0
    )


def test_conflict_flow_technical_failure_marks_task_failed(
    db_session, temp_settings
):
    missing = temp_settings.demo_data_dir / "not-created.csv"

    try:
        run_conflict_flow(
            db_session, file_path=missing, settings=temp_settings
        )
    except DemoFlowError:
        pass
    else:  # pragma: no cover
        raise AssertionError("run_conflict_flow should have raised")

    task = _latest_task(db_session)
    assert task.status == "failed"
    assert (
        db_session.query(Task)
        .filter(Task.status == "running")
        .count()
        == 0
    )


def test_conflict_flow_without_conflicts_is_a_demo_failure(
    db_session, temp_settings, make_csv
):
    from backend.app.services.demo_data import HEADERS

    path = make_csv(
        [HEADERS, list(NORMAL_CASE.rows[1])],
        name="clean.csv",
        directory=temp_settings.demo_data_dir,
    )

    try:
        run_conflict_flow(
            db_session, file_path=path, settings=temp_settings
        )
    except DemoFlowError:
        pass
    else:  # pragma: no cover
        raise AssertionError("run_conflict_flow should have raised")

    task = _latest_task(db_session)
    assert task.status == "completed"
    assert (
        db_session.query(Task)
        .filter(Task.status == "running")
        .count()
        == 0
    )
