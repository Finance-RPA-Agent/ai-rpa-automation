"""Build the committed demo input files from the canonical demo data.

Run from the project root:

    python scripts/build_demo_files.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.services.demo_data import DEMO_CASES  # noqa: E402


def write_csv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(row)


def write_xlsx(path: Path, rows) -> None:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Sheet1"
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def main() -> int:
    settings = get_settings()
    settings.demo_data_dir.mkdir(parents=True, exist_ok=True)

    for case in DEMO_CASES:
        target = settings.demo_data_dir / case.filename
        if case.file_type == "xlsx":
            write_xlsx(target, case.rows)
        else:
            write_csv(target, case.rows)
        print(f"wrote {target}")

    print(
        f"\n{len(DEMO_CASES)} demo files written to "
        f"{settings.demo_data_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
