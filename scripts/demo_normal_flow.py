"""Deterministic normal-path demo (not an AI agent run).

Run from the project root:

    python scripts/demo_normal_flow.py

The script creates a task, calls the four tools in order, archives the
matching OA results and reads one of them back.  The task is marked
``completed`` only when every step succeeds.
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
    run_normal_flow,
)


def main() -> int:
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        try:
            summary = run_normal_flow(session)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            print("\nNORMAL DEMO FAILED")
            return 1

    print("NORMAL DEMO COMPLETED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
