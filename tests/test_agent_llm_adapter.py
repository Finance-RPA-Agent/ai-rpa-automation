"""Model advice cannot execute, skip Runtime policy or manufacture authority."""
from copy import deepcopy
from dataclasses import asdict, replace
import json

import pytest

from backend.app.services.agent_llm_adapter import (
    AgentModelContext, AgentModelProposal, ConfirmationState,
    DeterministicStubAdapter, ModelAction, RuntimeProposalBoundary,
    ToolResultSummary, get_model_advice, validate_model_proposal,
)
from backend.app.services.agent_runtime import ConfirmationRequest, VerifiedConfirmationContext
from backend.app.services.agent_runtime_contracts import ContractViolation, TaskStatus, ToolName
from backend.app.tools import dispatcher
from scripts.run_agent_runtime_demo import run_demo


def context(**updates):
    return replace(AgentModelContext("Synthetic reconciliation", TaskStatus.RUNNING), **updates)


def query():
    return {"action": "call_tool", "tool": "query_bi",
            "arguments": {"supplier_id": "SUP-001", "order_id": "PO-001"},
            "reason": "Need the BI reference before reconciliation."}


def boundary(payload=None, **updates):
    value = payload or query()
    return RuntimeProposalBoundary(ModelAction.CALL_TOOL, value["tool"],
                                   deepcopy(value["arguments"]), **updates)


def simple(action):
    return {"action": action, "tool": None, "arguments": {}, "reason": "Structured advice only."}


@pytest.fixture(autouse=True)
def no_model_dispatch(monkeypatch):
    """Most cases exercise only the seam; any accidental dispatch fails the test."""
    def forbidden(*args, **kwargs):
        raise AssertionError("Adapter must not execute tools")
    monkeypatch.setattr(dispatcher, "execute_tool", forbidden)


@pytest.mark.parametrize("representation", ["dict", "json", "typed"])
def test_valid_query_proposal_is_advice_only_and_copied(representation):
    payload = query()
    if representation == "json":
        payload = json.dumps(payload)
    elif representation == "typed":
        payload = AgentModelProposal(ModelAction.CALL_TOOL, "query_bi", query()["arguments"], "Read BI")
    result = validate_model_proposal(payload, context(), boundary())
    assert result.action is ModelAction.CALL_TOOL
    assert result.tool == "query_bi"
    assert result.arguments == query()["arguments"]
    result.arguments["order_id"] = "CHANGED"
    if representation == "dict":
        assert payload["arguments"]["order_id"] == "PO-001"
    elif representation == "typed":
        assert payload.arguments["order_id"] == "PO-001"


@pytest.mark.parametrize("tool", ["run_python", "shell", "query_sql", "fetch_url", "read_oa_record", "", None, 7])
def test_fifth_tools_and_execution_tools_are_rejected(tool):
    payload = query(); payload["tool"] = tool
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("action", ["execute", "approve", "run_code", "fetch", "", None, True])
def test_invalid_actions_are_rejected(action):
    payload = query(); payload["action"] = action
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("field", ["action", "tool", "arguments", "reason"])
def test_missing_fields_are_rejected(field):
    payload = query(); del payload[field]
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("payload", [None, [], 42, "not JSON", '[]', 'null',
    '{"action":"fail_safe","action":"complete","tool":null,"arguments":{},"reason":"x"}',
    '{"action":"call_tool","tool":"query_bi","arguments":{"supplier_id":"a","supplier_id":"b"},"reason":"x"}'])
def test_nonstructured_or_ambiguous_json_is_rejected(payload):
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("arguments", [None, [], "query_bi", {}, {"supplier_id": True},
                                       {"supplier_id": "SUP-001", "sql": "DELETE FROM tasks"},
                                       {"supplier_id": float("nan")}])
def test_invalid_or_missing_tool_arguments_are_rejected(arguments):
    payload = query(); payload["arguments"] = arguments
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("field", ["approved", "confirmed", "verified", "VerifiedContext", "confirmation_token", "unknown"])
def test_extra_top_level_fields_are_rejected(field):
    payload = query(); payload[field] = True
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


@pytest.mark.parametrize("field", ["approved", "Confirmed", "isVerified", "review_status", "verificationContext"])
def test_nested_authority_is_rejected(field):
    payload = exception_call()
    payload["arguments"]["data"]["nested"] = [{field: True}]
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary(payload))


@pytest.mark.parametrize("field", ["shell", "command", "code", "script", "python", "exec", "eval", "url_fetch"])
def test_nested_executable_payload_is_rejected(field):
    payload = exception_call()
    payload["arguments"]["data"][field] = "untrusted instruction"
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary(payload))


@pytest.mark.parametrize("action", ["request_confirmation", "complete", "fail_safe"])
def test_non_tool_actions_cannot_smuggle_arguments(action):
    payload = query(); payload["action"] = action
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())


def test_request_confirmation_never_becomes_verified_or_mutates_state():
    ctx = context(current_status=TaskStatus.WAITING_CONFIRMATION,
                  confirmation_state=ConfirmationState.REQUESTED)
    limit = RuntimeProposalBoundary(unresolved_business_issue=True)
    result = get_model_advice(ctx, limit, DeterministicStubAdapter(
        AgentModelProposal(ModelAction.REQUEST_CONFIRMATION, None, {}, "Ask reviewer")
    ))
    assert result.classification == "model_proposal_valid"
    assert result.proposal.action is ModelAction.REQUEST_CONFIRMATION
    assert limit.verified_confirmation is None
    assert ctx.confirmation_state is ConfirmationState.REQUESTED
    assert ctx.current_status is TaskStatus.WAITING_CONFIRMATION


@pytest.mark.parametrize("classification", ["business_issue", "business_no_match", "oa_exception_pending_review"])
def test_business_findings_cannot_be_completed_even_with_verified_label(classification):
    ctx = context(current_status=TaskStatus.COMPLETED, confirmation_state=ConfirmationState.VERIFIED,
                  previous_tool_results=(ToolResultSummary(ToolName.QUERY_BI, classification),))
    with pytest.raises(ContractViolation):
        validate_model_proposal(simple("complete"), ctx, RuntimeProposalBoundary(ModelAction.COMPLETE))


@pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING_CONFIRMATION,
                                   TaskStatus.FAILED, TaskStatus.CANCELLED])
def test_model_cannot_mark_an_uncompleted_runtime_complete(status):
    with pytest.raises(ContractViolation):
        validate_model_proposal(simple("complete"), context(current_status=status),
                                RuntimeProposalBoundary(ModelAction.COMPLETE))


def test_complete_only_acknowledges_an_already_completed_runtime():
    result = validate_model_proposal(simple("complete"), context(current_status=TaskStatus.COMPLETED),
                                     RuntimeProposalBoundary(ModelAction.COMPLETE))
    assert result.action is ModelAction.COMPLETE


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.WAITING_CONFIRMATION])
def test_ineligible_task_status_cannot_call_query(status):
    with pytest.raises(ContractViolation):
        validate_model_proposal(query(), context(current_status=status), boundary())


def test_task_allowlist_and_exact_deterministic_next_call_cannot_be_bypassed():
    with pytest.raises(ContractViolation):
        validate_model_proposal(query(), context(allowed_tools=(ToolName.READ_DATA_FILE,)), boundary())
    with pytest.raises(ContractViolation):
        validate_model_proposal(query(), context(), RuntimeProposalBoundary())
    payload = query(); payload["arguments"]["supplier_id"] = "OTHER-TASK"
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary())
    read = {"action": "call_tool", "tool": "read_data_file", "arguments": {"file_path": "allowed.csv"}, "reason": "Read"}
    with pytest.raises(ContractViolation):
        validate_model_proposal(query(), context(), boundary(read))


def exception_call():
    return {"action": "call_tool", "tool": "submit_to_oa", "arguments": {
        "task_id": 1, "record_type": "reconciliation_exception", "operation_id": "revision-1:exception:0",
        "data": {"supplier_id": "SUP-001", "order_id": "PO-001", "issue_type": "record_not_found"},
    }, "reason": "Archive only for pending review"}


def grant():
    return VerifiedConfirmationContext(1, "revision-1", "a" * 64, "backend-review-1")


def exception_boundary(verified=None):
    return boundary(exception_call(), unresolved_business_issue=True,
                    confirmation_request=ConfirmationRequest(1, "revision-1", "a" * 64),
                    verified_confirmation=verified)


@pytest.mark.parametrize("verified", [None, True, {"verified": True}, {"confirmation_id": "forged"}])
def test_high_risk_write_requires_backend_context_not_model_label(verified):
    with pytest.raises(ContractViolation):
        validate_model_proposal(exception_call(), context(current_status=TaskStatus.WAITING_CONFIRMATION,
            confirmation_state=ConfirmationState.VERIFIED), exception_boundary(verified))


@pytest.mark.parametrize("change", [{"task_id": 2}, {"operation_id": "other"}, {"evidence_digest": "b"*64},
                                    {"purpose": "final_approval"}, {"confirmation_id": ""}])
def test_wrong_or_stale_confirmation_binding_is_rejected(change):
    with pytest.raises(ContractViolation):
        validate_model_proposal(exception_call(), context(current_status=TaskStatus.WAITING_CONFIRMATION,
            confirmation_state=ConfirmationState.VERIFIED), exception_boundary(replace(grant(), **change)))


def test_valid_backend_bound_exception_is_still_only_advice():
    result = validate_model_proposal(exception_call(), context(current_status=TaskStatus.WAITING_CONFIRMATION,
        confirmation_state=ConfirmationState.VERIFIED), exception_boundary(grant()))
    assert result.action is ModelAction.CALL_TOOL
    assert result.arguments["record_type"] == "reconciliation_exception"
    assert not hasattr(result, "verified_confirmation")


def test_normal_archive_does_not_resolve_business_issue():
    payload = exception_call(); payload["arguments"]["record_type"] = "reconciliation_result"
    with pytest.raises(ContractViolation):
        validate_model_proposal(payload, context(), boundary(payload, unresolved_business_issue=True))


def test_stub_is_repeatable_and_defensively_copies_proposals():
    proposed = AgentModelProposal(ModelAction.CALL_TOOL, "query_bi", query()["arguments"], "Read BI")
    adapter = DeterministicStubAdapter(proposed)
    proposed.arguments["supplier_id"] = "MUTATED"
    first = adapter.propose_next_action(context()); second = adapter.propose_next_action(context())
    assert first == second
    first.arguments.clear()
    assert adapter.propose_next_action(context()) == second
    assert get_model_advice(context(), boundary()).proposal.action is ModelAction.FAIL_SAFE


def test_provider_exception_is_fail_safe_and_does_not_leak_secrets():
    class Broken:
        def propose_next_action(self, ctx):
            raise RuntimeError("private provider diagnostic must not be logged")
    result = get_model_advice(context(), boundary(), Broken())
    assert result.proposal.action is ModelAction.FAIL_SAFE
    assert result.classification == "provider_error"
    assert result.error_code == "MODEL_PROVIDER_FAILED"
    assert "private provider" not in json.dumps(asdict(result))


def test_invalid_provider_result_is_classified_without_execution():
    class BadOutput:
        def propose_next_action(self, ctx):
            return {**query(), "approved": True}
    result = get_model_advice(context(), boundary(), BadOutput())
    assert result.proposal.action is ModelAction.FAIL_SAFE
    assert result.classification == "model_output_invalid"
    assert result.error_code == "MODEL_OUTPUT_INVALID"


def test_provider_cannot_change_saved_boundary_during_request():
    limit = boundary()
    class Mutating:
        def propose_next_action(self, ctx):
            limit.expected_arguments["supplier_id"] = "OTHER"
            return {**query(), "arguments": deepcopy(limit.expected_arguments)}
    assert get_model_advice(context(), limit, Mutating()).classification == "model_output_invalid"


@pytest.mark.parametrize("bad", [{"allowed_tools": ("run_python",)}, {"allowed_tools": ("query_bi", "query_bi")},
                                {"previous_tool_results": ({"db": object()},)},
                                {"confirmation_state": {"verified": True}}, {"current_status": "running"}])
def test_context_rejects_non_typed_or_overbroad_provider_inputs(bad):
    with pytest.raises(ContractViolation):
        context(**bad)


@pytest.mark.parametrize("scenario", ["clean_success", "validation_issue", "bi_no_match"])
def test_existing_runtime_independent_of_missing_or_broken_adapter(scenario, monkeypatch):
    # Restore the real dispatcher just for this integration check.
    monkeypatch.undo()
    class Broken:
        def propose_next_action(self, ctx):
            raise OSError("test outage")
    assert get_model_advice(context(), boundary(), Broken()).proposal.action is ModelAction.FAIL_SAFE
    report = run_demo(scenario)
    assert report["harness_status"] == "passed"
    assert report["task_status"] == ("completed" if scenario == "clean_success" else "waiting_confirmation")
    if scenario == "clean_success":
        assert len(report["oa_records"]) == 1
    else:
        assert report["oa_records"] == []
