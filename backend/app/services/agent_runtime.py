"""Deterministic Agent orchestration over the existing four-tool dispatcher.

This service has no HTTP/authentication/persistence layer. Backend supplies an
authorized task/file context and, optionally, a trusted confirmation provider.
Caller JSON cannot supply that provider or mint a verified confirmation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Callable, Mapping

from backend.app.tools import dispatcher
from backend.app.tools.rules import normalise_identifier
from backend.app.services.agent_runtime_contracts import (
    ContractViolation, TaskStatus, ToolName, parse_tool_envelope,
    reject_untrusted_authority_claims, validate_tool_call,
)
from backend.app.services.agent_runtime_policy import (
    AgentDecision, classify_tool_response, require_stable_operation_id,
)


@dataclass(frozen=True)
class ConfirmationRequest:
    task_id: int
    operation_id: str
    evidence_digest: str
    purpose: str = "archive_exceptions"


@dataclass(frozen=True)
class VerifiedConfirmationContext:
    """Backend-only verification output; never deserialize this from a request.

    The injected provider must authenticate the reviewer, check permissions and
    stored evidence, and return this object only for a matching saved decision.
    Runtime checks binding/scope, not the reviewer's identity or persistence.
    """
    task_id: int
    operation_id: str
    evidence_digest: str
    confirmation_id: str
    purpose: str = "archive_exceptions"


@dataclass(frozen=True)
class ToolAttempt:
    tool: str
    arguments: dict
    envelope: object
    attempt: int
    classification: str
    retry_allowed: bool


@dataclass(frozen=True)
class RuntimeResult:
    task_status: TaskStatus
    classification: str
    reason: str
    trace: tuple[ToolAttempt, ...]
    error_code: str | None = None
    confirmation_request: ConfirmationRequest | None = None


class _Stopped(Exception):
    def __init__(self, classification: str, reason: str, error_code: str):
        self.classification = classification
        self.reason = reason
        self.error_code = error_code
        super().__init__(reason)


class AgentRuntime:
    """One deterministic run, with at most one retry per logical tool call.

    db and settings must be supplied by Backend; no implicit default database.
    The same operation_id denotes the same immutable task revision. Re-running
    always re-reads and re-validates; it never resumes from caller-supplied state.
    """

    def __init__(
        self, *, db, settings,
        confirmation_provider: Callable[
            [ConfirmationRequest], VerifiedConfirmationContext | None
        ] | None = None,
    ):
        if db is None or settings is None:
            raise ValueError("Backend must supply an explicit db and settings.")
        if confirmation_provider is not None and not callable(confirmation_provider):
            raise ValueError("confirmation_provider must be a trusted Backend callable.")
        self.db = db
        self.settings = settings
        self._confirmation_provider = confirmation_provider

    @staticmethod
    def _context(context: Mapping) -> dict:
        if not isinstance(context, Mapping):
            raise ContractViolation("Task context must be an object.")
        reject_untrusted_authority_claims(context)
        required = {"task_id", "file_path", "operation_id"}
        allowed = required | {"sheet_name"}
        if set(context) - allowed or required - set(context):
            raise ContractViolation("Task context has unknown or missing fields.")
        result = deepcopy(dict(context))
        if type(result["task_id"]) is not int or result["task_id"] <= 0:
            raise ContractViolation("task_id must be a positive integer.")
        for field in ("file_path", "operation_id"):
            if not isinstance(result[field], str) or not result[field].strip():
                raise ContractViolation(f"{field} must be a non-empty string.")
        if result["operation_id"] != result["operation_id"].strip():
            raise ContractViolation("operation_id cannot have surrounding whitespace.")
        validate_tool_call("read_data_file", {
            key: result[key] for key in ("file_path", "sheet_name") if key in result
        })
        return result

    def _execute(self, tool, arguments, trace: list[ToolAttempt]) -> tuple[dict, AgentDecision]:
        name, args = validate_tool_call(tool, arguments)
        # Each attempt receives a fresh copy of the SAME logical arguments.
        original = deepcopy(args)
        for attempt in range(2):
            current = deepcopy(original)
            if name is ToolName.SUBMIT_TO_OA:
                require_stable_operation_id(original["operation_id"], current["operation_id"])
            try:
                response = dispatcher.execute_tool(
                    name.value, current, db=self.db, settings=self.settings,
                )
            except Exception as exc:
                # Normally the dispatcher converts handler exceptions itself.
                # A broken integration must still surface an explicit failure.
                response = {
                    "status": "error", "error_code": "INTERNAL_ERROR",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            try:
                envelope = parse_tool_envelope(response)
                decision = classify_tool_response(
                    name, response,
                    requested_record_type=original.get("record_type"),
                    retries_already_attempted=attempt,
                )
                if name is ToolName.SUBMIT_TO_OA and envelope.is_success:
                    require_stable_operation_id(
                        original["operation_id"], envelope.result["operation_id"],
                    )
            except ContractViolation:
                trace.append(ToolAttempt(
                    name.value, deepcopy(original), deepcopy(response), attempt,
                    "invalid_contract", False,
                ))
                raise
            trace.append(ToolAttempt(
                name.value, deepcopy(original), deepcopy(response), attempt,
                decision.classification.value, decision.retry_allowed,
            ))
            if envelope.is_error:
                if decision.retry_allowed:
                    continue
                raise _Stopped(
                    "technical_error", envelope.message, envelope.error_code,
                )
            return envelope.result, decision
        raise AssertionError("Retry bound must terminate with a result or explicit failure.")

    def run(self, context: Mapping) -> RuntimeResult:
        trace: list[ToolAttempt] = []
        try:
            task = self._context(context)
            return self._run(task, trace)
        except ContractViolation as exc:
            return RuntimeResult(
                TaskStatus.FAILED, "invalid_contract", str(exc), tuple(trace),
                error_code="INVALID_CONTRACT",
            )
        except _Stopped as exc:
            return RuntimeResult(
                TaskStatus.FAILED, exc.classification, exc.reason, tuple(trace),
                error_code=exc.error_code,
            )

    def _run(self, task: dict, trace: list[ToolAttempt]) -> RuntimeResult:
        file_args = {
            key: task[key] for key in ("file_path", "sheet_name") if key in task
        }
        read, _ = self._execute("read_data_file", file_args, trace)
        records = read["records"]
        validation, decision = self._execute("validate_data", file_args, trace)
        references: list[dict] = []
        if decision.task_status is TaskStatus.WAITING_CONFIRMATION:
            return self._wait(task, read, validation, references, decision, trace)
        if not records:
            raise ContractViolation("A clean validation cannot complete an empty read.")

        no_match = None
        # Validation owns missing/duplicate keys and all financial comparisons.
        for record in records:
            data = record["data"]
            response, query_decision = self._execute("query_bi", {
                "supplier_id": normalise_identifier(data.get("supplier_id")),
                "order_id": normalise_identifier(data.get("order_id")),
            }, trace)
            references.extend(response["records"])
            if query_decision.task_status is TaskStatus.WAITING_CONFIRMATION:
                no_match = query_decision

        validation, decision = self._execute("validate_data", {
            **file_args, "reference_records": references,
        }, trace)
        if no_match is not None or decision.task_status is TaskStatus.WAITING_CONFIRMATION:
            return self._wait(
                task, read, validation, references, no_match or decision, trace,
            )

        for record in records:
            # 'matched' is the archive outcome of the successful comparison,
            # not a mutation of the input file or BI business status.
            data = dict(record["data"])
            data["record_status"] = "matched"
            self._execute("submit_to_oa", {
                "task_id": task["task_id"],
                "record_type": "reconciliation_result",
                "data": data,
                "operation_id": f"{task['operation_id']}:result:{record['row']}",
            }, trace)
        return RuntimeResult(
            TaskStatus.COMPLETED, "oa_result_archived",
            f"Archived {len(records)} reconciled record(s).", tuple(trace),
        )

    def _wait(self, task, read, validation, references, decision, trace):
        evidence = {"read": read, "validation": validation, "references": references}
        try:
            encoded = json.dumps(
                evidence, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"), allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ContractViolation("Tool evidence must be JSON serializable.") from exc
        request = ConfirmationRequest(
            task["task_id"], task["operation_id"], hashlib.sha256(encoded).hexdigest(),
        )

        def waiting(reason):
            return RuntimeResult(
                TaskStatus.WAITING_CONFIRMATION, decision.classification.value,
                reason, tuple(trace), confirmation_request=request,
            )

        if self._confirmation_provider is None:
            return waiting(decision.reason)
        try:
            verified = self._confirmation_provider(request)
        except Exception as exc:
            raise _Stopped(
                "confirmation_error",
                f"Backend confirmation provider failed: {type(exc).__name__}: {exc}",
                "CONFIRMATION_PROVIDER_FAILED",
            ) from exc
        if verified is None:
            return waiting(decision.reason)
        if (
            type(verified) is not VerifiedConfirmationContext
            or type(verified.task_id) is not int
            or verified.task_id != request.task_id
            or verified.operation_id != request.operation_id
            or verified.evidence_digest != request.evidence_digest
            or verified.purpose != request.purpose
            or not isinstance(verified.confirmation_id, str)
            or not verified.confirmation_id.strip()
        ):
            raise _Stopped(
                "confirmation_error", "Backend confirmation is invalid or stale.",
                "INVALID_CONFIRMATION",
            )

        # The grant only permits archiving exceptions for review. It can never
        # convert a business issue/no-match into a reconciled normal result.
        rows = {record["row"]: record["data"] for record in read["records"]}
        submissions = []
        for index, issue in enumerate(validation["issues"]):
            source = rows.get(issue.get("row"), {})
            supplier_id = normalise_identifier(source.get("supplier_id"))
            order_id = normalise_identifier(source.get("order_id"))
            if supplier_id is None or order_id is None:
                return waiting("Correct missing business keys/file-level issues and run again.")
            data = {
                "supplier_id": supplier_id,
                "order_id": order_id,
                "issue_type": issue["type"],
            }
            for field in (
                "excel_amount", "bi_amount", "difference", "excel_value", "bi_value",
            ):
                if field in issue:
                    data[field] = issue[field]
            submissions.append({
                "task_id": task["task_id"],
                "record_type": "reconciliation_exception",
                "data": data,
                "operation_id": f"{task['operation_id']}:exception:{index}",
            })
        if not submissions:
            return waiting(decision.reason)
        for arguments in submissions:
            self._execute("submit_to_oa", arguments, trace)
        return waiting("Verified exceptions archived as pending_review; human review remains required.")
