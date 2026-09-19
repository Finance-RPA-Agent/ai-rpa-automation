"""PROTOTYPE / NOT PRODUCTION: deterministic V1.1 decision policy.

The policy consumes real tool envelopes. It does not call a model, run a
script, mutate files, or persist workflow state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from .contracts import (
    ContractViolation,
    OaRecordType,
    TaskStatus,
    ToolName,
    parse_tool_envelope,
    parse_tool_name,
)


MAX_AUTOMATIC_RETRIES = 1
RETRYABLE_ERROR_CODES = frozenset(
    {"BI_QUERY_FAILED", "OA_SUBMISSION_FAILED", "INTERNAL_ERROR"}
)


class DecisionClass(str, Enum):
    CLEAN_SUCCESS = "clean_success"
    BUSINESS_ISSUE = "business_issue"
    BUSINESS_NO_MATCH = "business_no_match"
    TECHNICAL_ERROR = "technical_error"
    OA_RESULT_ARCHIVED = "oa_result_archived"
    OA_EXCEPTION_PENDING_REVIEW = "oa_exception_pending_review"


@dataclass(frozen=True)
class AgentDecision:
    task_status: TaskStatus
    classification: DecisionClass
    reason: str
    retry_allowed: bool = False


def may_retry(error_code: str, retries_already_attempted: int) -> bool:
    if not isinstance(retries_already_attempted, int) or isinstance(
        retries_already_attempted, bool
    ):
        raise ContractViolation("retries_already_attempted must be an integer.")
    if retries_already_attempted < 0:
        raise ContractViolation("retries_already_attempted cannot be negative.")
    return (
        error_code in RETRYABLE_ERROR_CODES
        and retries_already_attempted < MAX_AUTOMATIC_RETRIES
    )


def require_stable_operation_id(original: str, retry: str) -> None:
    """Reject an OA retry that changes its idempotency key."""

    if not isinstance(original, str) or not original.strip():
        raise ContractViolation("The original operation_id must be non-empty.")
    if not isinstance(retry, str) or not retry.strip():
        raise ContractViolation("The retry operation_id must be non-empty.")
    if original != retry:
        raise ContractViolation("OA retry must keep the original operation_id.")


def _require_list(result: Mapping[str, Any], field: str) -> list[Any]:
    value = result.get(field)
    if not isinstance(value, list):
        raise ContractViolation(f"Tool result field {field!r} must be a list.")
    return value


def classify_tool_response(
    tool: ToolName | str,
    payload: Mapping[str, Any],
    *,
    requested_record_type: OaRecordType | str | None = None,
    retries_already_attempted: int = 0,
) -> AgentDecision:
    """Classify a real RPA envelope into an Agent-side decision."""

    tool_name = parse_tool_name(tool)
    envelope = parse_tool_envelope(payload)

    if envelope.is_error:
        assert envelope.error_code is not None
        retry_allowed = may_retry(envelope.error_code, retries_already_attempted)
        return AgentDecision(
            task_status=(TaskStatus.RUNNING if retry_allowed else TaskStatus.FAILED),
            classification=DecisionClass.TECHNICAL_ERROR,
            reason=(
                f"{tool_name.value} returned technical error "
                f"{envelope.error_code}."
            ),
            retry_allowed=retry_allowed,
        )

    assert envelope.result is not None
    result = envelope.result

    if tool_name is ToolName.VALIDATE_DATA:
        issues = _require_list(result, "issues")
        if issues:
            return AgentDecision(
                task_status=TaskStatus.WAITING_CONFIRMATION,
                classification=DecisionClass.BUSINESS_ISSUE,
                reason=f"validate_data returned {len(issues)} business/data issue(s).",
            )

    if tool_name is ToolName.QUERY_BI:
        records = _require_list(result, "records")
        if not records:
            return AgentDecision(
                task_status=TaskStatus.WAITING_CONFIRMATION,
                classification=DecisionClass.BUSINESS_NO_MATCH,
                reason="query_bi succeeded but returned no business match.",
            )

    if tool_name is ToolName.SUBMIT_TO_OA:
        raw_record_type = result.get("record_type")
        try:
            returned_type = OaRecordType(raw_record_type)
        except (TypeError, ValueError) as exc:
            raise ContractViolation("submit_to_oa returned an unknown record_type.") from exc

        if requested_record_type is not None:
            try:
                expected_type = (
                    requested_record_type
                    if isinstance(requested_record_type, OaRecordType)
                    else OaRecordType(requested_record_type)
                )
            except (TypeError, ValueError) as exc:
                raise ContractViolation("Requested OA record_type is invalid.") from exc
            if returned_type is not expected_type:
                raise ContractViolation(
                    "submit_to_oa returned a different record_type than requested."
                )

        if result.get("submitted") is not True:
            raise ContractViolation("submit_to_oa success must report submitted=true.")

        review_status = result.get("review_status")
        if returned_type is OaRecordType.RECONCILIATION_RESULT:
            if review_status != "archived":
                raise ContractViolation(
                    "reconciliation_result must return review_status='archived'."
                )
            return AgentDecision(
                task_status=TaskStatus.RUNNING,
                classification=DecisionClass.OA_RESULT_ARCHIVED,
                reason="Normal reconciliation result was archived.",
            )

        if review_status != "pending_review":
            raise ContractViolation(
                "reconciliation_exception must return review_status='pending_review'."
            )
        return AgentDecision(
            task_status=TaskStatus.WAITING_CONFIRMATION,
            classification=DecisionClass.OA_EXCEPTION_PENDING_REVIEW,
            reason="Reconciliation exception was archived for review.",
        )

    return AgentDecision(
        task_status=TaskStatus.RUNNING,
        classification=DecisionClass.CLEAN_SUCCESS,
        reason=f"{tool_name.value} returned a clean success result.",
    )


def finalize_task(
    decisions: Iterable[AgentDecision],
    *,
    expected_normal_submissions: int,
) -> TaskStatus:
    """Derive a terminal validation status from completed tool decisions."""

    if expected_normal_submissions < 0:
        raise ContractViolation("expected_normal_submissions cannot be negative.")

    observed = list(decisions)
    if any(item.task_status is TaskStatus.FAILED for item in observed):
        return TaskStatus.FAILED

    waiting_classes = {
        DecisionClass.BUSINESS_ISSUE,
        DecisionClass.BUSINESS_NO_MATCH,
        DecisionClass.OA_EXCEPTION_PENDING_REVIEW,
    }
    if any(item.classification in waiting_classes for item in observed):
        return TaskStatus.WAITING_CONFIRMATION

    archived = sum(
        item.classification is DecisionClass.OA_RESULT_ARCHIVED for item in observed
    )
    if archived != expected_normal_submissions:
        raise ContractViolation(
            "Cannot complete: archived normal-result count does not match expectation."
        )
    return TaskStatus.COMPLETED
