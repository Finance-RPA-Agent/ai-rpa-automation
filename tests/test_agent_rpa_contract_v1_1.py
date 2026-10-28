"""Agent V1.1 prototype integration checks against the real four RPA tools.

All database writes use the existing ``db_session`` temporary SQLite fixture.
The seven repository demo files are read-only inputs and are hash-checked.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.models import OaReconciliationRecord, Task
from backend.app.services.finance_seed import seed_financial_records
from backend.app.tools.dispatcher import execute_tool
from prototypes.week2_agent_v1_1.contracts import (
    ContractViolation,
    TaskStatus,
    ToolName,
    parse_tool_envelope,
    parse_tool_name,
    reject_untrusted_authority_claims,
)
from prototypes.week2_agent_v1_1.decision_policy import (
    DecisionClass,
    classify_tool_response,
    finalize_task,
    may_retry,
    require_stable_operation_id,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_DATA = REPO_ROOT / "demo_data"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def demo_settings(temp_settings) -> Settings:
    return Settings(
        base_dir=REPO_ROOT,
        upload_dir=temp_settings.upload_dir,
        demo_data_dir=DEMO_DATA,
        output_dir=temp_settings.output_dir,
    )


@pytest.fixture
def seeded_db(db_session):
    seed_financial_records(db_session)
    return db_session


def _new_task(db, description: str) -> Task:
    task = Task(description=description, status=TaskStatus.RUNNING.value)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _call(db, settings, tool: str, arguments: dict) -> dict:
    return execute_tool(tool, arguments, db=db, settings=settings)


def _read_and_validate(filename: str, db, settings):
    path = DEMO_DATA / filename
    before = _sha256(path)

    read = _call(
        db,
        settings,
        "read_data_file",
        {"file_path": str(path)},
    )
    read_decision = classify_tool_response(ToolName.READ_DATA_FILE, read)

    validation = _call(
        db,
        settings,
        "validate_data",
        {"file_path": str(path)},
    )
    validation_decision = classify_tool_response(ToolName.VALIDATE_DATA, validation)
    return path, before, read, read_decision, validation, validation_decision


def _query_unique_records(read: dict, db, settings):
    references = []
    envelopes = []
    decisions = []
    seen = set()

    for item in read["result"]["records"]:
        data = item["data"]
        key = (data.get("supplier_id"), data.get("order_id"))
        if key in seen or not all(key):
            continue
        seen.add(key)
        envelope = _call(
            db,
            settings,
            "query_bi",
            {"supplier_id": key[0], "order_id": key[1]},
        )
        envelopes.append(envelope)
        decisions.append(classify_tool_response(ToolName.QUERY_BI, envelope))
        if envelope["status"] == "success":
            references.extend(envelope["result"]["records"])

    return references, envelopes, decisions


def test_contract_enums_and_envelope_parser_are_strict():
    assert {item.value for item in ToolName} == {
        "read_data_file",
        "validate_data",
        "query_bi",
        "submit_to_oa",
    }
    assert {item.value for item in TaskStatus} == {
        "pending",
        "running",
        "waiting_confirmation",
        "completed",
        "failed",
        "cancelled",
    }
    assert parse_tool_envelope(
        {"status": "success", "result": {"records": []}}
    ).is_success

    with pytest.raises(ContractViolation):
        parse_tool_name("run_shell")
    with pytest.raises(ContractViolation):
        parse_tool_envelope({"status": "success"})
    with pytest.raises(ContractViolation):
        parse_tool_envelope({"status": "error", "message": "missing code"})


@pytest.mark.parametrize(
    "error_code",
    ["BI_QUERY_FAILED", "OA_SUBMISSION_FAILED", "INTERNAL_ERROR"],
)
def test_retry_policy_allows_exactly_one_retry(error_code):
    assert may_retry(error_code, 0) is True
    assert may_retry(error_code, 1) is False
    assert may_retry(error_code, 2) is False
    first = classify_tool_response(
        ToolName.QUERY_BI,
        {"status": "error", "error_code": error_code, "message": "injected"},
        retries_already_attempted=0,
    )
    exhausted = classify_tool_response(
        ToolName.QUERY_BI,
        {"status": "error", "error_code": error_code, "message": "injected"},
        retries_already_attempted=1,
    )
    assert first.retry_allowed is True
    assert first.task_status is TaskStatus.RUNNING
    assert exhausted.retry_allowed is False
    assert exhausted.task_status is TaskStatus.FAILED


def test_operation_id_and_untrusted_authority_guards():
    operation_id = "task12:SUP-001:ORD-1001:result"
    require_stable_operation_id(operation_id, operation_id)
    with pytest.raises(ContractViolation):
        require_stable_operation_id(operation_id, operation_id + ":retry")
    with pytest.raises(ContractViolation):
        reject_untrusted_authority_claims({"confirmed": True})
    with pytest.raises(ContractViolation):
        reject_untrusted_authority_claims({"approved": True})


def test_normal_orders_reaches_completed_with_real_four_tools(
    seeded_db, demo_settings
):
    path, before, read, read_decision, first_validation, first_decision = (
        _read_and_validate("normal_orders.xlsx", seeded_db, demo_settings)
    )
    assert read_decision.classification is DecisionClass.CLEAN_SUCCESS
    assert first_decision.classification is DecisionClass.CLEAN_SUCCESS

    references, query_envelopes, query_decisions = _query_unique_records(
        read, seeded_db, demo_settings
    )
    assert len(query_envelopes) == 3
    assert all(item["status"] == "success" for item in query_envelopes)
    assert all(item["result"]["records"] for item in query_envelopes)

    final_validation = _call(
        seeded_db,
        demo_settings,
        "validate_data",
        {"file_path": str(path), "reference_records": references},
    )
    final_decision = classify_tool_response(
        ToolName.VALIDATE_DATA, final_validation
    )
    assert final_validation["result"]["issues"] == []

    task = _new_task(seeded_db, "Agent V1.1 normal validation")
    oa_decisions = []
    for item in read["result"]["records"]:
        data = dict(item["data"])
        data["record_status"] = "matched"
        operation_id = (
            f"agent-v1.1:{task.id}:{data['supplier_id']}:{data['order_id']}:result"
        )
        response = _call(
            seeded_db,
            demo_settings,
            "submit_to_oa",
            {
                "task_id": task.id,
                "record_type": "reconciliation_result",
                "data": data,
                "operation_id": operation_id,
            },
        )
        oa_decisions.append(
            classify_tool_response(
                ToolName.SUBMIT_TO_OA,
                response,
                requested_record_type="reconciliation_result",
            )
        )

    decisions = [
        read_decision,
        first_decision,
        *query_decisions,
        final_decision,
        *oa_decisions,
    ]
    assert finalize_task(decisions, expected_normal_submissions=3) is TaskStatus.COMPLETED
    assert all(
        item.classification is DecisionClass.OA_RESULT_ARCHIVED
        for item in oa_decisions
    )
    assert _sha256(path) == before


def test_amount_conflict_waits_and_archives_only_exceptions(
    seeded_db, demo_settings
):
    path, before, read, read_decision, _, first_decision = _read_and_validate(
        "amount_conflict.csv", seeded_db, demo_settings
    )
    references, _, query_decisions = _query_unique_records(
        read, seeded_db, demo_settings
    )
    final_validation = _call(
        seeded_db,
        demo_settings,
        "validate_data",
        {"file_path": str(path), "reference_records": references},
    )
    final_decision = classify_tool_response(
        ToolName.VALIDATE_DATA, final_validation
    )
    assert final_decision.classification is DecisionClass.BUSINESS_ISSUE
    assert {item["type"] for item in final_validation["result"]["issues"]} == {
        "amount_mismatch",
        "payment_status_mismatch",
    }

    rows = {
        item["row"]: item["data"] for item in read["result"]["records"]
    }
    task = _new_task(seeded_db, "Agent V1.1 conflict validation")
    oa_decisions = []
    for issue in final_validation["result"]["issues"]:
        source = rows[issue["row"]]
        data = {
            "supplier_id": source["supplier_id"],
            "order_id": source["order_id"],
            "issue_type": issue["type"],
        }
        for field in (
            "excel_amount",
            "bi_amount",
            "difference",
            "excel_value",
            "bi_value",
        ):
            if field in issue:
                data[field] = issue[field]
        operation_id = (
            f"agent-v1.1:{task.id}:{data['supplier_id']}:{data['order_id']}:"
            f"{issue['type']}"
        )
        response = _call(
            seeded_db,
            demo_settings,
            "submit_to_oa",
            {
                "task_id": task.id,
                "record_type": "reconciliation_exception",
                "data": data,
                "operation_id": operation_id,
            },
        )
        decision = classify_tool_response(
            ToolName.SUBMIT_TO_OA,
            response,
            requested_record_type="reconciliation_exception",
        )
        assert decision.classification is DecisionClass.OA_EXCEPTION_PENDING_REVIEW
        oa_decisions.append(decision)

    decisions = [
        read_decision,
        first_decision,
        *query_decisions,
        final_decision,
        *oa_decisions,
    ]
    assert (
        finalize_task(decisions, expected_normal_submissions=0)
        is TaskStatus.WAITING_CONFIRMATION
    )
    assert (
        seeded_db.query(OaReconciliationRecord)
        .filter(OaReconciliationRecord.task_id == task.id)
        .filter(OaReconciliationRecord.record_type == "reconciliation_result")
        .count()
        == 0
    )
    assert _sha256(path) == before


@pytest.mark.parametrize(
    ("filename", "expected_types"),
    [
        ("missing_values.csv", {"missing_value"}),
        ("invalid_formats.xlsx", {"invalid_amount", "invalid_date"}),
        ("duplicate_keys.xlsx", {"duplicate_business_key"}),
    ],
)
def test_file_quality_cases_wait_for_confirmation_without_guessing(
    filename, expected_types, seeded_db, demo_settings
):
    path, before, _, read_decision, validation, validation_decision = (
        _read_and_validate(filename, seeded_db, demo_settings)
    )
    issue_types = {item["type"] for item in validation["result"]["issues"]}
    assert expected_types.issubset(issue_types)
    assert validation["status"] == "success"
    assert validation_decision.classification is DecisionClass.BUSINESS_ISSUE
    assert validation_decision.task_status is TaskStatus.WAITING_CONFIRMATION
    assert (
        finalize_task(
            [read_decision, validation_decision],
            expected_normal_submissions=0,
        )
        is TaskStatus.WAITING_CONFIRMATION
    )
    assert _sha256(path) == before


def test_no_match_is_business_result_not_bi_query_failed(seeded_db, demo_settings):
    path, before, read, read_decision, _, first_decision = _read_and_validate(
        "no_match.csv", seeded_db, demo_settings
    )
    references, query_envelopes, query_decisions = _query_unique_records(
        read, seeded_db, demo_settings
    )
    empty = [item for item in query_envelopes if item["result"]["records"] == []]
    assert len(empty) == 1
    no_match_decision = next(
        item
        for item in query_decisions
        if item.classification is DecisionClass.BUSINESS_NO_MATCH
    )
    assert no_match_decision.task_status is TaskStatus.WAITING_CONFIRMATION
    assert no_match_decision.classification is not DecisionClass.TECHNICAL_ERROR

    final_validation = _call(
        seeded_db,
        demo_settings,
        "validate_data",
        {"file_path": str(path), "reference_records": references},
    )
    final_decision = classify_tool_response(
        ToolName.VALIDATE_DATA, final_validation
    )
    assert "record_not_found" in {
        item["type"] for item in final_validation["result"]["issues"]
    }
    assert (
        finalize_task(
            [read_decision, first_decision, *query_decisions, final_decision],
            expected_normal_submissions=0,
        )
        is TaskStatus.WAITING_CONFIRMATION
    )
    assert _sha256(path) == before


def test_leading_zero_identifiers_are_preserved_in_real_query(
    seeded_db, demo_settings
):
    path, before, read, read_decision, _, first_decision = _read_and_validate(
        "leading_zero.csv", seeded_db, demo_settings
    )
    data = read["result"]["records"][0]["data"]
    assert data["supplier_id"] == "00123"
    assert data["order_id"] == "ORD-0007"

    response = _call(
        seeded_db,
        demo_settings,
        "query_bi",
        {"supplier_id": data["supplier_id"], "order_id": data["order_id"]},
    )
    decision = classify_tool_response(ToolName.QUERY_BI, response)
    assert response["result"]["query"] == {
        "supplier_id": "00123",
        "order_id": "ORD-0007",
    }
    assert decision.classification is DecisionClass.BUSINESS_NO_MATCH
    assert (
        finalize_task(
            [read_decision, first_decision, decision],
            expected_normal_submissions=0,
        )
        is TaskStatus.WAITING_CONFIRMATION
    )
    assert _sha256(path) == before
