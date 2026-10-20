"""Deterministic runtime decisions for the existing four RPA tool contracts.

Business findings remain successful tool results that require confirmation.
This module neither executes tools nor grants or persists human authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from backend.app.services.agent_runtime_contracts import (
    ContractViolation,
    OaRecordType,
    TaskStatus,
    ToolName,
    parse_tool_envelope,
    parse_tool_name,
    validate_tool_result,
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
    if not isinstance(error_code, str) or not error_code.strip():
        raise ContractViolation("error_code must be a non-empty string.")
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


def classify_tool_response(
    tool: ToolName | str,
    payload: Mapping[str, Any],
    *,
    requested_record_type: OaRecordType | str | None = None,
    retries_already_attempted: int = 0,
) -> AgentDecision:
    """Validate and classify a real dispatcher response without hiding errors."""
    tool_name = parse_tool_name(tool)
    envelope = parse_tool_envelope(payload)
    if envelope.is_error:
        retry_allowed = may_retry(envelope.error_code, retries_already_attempted)
        return AgentDecision(
            task_status=TaskStatus.RUNNING if retry_allowed else TaskStatus.FAILED,
            classification=DecisionClass.TECHNICAL_ERROR,
            reason=f"{tool_name.value} returned technical error {envelope.error_code}.",
            retry_allowed=retry_allowed,
        )

    result = envelope.result
    validate_tool_result(tool_name, result)
    if tool_name is ToolName.VALIDATE_DATA and result["issues"]:
        return AgentDecision(
            task_status=TaskStatus.WAITING_CONFIRMATION,
            classification=DecisionClass.BUSINESS_ISSUE,
            reason=f"validate_data returned {len(result['issues'])} business/data issue(s).",
        )
    if tool_name is ToolName.QUERY_BI and not result["records"]:
        return AgentDecision(
            task_status=TaskStatus.WAITING_CONFIRMATION,
            classification=DecisionClass.BUSINESS_NO_MATCH,
            reason="query_bi succeeded but returned no business match.",
        )

    if tool_name is ToolName.SUBMIT_TO_OA:
        returned_type = OaRecordType(result["record_type"])
        if requested_record_type is not None:
            try:
                expected_type = OaRecordType(requested_record_type)
            except (TypeError, ValueError) as exc:
                raise ContractViolation("Requested OA record_type is invalid.") from exc
            if returned_type is not expected_type:
                raise ContractViolation(
                    "submit_to_oa returned a different record_type than requested."
                )
        if returned_type is OaRecordType.RECONCILIATION_RESULT:
            if result["review_status"] != "archived":
                raise ContractViolation(
                    "reconciliation_result must return review_status='archived'."
                )
            return AgentDecision(
                task_status=TaskStatus.RUNNING,
                classification=DecisionClass.OA_RESULT_ARCHIVED,
                reason="Normal reconciliation result was archived.",
            )
        if result["review_status"] != "pending_review":
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
