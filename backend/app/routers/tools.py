"""FastAPI entry points for the four RPA tools.

The routes only adapt HTTP to the reusable tool layer in
``backend.app.tools``; no validation algorithm is duplicated here.

- ``GET  /tools``                     list the fixed tool whitelist
- ``POST /tools/execute``             unified dispatch entry point
- ``POST /tools/files``               safe upload; returns a file reference
- ``GET  /tools/oa/records``          list archived OA records
- ``GET  /tools/oa/records/{id}``     read one archived OA record

Tool envelopes are always returned with HTTP 200; an HTTP 422 only means
the request body itself was malformed for FastAPI.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.database import SessionLocal
from backend.app.tools import (
    ErrorCode,
    ToolError,
    execute_tool,
    list_oa_records,
    list_tools,
    read_oa_record,
)
from backend.app.tools.errors import success

router = APIRouter(prefix="/tools", tags=["RPA Tools"])

ALLOWED_UPLOAD_SUFFIXES = (".xlsx", ".csv")


class ToolExecuteRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] | None = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_settings_dependency() -> Settings:
    return get_settings()


@router.get("")
def get_tools() -> dict:
    return success({"tools": list_tools()})


@router.post("/execute")
def run_tool(
    request: ToolExecuteRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dependency),
) -> dict:
    return execute_tool(
        request.tool,
        request.arguments,
        db=db,
        settings=settings,
    )


@router.post("/files")
async def upload_tool_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings_dependency),
) -> dict:
    original_name = Path(file.filename or "").name
    suffix = Path(original_name).suffix.lower()

    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        return ToolError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "Only .xlsx and UTF-8 .csv files can be uploaded.",
        ).as_envelope()

    content = await file.read()
    if not content:
        return ToolError(
            ErrorCode.EMPTY_FILE,
            "The uploaded file is empty.",
        ).as_envelope()

    if len(content) > settings.max_upload_bytes:
        return ToolError(
            ErrorCode.FILE_TOO_LARGE,
            (
                "The uploaded file is larger than the configured limit "
                f"({settings.max_upload_bytes} bytes)."
            ),
        ).as_envelope()

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = settings.upload_dir / stored_name
    target.write_bytes(content)

    try:
        relative_path = target.relative_to(settings.base_dir)
        file_path = relative_path.as_posix()
    except ValueError:
        file_path = str(target)

    return success(
        {
            "file_id": stored_name,
            "original_name": original_name,
            "file_path": file_path,
            "file_type": suffix.lstrip("."),
            "size_bytes": len(content),
        }
    )


@router.get("/oa/records")
def get_oa_records(
    task_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dependency),
) -> dict:
    return list_oa_records(task_id=task_id, db=db, settings=settings)


@router.get("/oa/records/{record_id}")
def get_oa_record(
    record_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dependency),
) -> dict:
    return read_oa_record(record_id=record_id, db=db, settings=settings)
