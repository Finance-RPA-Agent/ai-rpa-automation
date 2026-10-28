"""Tool error types and stable error codes.

The task contract keeps HTTP errors and tool envelopes separate: a tool
that cannot fulfil its job returns ``{"status": "error", "error_code": ...}``
rather than raising an HTTP exception.
"""

from __future__ import annotations


class ErrorCode:
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_READ_ERROR = "FILE_READ_ERROR"
    EMPTY_FILE = "EMPTY_FILE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    UNSUPPORTED_ENCODING = "UNSUPPORTED_ENCODING"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_CSV_STRUCTURE = "INVALID_CSV_STRUCTURE"
    CSV_PARSE_ERROR = "CSV_PARSE_ERROR"
    SHEET_NOT_FOUND = "SHEET_NOT_FOUND"
    PATH_NOT_ALLOWED = "PATH_NOT_ALLOWED"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    BI_QUERY_FAILED = "BI_QUERY_FAILED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    INVALID_RECORD_TYPE = "INVALID_RECORD_TYPE"
    INVALID_DATA = "INVALID_DATA"
    RECORD_NOT_RECONCILED = "RECORD_NOT_RECONCILED"
    CONFLICTING_OPERATION = "CONFLICTING_OPERATION"
    OA_SUBMISSION_FAILED = "OA_SUBMISSION_FAILED"
    OA_RECORD_NOT_FOUND = "OA_RECORD_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolError(Exception):
    """An expected, documented tool failure."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message

    def as_envelope(self) -> dict:
        return {
            "status": "error",
            "error_code": self.error_code,
            "message": self.message,
        }


def success(result: dict) -> dict:
    return {"status": "success", "result": result}
