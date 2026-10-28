"""Provider-neutral, advice-only model seam. No dispatcher or provider SDK.

The caller supplies a trusted deterministic boundary separately from the
redacted model context. A validated proposal is still not permission to run it.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import json
from typing import Protocol

from backend.app.services.agent_runtime import ConfirmationRequest, VerifiedConfirmationContext
from backend.app.services.agent_runtime_contracts import (
    ContractViolation, TaskStatus, ToolName, parse_tool_name,
    reject_untrusted_authority_claims, validate_tool_call,
)


class ModelAction(str, Enum):
    CALL_TOOL = "call_tool"
    REQUEST_CONFIRMATION = "request_confirmation"
    COMPLETE = "complete"
    FAIL_SAFE = "fail_safe"


class ConfirmationState(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    VERIFIED = "verified"  # Informational only; never an authorization grant.


@dataclass(frozen=True)
class ToolResultSummary:
    """Redacted result metadata, never a raw envelope or database object."""
    tool: ToolName
    classification: str
    error_code: str | None = None

    def __post_init__(self):
        parse_tool_name(self.tool)
        if type(self.classification) is not str or self.classification not in {
            "clean_success", "business_issue", "business_no_match", "technical_error",
            "oa_result_archived", "oa_exception_pending_review", "invalid_contract",
        }:
            raise ContractViolation("Unknown tool summary classification.")
        if self.error_code is not None and type(self.error_code) is not str:
            raise ContractViolation("Summary error_code must be text or null.")


@dataclass(frozen=True)
class AgentModelContext:
    """Backend-built, redacted context. Never deserialize caller authority here.

    Task/summary text must be scrubbed by the trusted caller before a future
    external provider sees it. This class does not claim automatic redaction.
    """
    task_description: str
    current_status: TaskStatus
    allowed_tools: tuple[ToolName, ...] = tuple(ToolName)
    previous_tool_results: tuple[ToolResultSummary, ...] = ()
    business_context_summary: str = ""
    confirmation_state: ConfirmationState = ConfirmationState.NOT_REQUESTED

    def __post_init__(self):
        if type(self.task_description) is not str or not self.task_description.strip():
            raise ContractViolation("Task description must be nonempty text.")
        if type(self.business_context_summary) is not str:
            raise ContractViolation("Business summary must be text.")
        if type(self.current_status) is not TaskStatus:
            raise ContractViolation("Use a typed Runtime task status.")
        if type(self.confirmation_state) is not ConfirmationState:
            raise ContractViolation("Use a typed informational confirmation state.")
        if type(self.allowed_tools) is not tuple:
            raise ContractViolation("allowed_tools must be a tuple.")
        names = tuple(parse_tool_name(tool) for tool in self.allowed_tools)
        if len(set(names)) != len(names):
            raise ContractViolation("Duplicate allowed tools.")
        object.__setattr__(self, "allowed_tools", names)
        if type(self.previous_tool_results) is not tuple or any(
            type(item) is not ToolResultSummary for item in self.previous_tool_results
        ):
            raise ContractViolation("Use redacted, typed tool summaries only.")


@dataclass(frozen=True)
class AgentModelProposal:
    action: ModelAction
    tool: str | None
    arguments: dict
    reason: str


@dataclass(frozen=True)
class RuntimeProposalBoundary:
    """Trusted in-process policy output, NEVER taken from model/user JSON.

    Exact next tool/arguments prevent skipped stages or changed file/task/operation
    IDs. This seam does not calculate a second workflow or execute this candidate.
    Confirmation objects stay here and are never passed to the model provider.
    """
    expected_action: ModelAction = ModelAction.FAIL_SAFE
    expected_tool: str | None = None
    expected_arguments: dict = field(default_factory=dict)
    unresolved_business_issue: bool = False
    confirmation_request: ConfirmationRequest | None = None
    verified_confirmation: VerifiedConfirmationContext | None = None


class LLMAdapter(Protocol):
    def propose_next_action(self, context: AgentModelContext) -> AgentModelProposal:
        """Return structured advice; provider code must not execute tools."""
        ...


def _safe_proposal(reason: str) -> AgentModelProposal:
    return AgentModelProposal(ModelAction.FAIL_SAFE, None, {}, reason)


class DeterministicStubAdapter:
    """Repeat a configured local proposal, or abstain. No network or execution."""
    def __init__(self, proposal: AgentModelProposal | None = None):
        self._proposal = deepcopy(proposal) if proposal is not None else _safe_proposal(
            "No external model configured; retain deterministic Runtime control."
        )

    def propose_next_action(self, context: AgentModelContext) -> AgentModelProposal:
        return deepcopy(self._proposal)


def _json_copy(value):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContractViolation("Proposal must contain finite JSON data only.") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractViolation("Duplicate JSON keys are ambiguous.")
        result[key] = value
    return result


def _reject_execution_fields(arguments):
    pending = [arguments]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                canonical = "".join(char for char in key.casefold() if char.isalnum())
                if canonical in {"shell", "command", "code", "script", "python", "exec", "eval", "urlfetch"}:
                    raise ContractViolation("Executable instructions are not model tool arguments.")
                pending.append(child)
        elif isinstance(value, list):
            pending.extend(value)


def _parse_proposal(payload) -> AgentModelProposal:
    if type(payload) is AgentModelProposal:
        payload = {key: getattr(payload, key) for key in ("action", "tool", "arguments", "reason")}
    elif type(payload) is str:
        try:
            payload = json.loads(payload, object_pairs_hook=_unique_object)
        except (ValueError, RecursionError) as exc:
            raise ContractViolation("Model output must be structured JSON.") from exc
    if type(payload) is not dict or set(payload) != {"action", "tool", "arguments", "reason"}:
        raise ContractViolation("Proposal requires exactly action, tool, arguments and reason.")
    reject_untrusted_authority_claims(payload)
    payload = _json_copy(payload)
    try:
        action = ModelAction(payload["action"])
    except (TypeError, ValueError) as exc:
        raise ContractViolation("Invalid proposal action.") from exc
    if type(payload["arguments"]) is not dict:
        raise ContractViolation("Proposal arguments must be an object.")
    _reject_execution_fields(payload["arguments"])
    if type(payload["reason"]) is not str or not payload["reason"].strip():
        raise ContractViolation("Proposal reason must be nonempty text.")
    if action is ModelAction.CALL_TOOL:
        tool, arguments = validate_tool_call(payload["tool"], payload["arguments"])
        return AgentModelProposal(action, tool.value, arguments, payload["reason"])
    if payload["tool"] is not None or payload["arguments"]:
        raise ContractViolation("Non-tool actions require tool=null and arguments={ }.")
    return AgentModelProposal(action, None, {}, payload["reason"])


def _bound_confirmation(boundary: RuntimeProposalBoundary, arguments: dict) -> bool:
    request, verified = boundary.confirmation_request, boundary.verified_confirmation
    return (
        type(request) is ConfirmationRequest
        and type(verified) is VerifiedConfirmationContext
        and type(request.task_id) is int and request.task_id > 0
        and type(verified.task_id) is int and verified.task_id == request.task_id
        and type(request.operation_id) is str and bool(request.operation_id.strip())
        and verified.operation_id == request.operation_id
        and type(request.evidence_digest) is str and len(request.evidence_digest) == 64
        and verified.evidence_digest == request.evidence_digest
        and request.purpose == verified.purpose == "archive_exceptions"
        and type(verified.confirmation_id) is str and bool(verified.confirmation_id.strip())
        and arguments["task_id"] == request.task_id
        and arguments["operation_id"].startswith(request.operation_id + ":exception:")
    )


def validate_model_proposal(
    payload, context: AgentModelContext, boundary: RuntimeProposalBoundary,
) -> AgentModelProposal:
    """Second validation against trusted state/candidate, with zero execution.

    Context and boundary must come from Runtime/Backend code, not model text.
    Runtime must still recheck policy and its own confirmation provider at use.
    """
    if type(context) is not AgentModelContext or type(boundary) is not RuntimeProposalBoundary:
        raise ContractViolation("Trusted typed context and boundary are required.")
    if type(boundary.expected_action) is not ModelAction or type(boundary.unresolved_business_issue) is not bool:
        raise ContractViolation("Invalid trusted boundary.")
    proposal = _parse_proposal(payload)
    if proposal.action is ModelAction.FAIL_SAFE:
        return proposal
    unresolved = boundary.unresolved_business_issue or any(
        item.classification in {"business_issue", "business_no_match", "oa_exception_pending_review"}
        for item in context.previous_tool_results
    )
    if context.current_status in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
        raise ContractViolation("Terminal failed/cancelled tasks only permit fail_safe advice.")
    if proposal.action is ModelAction.COMPLETE:
        if unresolved or context.current_status is not TaskStatus.COMPLETED or boundary.expected_action is not ModelAction.COMPLETE:
            raise ContractViolation("Model cannot skip steps, resolve business issues or mark a task complete.")
        return proposal  # Acknowledge an already completed Runtime; no state change.
    if proposal.action is ModelAction.REQUEST_CONFIRMATION:
        if context.current_status is TaskStatus.COMPLETED:
            raise ContractViolation("Completed tasks do not request new confirmation.")
        return proposal  # A request does not mint/store a verified context.
    if context.current_status is TaskStatus.COMPLETED:
        raise ContractViolation("Completed tasks cannot propose more tool calls.")
    if boundary.expected_action is not ModelAction.CALL_TOOL:
        raise ContractViolation("Runtime has not selected a next tool.")
    expected_tool, expected_args = validate_tool_call(boundary.expected_tool, boundary.expected_arguments)
    if parse_tool_name(proposal.tool) not in context.allowed_tools:
        raise ContractViolation("Tool is outside this task's allowlist.")
    if proposal.tool != expected_tool.value or json.dumps(proposal.arguments, sort_keys=True) != json.dumps(expected_args, sort_keys=True):
        raise ContractViolation("Proposal changes or skips the Runtime-selected next call.")
    is_exception = proposal.tool == "submit_to_oa" and proposal.arguments["record_type"] == "reconciliation_exception"
    if unresolved and not is_exception:
        raise ContractViolation("Unresolved business findings require confirmation, not normal execution.")
    if is_exception:
        if not unresolved or context.confirmation_state is not ConfirmationState.VERIFIED or not _bound_confirmation(boundary, proposal.arguments):
            raise ContractViolation("Exception write needs task/operation/evidence/purpose-bound Backend confirmation.")
    elif context.current_status is TaskStatus.WAITING_CONFIRMATION:
        raise ContractViolation("Waiting tasks cannot bypass confirmation with a normal call.")
    return proposal


@dataclass(frozen=True)
class ModelAdvice:
    proposal: AgentModelProposal
    classification: str
    error_code: str | None = None


def get_model_advice(
    context: AgentModelContext, boundary: RuntimeProposalBoundary,
    adapter: LLMAdapter | None = None,
) -> ModelAdvice:
    """Optional orchestration seam; failure leaves deterministic Runtime intact.

    No tool dispatch, task mutation, provider retry, confirmation minting or raw
    exception logging. A Python provider implementation is trusted code, not a
    sandbox; only its returned model data is treated as untrusted here.
    """
    if type(context) is not AgentModelContext or type(boundary) is not RuntimeProposalBoundary:
        raise ContractViolation("Trusted typed context and boundary are required.")
    saved_context, saved_boundary = deepcopy(context), deepcopy(boundary)
    try:
        payload = (adapter if adapter is not None else DeterministicStubAdapter()).propose_next_action(
            deepcopy(saved_context)
        )
    except Exception:
        return ModelAdvice(_safe_proposal("Model provider failed; retain deterministic control."),
                           "provider_error", "MODEL_PROVIDER_FAILED")
    try:
        proposal = validate_model_proposal(payload, saved_context, saved_boundary)
    except (ContractViolation, TypeError, ValueError, RecursionError):
        return ModelAdvice(_safe_proposal("Model proposal rejected; retain deterministic control."),
                           "model_output_invalid", "MODEL_OUTPUT_INVALID")
    return ModelAdvice(proposal, "model_proposal_valid")
