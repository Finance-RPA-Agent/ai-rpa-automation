"""query_bi: query the simulated BI finance layer.

The simulated BI source is the ``bi_financial_records`` table (supplier
financial records), not the legacy inventory table.  At least one query
key is required; both keys are combined with AND.  An empty result is a
business result, not a technical failure.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from backend.app.config import get_settings
from backend.app.database import SessionLocal
from backend.app.models import FinancialRecord
from backend.app.tools.errors import ErrorCode, ToolError, success
from backend.app.tools.serialization import to_jsonable


def _validate_key(value, name: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str):
        raise ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            f"{name} must be a string when provided.",
        )
    text = value.strip()
    return text or None


def _record_to_dict(record: FinancialRecord) -> dict:
    try:
        amount = to_jsonable(Decimal(record.amount))
    except (InvalidOperation, TypeError, ValueError):
        amount = record.amount

    return {
        "record_id": record.id,
        "supplier_id": record.supplier_id,
        "supplier_name": record.supplier_name,
        "order_id": record.order_id,
        "amount": amount,
        "date": record.date,
        "payment_status": record.payment_status,
        "record_status": record.record_status,
    }


def query_bi(supplier_id=None, order_id=None, *, db=None, settings=None) -> dict:
    settings = settings or get_settings()
    own_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        supplier_key = _validate_key(supplier_id, "supplier_id")
        order_key = _validate_key(order_id, "order_id")

        if not supplier_key and not order_key:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "At least one of supplier_id or order_id is required.",
            )

        query = session.query(FinancialRecord)
        if supplier_key:
            query = query.filter(
                FinancialRecord.supplier_id == supplier_key
            )
        if order_key:
            query = query.filter(FinancialRecord.order_id == order_key)

        records = query.order_by(FinancialRecord.id.asc()).all()

        result = {
            "records": [_record_to_dict(record) for record in records],
            "count": len(records),
            "query": {
                "supplier_id": supplier_key,
                "order_id": order_key,
            },
            "source": "simulated_bi_financial_records",
        }
        return success(to_jsonable(result))
    except ToolError as exc:
        _safe_rollback(session)
        return exc.as_envelope()
    except Exception as exc:  # noqa: BLE001 - report a stable tool error
        _safe_rollback(session)
        return ToolError(
            ErrorCode.BI_QUERY_FAILED,
            f"Failed to retrieve BI data: {exc}",
        ).as_envelope()
    finally:
        if own_session:
            session.close()


def _safe_rollback(session) -> None:
    try:
        session.rollback()
    except Exception:  # noqa: BLE001 - a broken rollback must not hide the error
        pass
