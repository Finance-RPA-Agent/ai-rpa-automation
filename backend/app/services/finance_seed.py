"""Idempotent seeding of the simulated BI finance records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.models import FinancialRecord
from backend.app.services.demo_data import DEMO_BI_RECORDS


def seed_financial_records(
    db: Session,
    records: list[dict] | None = None,
) -> dict:
    """Insert or update demo records by business key.

    Running this multiple times is safe: existing ``supplier_id`` +
    ``order_id`` rows are updated, missing rows are inserted.  Unrelated
    user data is never deleted.
    """

    source_records = records if records is not None else DEMO_BI_RECORDS
    inserted = 0
    updated = 0

    for record in source_records:
        existing = (
            db.query(FinancialRecord)
            .filter(
                FinancialRecord.supplier_id == record["supplier_id"],
                FinancialRecord.order_id == record["order_id"],
            )
            .first()
        )
        if existing is None:
            db.add(
                FinancialRecord(
                    supplier_id=record["supplier_id"],
                    supplier_name=record["supplier_name"],
                    order_id=record["order_id"],
                    amount=record["amount"],
                    date=record["date"],
                    payment_status=record["payment_status"],
                    record_status=record["record_status"],
                    source=record.get("source", "demo_seed"),
                )
            )
            inserted += 1
        else:
            existing.supplier_name = record["supplier_name"]
            existing.amount = record["amount"]
            existing.date = record["date"]
            existing.payment_status = record["payment_status"]
            existing.record_status = record["record_status"]
            existing.source = record.get("source", "demo_seed")
            existing.updated_at = datetime.now()
            updated += 1

    db.commit()

    return {
        "seeded": len(source_records),
        "inserted": inserted,
        "updated": updated,
        "total_records": db.query(FinancialRecord).count(),
    }
