"""Runtime contracts for the existing four RPA tools.

These checks validate protocol structure and untrusted input. File access,
reconciliation rules and OA business validation remain owned by the tools.
The Week 2 contract semantics live here without a production prototype import.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ContractViolation(ValueError):
    """A caller payload or tool response violates the runtime contract."""


class ToolName(str, Enum):
    READ_DATA_FILE = "read_data_file"
    VALIDATE_DATA = "validate_data"
    QUERY_BI = "query_bi"
    SUBMIT_TO_OA = "submit_to_oa"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OaRecordType(str, Enum):
    RECONCILIATION_RESULT = "reconciliation_result"
    RECONCILIATION_EXCEPTION = "reconciliation_exception"


FORBIDDEN_AUTHORITY_FIELDS = frozenset(
    {
        "confirmed", "approved", "approved_by", "human_confirmed",
        "authorized_by", "authorised_by", "authorized", "authorised",
        "is_confirmed", "is_approved", "is_verified", "verified", "verified_by",
        "approval", "approval_id", "approval_status", "approval_context",
        "approval_token", "human_approval", "confirmation", "confirmation_id",
        "confirmation_status", "confirmation_context", "confirmation_token",
        "confirmation_verified", "human_confirmation", "verified_confirmation",
        "verified_confirmation_context", "backend_verified_confirmation",
        "backend_verified", "backend_verified_context", "verified_context",
        "verification", "verification_status", "verification_context",
        "verification_token", "authorization", "authorization_context",
        "authority", "authority_context", "review_status",
    }
)


def _authority_key(key: str) -> str:
    # Treat casing, snake_case, camelCase and separators consistently.
    return "".join(character for character in key.casefold() if character.isalnum())


_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    _authority_key(field) for field in FORBIDDEN_AUTHORITY_FIELDS
)

_TOOL_PARAMETERS = {
    ToolName.READ_DATA_FILE: frozenset({"file_path", "sheet_name"}),
    ToolName.VALIDATE_DATA: frozenset(
        {"file_path", "reference_records", "sheet_name"}
    ),
    ToolName.QUERY_BI: frozenset({"supplier_id", "order_id"}),
    ToolName.SUBMIT_TO_OA: frozenset(
        {"task_id", "record_type", "data", "operation_id"}
    ),
}


@dataclass(frozen=True)
class ToolEnvelope:
    status: str
    result: dict[str, Any] | None = None
    error_code: str | None = None
    message: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_error(self) -> bool:
        return self.status == "error"


def parse_tool_name(value: ToolName | str) -> ToolName:
    """Accept exactly the four implemented RPA tool names."""
    try:
        return value if isinstance(value, ToolName) else ToolName(value)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"Tool is not on the runtime whitelist: {value!r}") from exc


def _nonempty_string(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{field} must be a non-empty string.")


def _positive_integer(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractViolation(f"{field} must be a positive integer.")


def _object_list(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ContractViolation(f"{field} must be a list of objects.")
    return value


def parse_tool_envelope(payload: Mapping[str, Any]) -> ToolEnvelope:
    """Parse mutually exclusive success/error envelopes without defaults."""
    if not isinstance(payload, Mapping):
        raise ContractViolation("Tool response must be an object.")

    status = payload.get("status")
    if status == "success":
        if "error_code" in payload or "message" in payload:
            raise ContractViolation("A success envelope cannot contain error fields.")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise ContractViolation("A success envelope must contain an object result.")
        return ToolEnvelope(status="success", result=deepcopy(dict(result)))

    if status == "error":
        if "result" in payload:
            raise ContractViolation("An error envelope cannot contain a success result.")
        error_code = payload.get("error_code")
        message = payload.get("message")
        _nonempty_string(error_code, "error_code")
        _nonempty_string(message, "message")
        return ToolEnvelope(
            status="error", error_code=error_code.strip(), message=message.strip()
        )

    raise ContractViolation("Tool response status must be 'success' or 'error'.")


def reject_untrusted_authority_claims(data: Mapping[str, Any]) -> None:
    """Reject caller authority claims, including inside nested objects/lists.

    This function never grants permission. A serialized verification claim is
    still untrusted input; Backend confirmation verification is a separate job.
    Tool responses are not caller arguments and must not be passed here.
    """
    if not isinstance(data, Mapping):
        raise ContractViolation("Authority input must be an object.")

    pending: list[Any] = [data]
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (Mapping, list, tuple)):
            continue
        if id(value) in visited:
            continue
        visited.add(id(value))
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ContractViolation("Caller object keys must be strings.")
                if _authority_key(key) in _FORBIDDEN_AUTHORITY_KEYS:
                    raise ContractViolation(
                        "Caller-supplied authority fields are not valid Agent "
                        f"permission: {key}"
                    )
                pending.append(child)
        else:
            pending.extend(value)


def validate_tool_call(
    tool: ToolName | str, arguments: Mapping[str, Any]
) -> tuple[ToolName, dict[str, Any]]:
    """Validate a call's name/argument structure before dispatcher execution."""
    tool_name = parse_tool_name(tool)
    if not isinstance(arguments, dict):
        raise ContractViolation("Tool arguments must be an object.")
    reject_untrusted_authority_claims(arguments)
    unknown = set(arguments) - _TOOL_PARAMETERS[tool_name]
    if unknown:
        raise ContractViolation(
            f"Unexpected argument(s) for {tool_name.value}: {', '.join(sorted(unknown))}."
        )

    if tool_name in {ToolName.READ_DATA_FILE, ToolName.VALIDATE_DATA}:
        _nonempty_string(arguments.get("file_path"), "file_path")
        sheet_name = arguments.get("sheet_name")
        if sheet_name is not None:
            # The current file tool accepts worksheet names, not numeric indices.
            _nonempty_string(sheet_name, "sheet_name")
        references = arguments.get("reference_records")
        if tool_name is ToolName.VALIDATE_DATA and references is not None:
            _object_list(references, "reference_records")

    elif tool_name is ToolName.QUERY_BI:
        for field in ("supplier_id", "order_id"):
            value = arguments.get(field)
            if value is not None and not isinstance(value, str):
                raise ContractViolation(f"{field} must be a string when provided.")
        if not any(
            isinstance(arguments.get(field), str) and arguments[field].strip()
            for field in ("supplier_id", "order_id")
        ):
            raise ContractViolation("At least one non-empty BI identifier is required.")

    elif tool_name is ToolName.SUBMIT_TO_OA:
        _positive_integer(arguments.get("task_id"), "task_id")
        try:
            OaRecordType(arguments.get("record_type"))
        except (TypeError, ValueError) as exc:
            raise ContractViolation("Requested OA record_type is invalid.") from exc
        if not isinstance(arguments.get("data"), dict):
            raise ContractViolation("OA data must be an object.")
        _nonempty_string(arguments.get("operation_id"), "operation_id")

    return tool_name, deepcopy(dict(arguments))


def validate_tool_result(tool: ToolName | str, result: Mapping[str, Any]) -> None:
    """Validate fields consumed by runtime decisions, using real tool schemas."""
    tool_name = parse_tool_name(tool)
    if not isinstance(result, Mapping):
        raise ContractViolation("Tool result must be an object.")
    if tool_name is ToolName.READ_DATA_FILE:
        records = _object_list(result.get("records"), "read_data_file.records")
        for record in records:
            _positive_integer(record.get("row"), "read_data_file.records[].row")
            if not isinstance(record.get("data"), dict):
                raise ContractViolation("read_data_file.records[].data must be an object.")
    elif tool_name is ToolName.VALIDATE_DATA:
        issues = _object_list(result.get("issues"), "validate_data.issues")
        for issue in issues:
            required = {"type", "row", "field", "message"}
            if not required.issubset(issue):
                raise ContractViolation(
                    "validate_data.issues[] requires type, row, field and message."
                )
            _nonempty_string(issue["type"], "validate_data.issues[].type")
            _nonempty_string(issue["message"], "validate_data.issues[].message")
            if issue["row"] is not None:
                _positive_integer(issue["row"], "validate_data.issues[].row")
            if issue["field"] is not None and not isinstance(issue["field"], str):
                raise ContractViolation("validate_data.issues[].field must be text or null.")
    elif tool_name is ToolName.QUERY_BI:
        _object_list(result.get("records"), "query_bi.records")
    else:
        _nonempty_string(result.get("record_id"), "submit_to_oa.record_id")
        _nonempty_string(result.get("operation_id"), "submit_to_oa.operation_id")
        try:
            OaRecordType(result.get("record_type"))
        except (TypeError, ValueError) as exc:
            raise ContractViolation("submit_to_oa returned an unknown record_type.") from exc
        if result.get("submitted") is not True:
            raise ContractViolation("submit_to_oa success must report submitted=true.")
        _nonempty_string(result.get("review_status"), "submit_to_oa.review_status")
        if not isinstance(result.get("idempotent_replay"), bool):
            raise ContractViolation("submit_to_oa.idempotent_replay must be a boolean.")
        ignored_fields = result.get("ignored_fields")
        if not isinstance(ignored_fields, list) or any(
            not isinstance(field, str) for field in ignored_fields
        ):
            raise ContractViolation("submit_to_oa.ignored_fields must be a list of strings.")
