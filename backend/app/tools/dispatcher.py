"""Fixed tool whitelist and the unified dispatch entry point.

``execute_tool`` never uses ``eval`` or dynamic imports.  Only the tools
registered in :data:`TOOL_SPECS` can be invoked and only their documented
parameters are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.app.tools.bi_query import query_bi
from backend.app.tools.errors import ErrorCode, ToolError
from backend.app.tools.file_reader import read_data_file
from backend.app.tools.oa_submitter import submit_to_oa
from backend.app.tools.validation import validate_data


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable
    parameters: tuple[str, ...]
    requires_db: bool
    description: str


TOOL_SPECS: dict[str, ToolSpec] = {
    "read_data_file": ToolSpec(
        name="read_data_file",
        handler=read_data_file,
        parameters=("file_path", "sheet_name"),
        requires_db=False,
        description=(
            "Read .xlsx / UTF-8 .csv data and return rows with row numbers."
        ),
    ),
    "validate_data": ToolSpec(
        name="validate_data",
        handler=validate_data,
        parameters=("file_path", "reference_records", "sheet_name"),
        requires_db=False,
        description=(
            "Validate required fields, formats, business keys and "
            "optionally compare against BI reference records."
        ),
    ),
    "query_bi": ToolSpec(
        name="query_bi",
        handler=query_bi,
        parameters=("supplier_id", "order_id"),
        requires_db=True,
        description=(
            "Query simulated BI supplier finance records by supplier_id "
            "and/or order_id."
        ),
    ),
    "submit_to_oa": ToolSpec(
        name="submit_to_oa",
        handler=submit_to_oa,
        parameters=("task_id", "record_type", "data", "operation_id"),
        requires_db=True,
        description=(
            "Archive a reconciliation result or exception in the "
            "simulated OA system."
        ),
    ),
}


def list_tools() -> list[dict]:
    return [
        {
            "name": spec.name,
            "parameters": list(spec.parameters),
            "description": spec.description,
            "requires_database": spec.requires_db,
        }
        for spec in TOOL_SPECS.values()
    ]


def execute_tool(tool=None, arguments=None, *, db=None, settings=None) -> dict:
    if not isinstance(tool, str) or tool not in TOOL_SPECS:
        return ToolError(
            ErrorCode.UNKNOWN_TOOL,
            (
                f"Unknown tool '{tool}'. Available tools: "
                f"{', '.join(TOOL_SPECS)}."
            ),
        ).as_envelope()

    spec = TOOL_SPECS[tool]
    arguments = {} if arguments is None else arguments
    if not isinstance(arguments, dict):
        return ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            "arguments must be an object.",
        ).as_envelope()

    unknown = set(arguments) - set(spec.parameters)
    if unknown:
        return ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            (
                f"Unexpected argument(s) for {tool}: "
                f"{', '.join(sorted(unknown))}."
            ),
        ).as_envelope()

    try:
        if spec.requires_db:
            return spec.handler(**arguments, db=db, settings=settings)
        return spec.handler(**arguments, settings=settings)
    except ToolError as exc:
        _safe_rollback(db)
        return exc.as_envelope()
    except TypeError as exc:
        return ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            f"Invalid arguments for {tool}: {exc}",
        ).as_envelope()
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(db)
        return ToolError(
            ErrorCode.INTERNAL_ERROR,
            f"Unexpected error while running {tool}: {exc}",
        ).as_envelope()


def _safe_rollback(db) -> None:
    if db is None:
        return
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass


__all__ = [
    "TOOL_SPECS",
    "ToolSpec",
    "execute_tool",
    "list_tools",
]
