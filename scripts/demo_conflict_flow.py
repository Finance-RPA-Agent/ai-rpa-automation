"""Deterministic amount-conflict demo (not an AI agent run).

Run from the project root:

    python scripts/demo_conflict_flow.py

The script reads the conflict file, queries BI, shows both amount sources
plus the exact difference, archives the conflict as an OA exception with
``review_status=pending_review`` and leaves the task in
``waiting_confirmation``.  It never submits a normal result and never
modifies the source file.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database import Base, SessionLocal, engine  # noqa: E402
from backend.app.services.demo_workflow import (  # noqa: E402
    run_conflict_flow,
)


def main() -> int:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        try:
            summary = run_conflict_flow(session)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            print("\nCONFLICT DEMO FAILED")
            return 1

    print("CONFLICT DEMO COMPLETED (waiting for manual verification)")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
