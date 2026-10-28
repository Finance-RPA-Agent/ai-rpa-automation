"""submit_to_oa: archive structured reconciliation results / exceptions.

This simulates an OA archive.  It does **not** perform real payments,
transfers or final financial approvals.  Every write is tied to an
existing task and protected by an operation id so retries are idempotent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import OaReconciliationRecord, Task, TaskLog
from backend.app.tools.errors import ErrorCode, ToolError, success
from backend.app.tools.rules import (
    AmountError,
    DateRuleError,
    RECORD_TYPES,
    format_amount,
    normalise_status,
    parse_amount,
    parse_date,
)
from backend.app.tools.serialization import to_jsonable

FORBIDDEN_AUTHORITY_FIELDS = (
    "confirmed",
    "approved",
    "approved_by",
    "human_confirmed",
    "authorized_by",
)

AMOUNT_FIELDS = ("amount", "excel_amount", "bi_amount", "difference")
DATE_FIELDS = ("date",)

REQUIRED_DATA_FIELDS = {
    "reconciliation_result": (
        "supplier_id",
        "order_id",
        "amount",
        "date",
        "payment_status",
        "record_status",
    ),
    "reconciliation_exception": (
        "supplier_id",
        "order_id",
        "issue_type",
    ),
}


def _safe_rollback(session) -> None:
    try:
        session.rollback()
    except Exception:  # noqa: BLE001
        pass


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _canonical_value(key: str, value):
    if key in AMOUNT_FIELDS:
        try:
            return f"amount:{format_amount(parse_amount(value))}"
        except AmountError:
            return f"raw:{json.dumps(to_jsonable(value), sort_keys=True)}"
    if key in DATE_FIELDS:
        try:
            return f"date:{parse_date(value).isoformat()}"
        except DateRuleError:
            return f"raw:{json.dumps(to_jsonable(value), sort_keys=True)}"
    if isinstance(value, dict):
        return {
            str(inner_key): _canonical_value(str(inner_key), inner_value)
            for inner_key, inner_value in sorted(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value("", item) for item in value]
    return to_jsonable(value)


def _content_hash(data: dict) -> str:
    canonical = {
        str(key): _canonical_value(str(key), value)
        for key, value in sorted(data.items())
    }
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sanitise_data(record_type: str, data: dict) -> tuple[dict, list[str]]:
    cleaned = dict(data)
    ignored: list[str] = []

    for field in FORBIDDEN_AUTHORITY_FIELDS:
        if field in cleaned:
            ignored.append(field)
            del cleaned[field]

    if "review_status" in cleaned:
        ignored.append("review_status")
        del cleaned["review_status"]

    if record_type == "reconciliation_exception":
        cleaned["review_status"] = "pending_review"

    return cleaned, ignored


def _validate_business_data(record_type: str, data: dict) -> None:
    missing = [
        field
        for field in REQUIRED_DATA_FIELDS[record_type]
        if _is_blank(data.get(field))
    ]
    if missing:
        raise ToolError(
            ErrorCode.INVALID_DATA,
            (
                f"data for {record_type} is missing required field(s): "
                f"{', '.join(missing)}."
            ),
        )

    if record_type == "reconciliation_result":
        try:
            parse_amount(data.get("amount"))
        except AmountError as exc:
            raise ToolError(
                ErrorCode.INVALID_DATA,
                f"data.amount is not usable: {exc}.",
            ) from exc
        try:
            parse_date(data.get("date"))
        except DateRuleError as exc:
            raise ToolError(
                ErrorCode.INVALID_DATA,
                f"data.date is not usable: {exc}.",
            ) from exc

        if normalise_status(data.get("record_status")) != "matched":
            raise ToolError(
                ErrorCode.RECORD_NOT_RECONCILED,
                (
                    "Reconciliation results can only be archived when "
                    "record_status is 'matched'. Unresolved conflicts must "
                    "stay in review and must not be submitted as normal "
                    "results."
                ),
            )
    else:
        issue_type = normalise_status(data.get("issue_type"))
        if issue_type == "amount_mismatch":
            for field in ("excel_amount", "bi_amount"):
                try:
                    parse_amount(data.get(field))
                except AmountError as exc:
                    raise ToolError(
                        ErrorCode.INVALID_DATA,
                        (
                            "amount_mismatch exceptions require a usable "
                            f"{field}: {exc}."
                        ),
                    ) from exc


def _result_payload(record, replay: bool, ignored_fields: list[str]) -> dict:
    return {
        "record_id": record.record_id,
        "record_type": record.record_type,
        "submitted": True,
        "operation_id": record.operation_id,
        "review_status": record.review_status,
        "idempotent_replay": replay,
        "ignored_fields": ignored_fields,
    }


def _record_payload(record) -> dict:
    try:
        data = json.loads(record.payload)
    except (TypeError, json.JSONDecodeError):
        data = {"raw": record.payload}

    return {
        "record_id": record.record_id,
        "task_id": record.task_id,
        "record_type": record.record_type,
        "operation_id": record.operation_id,
        "review_status": record.review_status,
        "submitted_at": (
            record.created_at.isoformat() if record.created_at else None
        ),
        "data": data,
    }


def _find_existing(session, task_id: int, operation_id: str):
    return (
        session.query(OaReconciliationRecord)
        .filter(
            OaReconciliationRecord.task_id == task_id,
            OaReconciliationRecord.operation_id == operation_id,
        )
        .first()
    )


def submit_to_oa(
    task_id=None,
    record_type=None,
    data=None,
    *,
    operation_id=None,
    db=None,
    settings=None,
) -> dict:
    settings = settings or get_settings()
    own_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        if not isinstance(task_id, int) or isinstance(task_id, bool):
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "task_id is required and must be an integer.",
            )
        if record_type not in RECORD_TYPES:
            raise ToolError(
                ErrorCode.INVALID_RECORD_TYPE,
                (
                    "record_type must be one of: "
                    f"{', '.join(RECORD_TYPES)}."
                ),
            )
        if not isinstance(data, dict):
            raise ToolError(
                ErrorCode.INVALID_DATA,
                "data is required and must be an object.",
            )
        if operation_id is not None and (
            not isinstance(operation_id, str)
            or not operation_id.strip()
        ):
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                (
                    "operation_id must be a non-empty string when "
                    "provided."
                ),
            )

        task = session.get(Task, task_id)
        if task is None:
            raise ToolError(
                ErrorCode.TASK_NOT_FOUND,
                f"Task {task_id} does not exist.",
            )

        cleaned, ignored_fields = _sanitise_data(record_type, data)
        _validate_business_data(record_type, cleaned)

        content_hash = _content_hash(cleaned)
        resolved_operation_id = (
            operation_id.strip()
            if operation_id
            else f"auto:{content_hash[:16]}"
        )

        existing = _find_existing(
            session, task_id, resolved_operation_id
        )
        if existing is not None:
            if (
                existing.content_hash == content_hash
                and existing.record_type == record_type
            ):
                return success(
                    _result_payload(existing, True, ignored_fields)
                )
            raise ToolError(
                ErrorCode.CONFLICTING_OPERATION,
                (
                    f"Operation '{resolved_operation_id}' already exists "
                    "for this task with different content."
                ),
            )

        review_status = (
            "pending_review"
            if record_type == "reconciliation_exception"
            else "archived"
        )

        record = OaReconciliationRecord(
            task_id=task_id,
            record_type=record_type,
            operation_id=resolved_operation_id,
            payload=json.dumps(
                to_jsonable(cleaned),
                ensure_ascii=False,
                sort_keys=True,
            ),
            content_hash=content_hash,
            review_status=review_status,
            record_id=f"pending-{uuid.uuid4().hex}",
        )
        session.add(record)
        session.flush()

        created_at = record.created_at or datetime.now()
        record.record_id = (
            f"OA-{created_at:%Y%m%d}-{record.id:04d}"
        )

        session.add(
            TaskLog(
                task_id=task_id,
                action="OA Reconciliation Record Submitted",
                status="submitted",
                message=(
                    f"OA record {record.record_id} "
                    f"({record_type}) submitted; operation_id="
                    f"{resolved_operation_id}."
                ),
            )
        )
        session.commit()

        return success(
            _result_payload(record, False, ignored_fields)
        )
    except ToolError as exc:
        _safe_rollback(session)
        return exc.as_envelope()
    except IntegrityError:
        _safe_rollback(session)
        return _handle_integrity_error(
            session, task_id, record_type, operation_id, data
        )
    except Exception as exc:  # noqa: BLE001
        _safe_rollback(session)
        return ToolError(
            ErrorCode.OA_SUBMISSION_FAILED,
            f"Failed to submit the OA record: {exc}",
        ).as_envelope()
    finally:
        if own_session:
            session.close()


def _handle_integrity_error(
    session, task_id, record_type, operation_id, data
) -> dict:
    if operation_id is None:
        return ToolError(
            ErrorCode.OA_SUBMISSION_FAILED,
            "Failed to submit the OA record due to a database conflict.",
        ).as_envelope()

    existing = _find_existing(session, task_id, operation_id.strip())
    if existing is None:
        return ToolError(
            ErrorCode.OA_SUBMISSION_FAILED,
            "Failed to submit the OA record due to a database conflict.",
        ).as_envelope()

    cleaned, ignored_fields = _sanitise_data(record_type, data)
    if (
        existing.content_hash == _content_hash(cleaned)
        and existing.record_type == record_type
    ):
        return success(_result_payload(existing, True, ignored_fields))

    return ToolError(
        ErrorCode.CONFLICTING_OPERATION,
        (
            f"Operation '{operation_id.strip()}' already exists for this "
            "task with different content."
        ),
    ).as_envelope()


def read_oa_record(record_id=None, *, db=None, settings=None) -> dict:
    settings = settings or get_settings()
    own_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        if not isinstance(record_id, str) or not record_id.strip():
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "record_id is required and must be a string.",
            )

        record = (
            session.query(OaReconciliationRecord)
            .filter(
                OaReconciliationRecord.record_id == record_id.strip()
            )
            .first()
        )
        if record is None:
            raise ToolError(
                ErrorCode.OA_RECORD_NOT_FOUND,
                f"OA record '{record_id}' was not found.",
            )

        return success({"record": _record_payload(record)})
    except ToolError as exc:
        return exc.as_envelope()
    except Exception as exc:  # noqa: BLE001
        return ToolError(
            ErrorCode.OA_SUBMISSION_FAILED,
            f"Failed to read the OA record: {exc}",
        ).as_envelope()
    finally:
        if own_session:
            session.close()


def list_oa_records(task_id=None, *, db=None, settings=None) -> dict:
    settings = settings or get_settings()
    own_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        query = session.query(OaReconciliationRecord)
        if task_id is not None:
            if not isinstance(task_id, int) or isinstance(task_id, bool):
                raise ToolError(
                    ErrorCode.INVALID_ARGUMENTS,
                    "task_id must be an integer when provided.",
                )
            task = session.get(Task, task_id)
            if task is None:
                raise ToolError(
                    ErrorCode.TASK_NOT_FOUND,
                    f"Task {task_id} does not exist.",
                )
            query = query.filter(
                OaReconciliationRecord.task_id == task_id
            )

        records = query.order_by(
            OaReconciliationRecord.id.asc()
        ).all()

        return success(
            {
                "records": [
                    _record_payload(record) for record in records
                ],
                "count": len(records),
            }
        )
    except ToolError as exc:
        return exc.as_envelope()
    except Exception as exc:  # noqa: BLE001
        return ToolError(
            ErrorCode.OA_SUBMISSION_FAILED,
            f"Failed to list OA records: {exc}",
        ).as_envelope()
    finally:
        if own_session:
            session.close()
