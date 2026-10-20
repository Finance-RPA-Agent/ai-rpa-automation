"""Local Runtime demo with synthetic CSV data and a disposable SQLite database.

Run from the repository root: python -m scripts.run_agent_runtime_demo
--scenario clean_success. No HTTP, default database, or confirmation grant.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.database import Base
from backend.app.models import FinancialRecord, OaReconciliationRecord, Task
from backend.app.services.agent_runtime import AgentRuntime
from backend.app.tools.rules import CORE_FIELDS


SCENARIOS = ("clean_success", "validation_issue", "bi_no_match")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_NOTICE = (
    "Trace may contain business data. Keep it private; it is not a public log. "
    "This demo uses synthetic data and simulated BI/OA only."
)


def run_demo(scenario: str) -> dict:
    """Observe the real Runtime; expectations only check, never set its status.

    Each call owns and removes its CSV/SQLite sandbox. No caller-controlled
    files, database, confirmation provider or authority flags are accepted.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown demo scenario: {scenario!r}")

    with tempfile.TemporaryDirectory(prefix="agent-runtime-demo-") as directory:
        root = Path(directory)
        settings = Settings(
            base_dir=root, upload_dir=root / "uploads",
            demo_data_dir=root / "demo_data", output_dir=root / "outputs",
        )
        settings.demo_data_dir.mkdir()
        source = settings.demo_data_dir / "reconciliation.csv"
        row = {
            "supplier_id": "DEMO-SUP-001", "supplier_name": "Synthetic Supplier",
            "order_id": "DEMO-ORD-001", "amount": "5000.00",
            "date": "2026-10-20", "payment_status": "pending",
            "record_status": "active",
        }
        bi_row = dict(row)
        if scenario == "validation_issue":
            row["amount"] = "-1.00"  # Explicitly invalid under existing rules.
        elif scenario == "bi_no_match":
            row["order_id"] = "DEMO-ORD-NO-MATCH"
        with source.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CORE_FIELDS)
            writer.writeheader()
            writer.writerow(row)
        before = hashlib.sha256(source.read_bytes()).hexdigest()

        # Only this explicit, disposable engine is connected. The imported
        # project default engine/SessionLocal is never used.
        engine = create_engine(f"sqlite:///{(root / 'demo.sqlite3').as_posix()}")
        try:
            Base.metadata.create_all(bind=engine)  # Existing schema, new temp DB.
            with Session(engine) as db:
                task = Task(description=f"Synthetic Runtime demo: {scenario}", status="running")
                db.add(task)
                db.add(FinancialRecord(**bi_row, source="agent-runtime-demo"))
                db.commit()
                context = {
                    "task_id": task.id, "file_path": str(source),
                    "operation_id": f"runtime-demo:{scenario}:v1",
                }
                result = AgentRuntime(db=db, settings=settings).run(context)
                # Read the actual simulated OA table, not a mocked receipt.
                oa_records = [
                    {
                        "task_id": record.task_id, "record_id": record.record_id,
                        "record_type": record.record_type,
                        "operation_id": record.operation_id,
                        "review_status": record.review_status,
                        "data": json.loads(record.payload),
                    }
                    for record in db.query(OaReconciliationRecord)
                    .order_by(OaReconciliationRecord.id).all()
                ]
        finally:
            engine.dispose()

        runtime = asdict(result)
        runtime["task_status"] = result.task_status.value
        trace = [
            {key: item[key] for key in ("tool", "attempt", "classification", "retry_allowed")}
            for item in runtime["trace"]
        ]
        source_unchanged = before == hashlib.sha256(source.read_bytes()).hexdigest()
        queries = [item for item in result.trace if item.tool == "query_bi"]
        checks = {
            "source_unchanged": source_unchanged,
            "no_runtime_error": result.error_code is None,
            "no_unexpected_retry": all(item.attempt == 0 for item in result.trace),
        }
        if scenario == "clean_success":
            checks.update(
                completed=result.task_status.value == "completed",
                normal_archive_classification=result.classification == "oa_result_archived",
                four_tools_used={item.tool for item in result.trace} == {
                    "read_data_file", "validate_data", "query_bi", "submit_to_oa",
                },
                no_confirmation_request=result.confirmation_request is None,
                normal_oa_row=len(oa_records) == 1 and all(
                    item["record_type"] == "reconciliation_result"
                    and item["review_status"] == "archived"
                    and item["task_id"] == context["task_id"]
                    and item["operation_id"] == context["operation_id"] + ":result:2"
                    and item["data"] == {**row, "record_status": "matched"}
                    for item in oa_records
                ),
            )
        else:
            checks.update(
                waiting_confirmation=result.task_status.value == "waiting_confirmation",
                confirmation_requested=result.confirmation_request is not None,
                oa_table_empty=not oa_records,
                no_oa_tool_call=all(item.tool != "submit_to_oa" for item in result.trace),
                business_classification=result.classification == (
                    "business_issue" if scenario == "validation_issue" else "business_no_match"
                ),
            )
            if scenario == "bi_no_match":
                checks["bi_success_with_no_match"] = len(queries) == 1 and all(
                    item.envelope["status"] == "success"
                    and item.envelope["result"]["records"] == []
                    and item.classification == "business_no_match"
                    and not item.retry_allowed for item in queries
                )
            else:
                checks["invalid_amount_reported"] = any(
                    item.tool == "validate_data"
                    and item.envelope.get("status") == "success"
                    and any(issue["type"] == "invalid_amount"
                            for issue in item.envelope["result"]["issues"])
                    for item in result.trace
                )

        return {
            "scenario": scenario,
            "harness_status": "passed" if all(checks.values()) else "failed",
            "task_status": runtime["task_status"],
            "classification": result.classification, "reason": result.reason,
            "error_code": result.error_code,
            "confirmation_request": runtime["confirmation_request"],
            "trace": trace, "oa_records": oa_records, "demo_checks": checks,
            "trace_notice": TRACE_NOTICE, "runtime_result": runtime,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", required=True, choices=SCENARIOS)
    parser.add_argument(
        "--save-trace", action="store_true",
        help="Save private full JSON under ignored outputs/agent_runtime_demo/.",
    )
    args = parser.parse_args(argv)
    summary = None
    try:
        summary = run_demo(args.scenario)
        if args.save_trace:
            folder = PROJECT_ROOT / "outputs" / "agent_runtime_demo"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{args.scenario}-{uuid.uuid4().hex}.json"
            # Exclusive creation prevents silently replacing an earlier trace.
            with path.open("x", encoding="utf-8") as handle:
                json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write("\n")
            summary["trace_file"] = str(path)
        printable = {key: value for key, value in summary.items() if key != "runtime_result"}
        print(json.dumps(printable, ensure_ascii=False, indent=2, allow_nan=False))
        return 0 if summary["harness_status"] == "passed" else 1
    except Exception as exc:
        failure = {key: value for key, value in (summary or {}).items() if key != "runtime_result"}
        failure.update(
            scenario=args.scenario, harness_status="failed",
            harness_error={"type": type(exc).__name__, "message": str(exc)},
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
