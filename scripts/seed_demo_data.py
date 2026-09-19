"""Idempotently seed the simulated BI finance records.

Run from the project root:

    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --reset-demo-table

``--reset-demo-table`` only clears the dedicated
``bi_financial_records`` demo table; it never touches tasks, users,
exceptions, approvals or any other business table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database import Base, SessionLocal, engine  # noqa: E402
from backend.app.models import FinancialRecord  # noqa: E402
from backend.app.services.finance_seed import (  # noqa: E402
    seed_financial_records,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed simulated BI supplier finance records."
    )
    parser.add_argument(
        "--reset-demo-table",
        action="store_true",
        help=(
            "Delete existing rows in bi_financial_records before seeding "
            "(demo table only)."
        ),
    )
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        if args.reset_demo_table:
            deleted = session.query(FinancialRecord).delete()
            session.commit()
            print(f"cleared {deleted} existing demo BI record(s)")

        summary = seed_financial_records(session)

    print(
        "seed complete: "
        f"{summary['inserted']} inserted, "
        f"{summary['updated']} updated, "
        f"{summary['total_records']} total records"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
