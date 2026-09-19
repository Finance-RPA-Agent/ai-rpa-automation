"""Reusable RPA tools for the supplier finance reconciliation scenario.

Public Python entry points::

    from backend.app.tools import (
        read_data_file,
        validate_data,
        query_bi,
        submit_to_oa,
        execute_tool,
    )

Every function returns the unified envelope ``{"status": ...}`` described
in ``docs/RPA_TOOLS.md``.  Business findings are returned as successful
results; only technical failures produce the error envelope.
"""

from backend.app.tools.bi_query import query_bi
from backend.app.tools.dispatcher import TOOL_SPECS, ToolSpec, execute_tool, list_tools
from backend.app.tools.errors import ErrorCode, ToolError
from backend.app.tools.file_reader import read_data_file
from backend.app.tools.oa_submitter import (
    list_oa_records,
    read_oa_record,
    submit_to_oa,
)
from backend.app.tools.validation import validate_data

__all__ = [
    "ErrorCode",
    "TOOL_SPECS",
    "ToolError",
    "ToolSpec",
    "execute_tool",
    "list_oa_records",
    "list_tools",
    "query_bi",
    "read_data_file",
    "read_oa_record",
    "submit_to_oa",
    "validate_data",
]
