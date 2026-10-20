"""Runtime acceptance tests: real dispatcher/SQLite plus explicit fault injection.

The shared conftest supplies isolated databases and file roots. No existing
project data, source fixture or test is changed by this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.models import FinancialRecord, OaReconciliationRecord, Task
from backend.app.services import agent_runtime
from backend.app.services.agent_runtime import AgentRuntime, VerifiedConfirmationContext
from backend.app.services.agent_runtime_contracts import (
    ContractViolation,
    TaskStatus,
    ToolName,
    validate_tool_call,
)


CORE_FIELDS = [
    "supplier_id", "supplier_name", "order_id", "amount", "date",
    "payment_status", "record_status",
]
NORMAL_ROW = [
    "SUP-001", "ABC Ltd", "ORD-1001", "5000.00", "2026-09-18",
    "pending", "active",
]
FOUR_TOOLS = {"read_data_file", "validate_data", "query_bi", "submit_to_oa"}


@pytest.fixture
def runtime_case(db_session, temp_settings, make_csv):
    task = Task(description="Runtime skeleton isolated test", status="running")
    db_session.add(task)
    db_session.add(
        FinancialRecord(
            supplier_id="SUP-001", supplier_name="ABC Ltd", order_id="ORD-1001",
            amount="5000.00", date="2026-09-18", payment_status="pending",
            record_status="active", source="runtime-test",
        )
    )
    db_session.commit()
    db_session.refresh(task)
    path = make_csv([CORE_FIELDS, NORMAL_ROW], name="runtime.csv")
    return {
        "task_id": task.id,
        "file_path": str(path),
        "operation_id": "runtime-acceptance",
    }


def _runtime(db, settings, confirmation_provider=None):
    return AgentRuntime(db=db, settings=settings, confirmation_provider=confirmation_provider)


def _oa_rows(db):
    return db.query(OaReconciliationRecord).order_by(OaReconciliationRecord.id).all()


def _write_case(context, make_csv, row):
    make_csv([CORE_FIELDS, row], name=Path(context["file_path"]).name)


def _verified(request):
    return VerifiedConfirmationContext(
        task_id=request.task_id,
        operation_id=request.operation_id,
        evidence_digest=request.evidence_digest,
        confirmation_id="backend-confirmation-test-1",
        purpose="archive_exceptions",
    )


def test_runtime_whitelist_is_exactly_the_existing_four_tools():
    assert {item.value for item in ToolName} == FOUR_TOOLS
    assert set(agent_runtime.dispatcher.TOOL_SPECS) == FOUR_TOOLS


@pytest.mark.parametrize("tool", ["read_oa_record", "run_python", "query_sql", "", None, 12])
def test_runtime_contract_rejects_non_whitelisted_tools(tool):
    with pytest.raises(ContractViolation):
        validate_tool_call(tool, {})


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("read_data_file", {}),
        ("read_data_file", {"file_path": ""}),
        ("read_data_file", {"file_path": "data.csv", "approved": True}),
        ("validate_data", {}),
        ("query_bi", {}),
        ("query_bi", {"supplier_id": True}),
        ("query_bi", {"supplier_id": "SUP-001", "sql": "SELECT 1"}),
        ("submit_to_oa", {"task_id": 1}),
        ("submit_to_oa", {"task_id": True, "record_type": "reconciliation_result", "data": {}, "operation_id": "op"}),
        ("read_data_file", ["data.csv"]),
    ],
)
def test_runtime_tool_arguments_reject_missing_wrong_or_unexpected_fields(tool, arguments):
    with pytest.raises(ContractViolation):
        validate_tool_call(tool, arguments)


def test_deterministic_happy_path_uses_real_four_tools_and_preserves_source(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool
    calls = []

    def recording_execute(tool, arguments, **kwargs):
        calls.append((tool, copy.deepcopy(arguments)))
        return real_execute(tool, arguments, **kwargs)

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", recording_execute)
    source = Path(runtime_case["file_path"])
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = _runtime(db_session, temp_settings).run(runtime_case)

    assert result.task_status is TaskStatus.COMPLETED
    assert result.error_code is None
    expected_order = ["read_data_file", "validate_data", "query_bi", "validate_data", "submit_to_oa"]
    assert [name for name, _ in calls] == expected_order
    assert [item.tool for item in result.trace] == expected_order
    assert {name for name, _ in calls} == FOUR_TOOLS
    assert all(item.envelope["status"] == "success" for item in result.trace)
    assert all(item.attempt == 0 and not item.retry_allowed for item in result.trace)
    assert calls[2][1] == {"supplier_id": "SUP-001", "order_id": "ORD-1001"}
    assert calls[3][1]["reference_records"][0]["order_id"] == "ORD-1001"
    assert calls[-1][1]["data"]["record_status"] == "matched"
    assert calls[-1][1]["operation_id"] == "runtime-acceptance:result:2"
    records = _oa_rows(db_session)
    assert len(records) == 1
    assert records[0].record_type == "reconciliation_result"
    assert records[0].review_status == "archived"
    assert json.loads(records[0].payload)["amount"] == "5000.00"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("problem", ["invalid_amount", "missing_value", "duplicate_business_key"])
def test_real_validation_issues_wait_without_any_oa_write(
    problem, runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    if problem == "invalid_amount":
        row[3] = "not-money"
    elif problem == "missing_value":
        row[1] = ""
    rows = [CORE_FIELDS, row]
    if problem == "duplicate_business_key":
        rows.append(list(row))
    make_csv(rows, name="runtime.csv")

    result = _runtime(db_session, temp_settings).run(runtime_case)

    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert result.classification == "business_issue"
    assert result.error_code is None
    assert [item.tool for item in result.trace] == ["read_data_file", "validate_data"]
    validation = result.trace[-1].envelope
    assert validation["status"] == "success"
    assert problem in {issue["type"] for issue in validation["result"]["issues"]}
    assert result.confirmation_request is not None
    assert _oa_rows(db_session) == []


def test_real_amount_conflict_waits_after_reference_validation(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    result = _runtime(db_session, temp_settings).run(runtime_case)

    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert result.classification == "business_issue"
    assert [item.tool for item in result.trace] == ["read_data_file", "validate_data", "query_bi", "validate_data"]
    issues = result.trace[-1].envelope["result"]["issues"]
    assert [issue["type"] for issue in issues] == ["amount_mismatch"]
    assert issues[0]["excel_amount"] == 5200
    assert issues[0]["bi_amount"] == 5000
    assert _oa_rows(db_session) == []


def test_real_bi_no_match_is_business_wait_not_technical_failure(
    runtime_case, db_session, temp_settings,
):
    db_session.query(FinancialRecord).delete()
    db_session.commit()
    result = _runtime(db_session, temp_settings).run(runtime_case)

    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert result.classification == "business_no_match"
    assert result.error_code is None
    queries = [item for item in result.trace if item.tool == "query_bi"]
    assert len(queries) == 1
    assert queries[0].envelope["status"] == "success"
    assert queries[0].envelope["result"]["records"] == []
    assert queries[0].envelope["result"]["count"] == 0
    assert queries[0].classification == "business_no_match"
    assert queries[0].retry_allowed is False
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize("field", ["confirmed", "approved", "approved_by", "human_confirmed", "authorized_by", "confirmation_provider", "verified_confirmation", "review_status"])
@pytest.mark.parametrize("nested", [False, True])
def test_caller_authority_fields_never_reach_dispatcher(
    field, nested, runtime_case, db_session, temp_settings, monkeypatch,
):
    context = copy.deepcopy(runtime_case)
    if nested:
        context["file_path"] = {"path": runtime_case["file_path"], "metadata": [{field: True}]}
    else:
        context[field] = True
    calls = []

    def unexpected_tool(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Caller authority must fail before any tool executes")

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", unexpected_tool)
    result = _runtime(db_session, temp_settings).run(context)

    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INVALID_CONTRACT"
    assert result.trace == ()
    assert calls == []
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize("missing", ["task_id", "file_path", "operation_id"])
def test_missing_task_context_field_fails_before_tools(
    missing, runtime_case, db_session, temp_settings, monkeypatch,
):
    context = dict(runtime_case)
    del context[missing]
    calls = []
    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", lambda *args, **kwargs: calls.append(args))
    result = _runtime(db_session, temp_settings).run(context)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INVALID_CONTRACT"
    assert calls == []


@pytest.mark.parametrize(
    ("tool_name", "error_code"),
    [("query_bi", "BI_QUERY_FAILED"), ("submit_to_oa", "OA_SUBMISSION_FAILED"), ("read_data_file", "INTERNAL_ERROR")],
)
def test_retryable_failures_attempt_exactly_twice_and_preserve_error(
    tool_name, error_code, runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool
    attempts = []

    def broken_tool(tool, arguments, **kwargs):
        if tool == tool_name:
            attempts.append(copy.deepcopy(arguments))
            return {"status": "error", "error_code": error_code, "message": "injected outage"}
        return real_execute(tool, arguments, **kwargs)

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", broken_tool)
    result = _runtime(db_session, temp_settings).run(runtime_case)

    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == error_code
    assert len(attempts) == 2
    assert attempts[0] == attempts[1]
    failed_calls = [item for item in result.trace if item.tool == tool_name]
    assert [item.attempt for item in failed_calls] == [0, 1]
    assert [item.retry_allowed for item in failed_calls] == [True, False]
    assert all(item.envelope["error_code"] == error_code for item in failed_calls)
    assert _oa_rows(db_session) == []


def test_transient_bi_outage_recovers_on_single_retry(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool
    query_calls = []

    def once_broken(tool, arguments, **kwargs):
        if tool == "query_bi":
            query_calls.append(copy.deepcopy(arguments))
            if len(query_calls) == 1:
                return {"status": "error", "error_code": "BI_QUERY_FAILED", "message": "transient BI outage"}
        return real_execute(tool, arguments, **kwargs)

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", once_broken)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.COMPLETED
    assert query_calls == [{"supplier_id": "SUP-001", "order_id": "ORD-1001"}] * 2
    assert len(_oa_rows(db_session)) == 1
    assert [item.attempt for item in result.trace if item.tool == "query_bi"] == [0, 1]


def test_non_retryable_error_is_not_retried_or_hidden(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    calls = []

    def unreadable(tool, arguments, **kwargs):
        calls.append(tool)
        return {"status": "error", "error_code": "FILE_NOT_FOUND", "message": "missing source"}

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", unreadable)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "FILE_NOT_FOUND"
    assert calls == ["read_data_file"]
    assert result.trace[0].retry_allowed is False
    assert result.trace[0].envelope["message"] == "missing source"


def test_unexpected_dispatcher_exception_is_explicit_and_bounded(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    calls = []

    def raises(tool, arguments, **kwargs):
        calls.append(tool)
        raise RuntimeError("injected unexpected dispatcher exception")

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", raises)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert calls == ["read_data_file", "read_data_file"]
    assert len(result.trace) == 2
    assert all(item.envelope["status"] == "error" for item in result.trace)
    assert all("injected unexpected" in item.envelope["message"] for item in result.trace)


def test_oa_retry_after_real_commit_preserves_operation_and_deduplicates(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool
    oa_arguments = []

    def response_lost_after_commit(tool, arguments, **kwargs):
        response = real_execute(tool, arguments, **kwargs)
        if tool == "submit_to_oa":
            oa_arguments.append(copy.deepcopy(arguments))
            if len(oa_arguments) == 1:
                assert response["status"] == "success"
                assert len(_oa_rows(db_session)) == 1
                return {"status": "error", "error_code": "OA_SUBMISSION_FAILED", "message": "response lost after commit"}
        return response

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", response_lost_after_commit)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.COMPLETED
    assert len(oa_arguments) == 2
    assert oa_arguments[0] == oa_arguments[1]
    assert oa_arguments[0]["operation_id"] == "runtime-acceptance:result:2"
    assert len(_oa_rows(db_session)) == 1
    attempts = [item for item in result.trace if item.tool == "submit_to_oa"]
    assert [item.attempt for item in attempts] == [0, 1]
    assert attempts[0].envelope["status"] == "error"
    assert attempts[1].envelope["result"]["idempotent_replay"] is True


@pytest.mark.parametrize(
    "envelope",
    [None, [], "success", {}, {"status": "ok"}, {"status": "success"},
     {"status": "success", "result": []}, {"status": "success", "result": {}},
     {"status": "error", "message": "missing error code"},
     {"status": "error", "error_code": "INTERNAL_ERROR"},
     {"status": "error", "error_code": "", "message": "bad code"}],
)
def test_illegal_tool_envelope_fails_without_retry_or_oa(
    envelope, runtime_case, db_session, temp_settings, monkeypatch,
):
    calls = []

    def malformed(tool, arguments, **kwargs):
        calls.append(tool)
        return copy.deepcopy(envelope)

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", malformed)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code
    assert calls == ["read_data_file"]
    assert len(result.trace) == 1
    assert result.trace[0].retry_allowed is False
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize(
    ("target_tool", "missing_field"),
    [("read_data_file", "records"), ("validate_data", "issues"),
     ("query_bi", "records"), ("submit_to_oa", "record_id"),
     ("submit_to_oa", "operation_id"), ("submit_to_oa", "submitted")],
)
def test_missing_required_tool_result_fields_are_not_fabricated(
    target_tool, missing_field, runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool

    def incomplete(tool, arguments, **kwargs):
        response = real_execute(tool, arguments, **kwargs)
        if tool == target_tool:
            del response["result"][missing_field]
        return response

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", incomplete)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code
    assert result.trace[-1].tool == target_tool
    assert result.trace[-1].retry_allowed is False
    assert missing_field not in result.trace[-1].envelope["result"]


def test_oa_success_for_different_operation_is_rejected(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool

    def mismatched_result(tool, arguments, **kwargs):
        response = real_execute(tool, arguments, **kwargs)
        if tool == "submit_to_oa":
            response["result"]["operation_id"] = "another-operation"
        return response

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", mismatched_result)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code
    assert len([item for item in result.trace if item.tool == "submit_to_oa"]) == 1
    # A returned invalid receipt cannot undo a real tool commit or imply success.
    assert len(_oa_rows(db_session)) == 1
    assert _oa_rows(db_session)[0].operation_id == "runtime-acceptance:result:2"


def test_backend_verified_confirmation_archives_exception_only_for_review(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    requests = []

    def verified_provider(request):
        requests.append(request)
        return _verified(request)

    result = _runtime(db_session, temp_settings, verified_provider).run(runtime_case)
    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert len(requests) == 1
    assert requests[0].task_id == runtime_case["task_id"]
    assert requests[0].operation_id == runtime_case["operation_id"]
    assert requests[0].purpose == "archive_exceptions"
    assert len(requests[0].evidence_digest) == 64
    records = _oa_rows(db_session)
    assert len(records) == 1
    assert records[0].record_type == "reconciliation_exception"
    assert records[0].review_status == "pending_review"
    data = json.loads(records[0].payload)
    assert data["issue_type"] == "amount_mismatch"
    assert data["excel_amount"] == 5200
    assert data["bi_amount"] == 5000
    assert data["review_status"] == "pending_review"
    assert result.trace[-1].classification == "oa_exception_pending_review"


@pytest.mark.parametrize("bad_confirmation", [True, {"approved": True}, {"confirmed": True}])
def test_backend_provider_must_return_verified_type_not_authority_payload(
    bad_confirmation, runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    result = _runtime(db_session, temp_settings, lambda request: bad_confirmation).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INVALID_CONFIRMATION"
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize("mismatch", ["task_id", "operation_id", "evidence_digest", "purpose", "confirmation_id"])
def test_verified_confirmation_must_match_current_task_operation_evidence_and_purpose(
    mismatch, runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)

    def wrong_context(request):
        changes = {
            "task_id": request.task_id + 1,
            "operation_id": "another-operation",
            "evidence_digest": "0" * 64,
            "purpose": "final_approval",
            "confirmation_id": "",
        }
        return replace(_verified(request), **{mismatch: changes[mismatch]})

    result = _runtime(db_session, temp_settings, wrong_context).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INVALID_CONFIRMATION"
    assert _oa_rows(db_session) == []


def test_changed_source_is_revalidated_and_stale_confirmation_cannot_authorize_write(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    first = _runtime(db_session, temp_settings).run(runtime_case)
    assert first.task_status is TaskStatus.WAITING_CONFIRMATION
    old_confirmation = _verified(first.confirmation_request)

    row[3] = "5300.00"
    _write_case(runtime_case, make_csv, row)
    second = _runtime(db_session, temp_settings, lambda request: old_confirmation).run(runtime_case)
    assert second.task_status is TaskStatus.FAILED
    assert second.error_code == "INVALID_CONFIRMATION"
    assert second.trace[0].tool == "read_data_file"
    assert second.trace[0].envelope["result"]["records"][0]["data"]["amount"] == "5300.00"
    assert _oa_rows(db_session) == []


def test_backend_declines_confirmation_and_runtime_stays_waiting(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    result = _runtime(db_session, temp_settings, lambda request: None).run(runtime_case)
    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert result.error_code is None
    assert _oa_rows(db_session) == []


def test_runtime_executor_rejects_fifth_tool_before_dispatch(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        agent_runtime.dispatcher, "execute_tool",
        lambda *args, **kwargs: calls.append(args),
    )
    with pytest.raises(ContractViolation):
        _runtime(db_session, temp_settings)._execute("run_python", {}, [])
    assert calls == []
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize("authority", ["Approved", "humanConfirmed", "verified_confirmation_context"])
def test_nested_oa_authority_claims_are_rejected(authority):
    with pytest.raises(ContractViolation):
        validate_tool_call("submit_to_oa", {
            "task_id": 1, "record_type": "reconciliation_exception",
            "operation_id": "bound-operation",
            "data": {"metadata": [{"details": {authority: True}}]},
        })


def test_confirmation_provider_failure_is_explicit_without_any_write(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)

    def unavailable(request):
        raise RuntimeError("confirmation store unavailable")

    result = _runtime(db_session, temp_settings, unavailable).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "CONFIRMATION_PROVIDER_FAILED"
    assert "confirmation store unavailable" in result.reason
    assert _oa_rows(db_session) == []


def test_corrected_file_is_revalidated_before_normal_archive(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[3] = "5200.00"
    _write_case(runtime_case, make_csv, row)
    first = _runtime(db_session, temp_settings).run(runtime_case)
    assert first.task_status is TaskStatus.WAITING_CONFIRMATION
    assert _oa_rows(db_session) == []

    _write_case(runtime_case, make_csv, NORMAL_ROW)
    corrected = dict(runtime_case, operation_id="corrected-revision")
    second = _runtime(db_session, temp_settings).run(corrected)
    assert second.task_status is TaskStatus.COMPLETED
    validations = [item for item in second.trace if item.tool == "validate_data"]
    assert len(validations) == 2
    assert all(item.envelope["result"]["issues"] == [] for item in validations)
    assert validations[-1].envelope["result"]["reference_compared"] is True
    assert len(_oa_rows(db_session)) == 1


def test_same_task_revision_replay_does_not_duplicate_oa_records(
    runtime_case, db_session, temp_settings,
):
    runtime = _runtime(db_session, temp_settings)
    first = runtime.run(runtime_case)
    second = runtime.run(runtime_case)
    assert first.task_status is second.task_status is TaskStatus.COMPLETED
    assert len(_oa_rows(db_session)) == 1
    assert second.trace[-1].envelope["result"]["idempotent_replay"] is True


def test_real_empty_dataset_waits_instead_of_fake_completion(
    runtime_case, db_session, temp_settings, make_csv,
):
    make_csv([CORE_FIELDS], name="runtime.csv")
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert result.classification == "business_issue"
    assert result.trace[-1].envelope["result"]["issues"][0]["type"] == "empty_dataset"
    assert _oa_rows(db_session) == []


def test_missing_issue_type_is_explicit_contract_failure(
    runtime_case, db_session, temp_settings, monkeypatch,
):
    real_execute = agent_runtime.dispatcher.execute_tool

    def incomplete(tool, arguments, **kwargs):
        if tool == "validate_data":
            return {"status": "success", "result": {"issues": [
                {"row": 2, "field": "amount", "message": "missing issue type"},
            ]}}
        return real_execute(tool, arguments, **kwargs)

    monkeypatch.setattr(agent_runtime.dispatcher, "execute_tool", incomplete)
    result = _runtime(db_session, temp_settings).run(runtime_case)
    assert result.task_status is TaskStatus.FAILED
    assert result.error_code == "INVALID_CONTRACT"
    assert _oa_rows(db_session) == []


def test_missing_business_keys_cannot_be_confirmed_into_an_oa_write(
    runtime_case, db_session, temp_settings, make_csv,
):
    row = list(NORMAL_ROW)
    row[0] = ""
    _write_case(runtime_case, make_csv, row)
    result = _runtime(db_session, temp_settings, _verified).run(runtime_case)
    assert result.task_status is TaskStatus.WAITING_CONFIRMATION
    assert "missing business keys" in result.reason
    assert _oa_rows(db_session) == []


@pytest.mark.parametrize(
    ("supplier_cell", "order_cell", "supplier_key", "order_key"),
    [(123, 456, "123", "456"), ("00123", "00456", "00123", "00456")],
)
def test_real_xlsx_identifiers_use_existing_rules_and_preserve_leading_zero(
    supplier_cell, order_cell, supplier_key, order_key,
    runtime_case, db_session, temp_settings, make_xlsx,
):
    record = db_session.query(FinancialRecord).one()
    record.supplier_id = supplier_key
    record.order_id = order_key
    db_session.commit()
    row = list(NORMAL_ROW)
    row[0], row[2] = supplier_cell, order_cell
    path = make_xlsx([CORE_FIELDS, row], name="runtime-identifiers.xlsx")
    context = dict(runtime_case, file_path=str(path))
    result = _runtime(db_session, temp_settings).run(context)
    assert result.task_status is TaskStatus.COMPLETED
    query = next(item for item in result.trace if item.tool == "query_bi")
    assert query.arguments == {"supplier_id": supplier_key, "order_id": order_key}
    assert len(_oa_rows(db_session)) == 1
