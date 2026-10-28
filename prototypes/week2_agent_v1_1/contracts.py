"""PROTOTYPE / NOT PRODUCTION: strict Agent-side contract types.

This module has no model/runtime integration and never invokes a tool or an
arbitrary script. It only validates already-returned Python mappings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ContractViolation(ValueError):
    """A tool or caller payload does not satisfy the V1.1 contract."""


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
        "confirmed",
        "approved",
        "approved_by",
        "human_confirmed",
        "authorized_by",
    }
)


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
        raise ContractViolation(f"Tool is not on the V1.1 whitelist: {value!r}") from exc


def parse_tool_envelope(payload: Mapping[str, Any]) -> ToolEnvelope:
    """Parse the RPA success/error envelope without inventing defaults."""

    if not isinstance(payload, Mapping):
        raise ContractViolation("Tool response must be an object.")

    status = payload.get("status")
    if status == "success":
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise ContractViolation("A success envelope must contain an object result.")
        return ToolEnvelope(status="success", result=dict(result))

    if status == "error":
        error_code = payload.get("error_code")
        message = payload.get("message")
        if not isinstance(error_code, str) or not error_code.strip():
            raise ContractViolation("An error envelope needs a non-empty error_code.")
        if not isinstance(message, str) or not message.strip():
            raise ContractViolation("An error envelope needs a non-empty message.")
        return ToolEnvelope(
            status="error",
            error_code=error_code.strip(),
            message=message.strip(),
        )

    raise ContractViolation("Tool response status must be 'success' or 'error'.")


def reject_untrusted_authority_claims(data: Mapping[str, Any]) -> None:
    """Prevent caller-supplied booleans/names from becoming Agent authority.

    A future production integration must consume a backend-verified confirmation
    context. This prototype deliberately has no positive authorization path.
    """

    if not isinstance(data, Mapping):
        raise ContractViolation("Authority input must be an object.")
    present = sorted(FORBIDDEN_AUTHORITY_FIELDS.intersection(data))
    if present:
        raise ContractViolation(
            "Caller-supplied authority fields are not valid Agent permission: "
            + ", ".join(present)
        )
