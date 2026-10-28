"""Explicit, deterministic demo orchestration for the four tools.

This module is *not* an AI agent.  It is a fixed script that plays the
role the future agent / backend integration will play: it calls the four
tools in order and owns the task status transitions.  The tool functions
themselves never advance global task state.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.config import Settings, get_settings
from backend.app.models import OaReconciliationRecord, Task, TaskLog
from backend.app.services.demo_data import NORMAL_CASE
from backend.app.services.finance_seed import seed_financial_records
from backend.app.tools import (
    query_bi,
    read_data_file,
    read_oa_record,
    submit_to_oa,
    validate_data,
)

CONFLICT_ISSUE_TYPES = (
    "amount_mismatch",
    "payment_status_mismatch",
    "record_status_mismatch",
    "record_not_found",
    "ambiguous_reference",
    "invalid_reference_amount",
)


class DemoFlowError(RuntimeError):
    """The demo did not observe the result it is supposed to demonstrate."""


def _file_hash(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _unchanged(before_hash: str | None, path: Path) -> bool:
    after_hash = _file_hash(path)
    return before_hash is not None and before_hash == after_hash


def _require_success(response: dict, tool_name: str) -> dict:
    if response.get("status") != "success":
        raise DemoFlowError(
            f"{tool_name} failed with {response.get('error_code')}: "
            f"{response.get('message')}"
        )
    return response["result"]


def _set_running(db: Session, task_id: int, message: str) -> Task:
    task = db.get(Task, task_id)
    task.status = "running"
    db.add(
        TaskLog(
            task_id=task_id,
            action="Demo Flow Start",
            status="running",
            message=message,
        )
    )
    db.commit()
    return task


def _finish_task(
    db: Session,
    task_id: int,
    status: str,
    summary: dict,
    action: str,
    message: str,
) -> None:
    task = db.get(Task, task_id)
    task.status = status
    task.result = json.dumps(summary, ensure_ascii=False)
    db.add(
        TaskLog(
            task_id=task_id,
            action=action,
            status=status,
            message=message,
        )
    )
    db.commit()


def _mark_failed(db: Session, task_id: int, error: str) -> None:
    db.rollback()
    task = db.get(Task, task_id)
    if task is None or task.status != "running":
        return
    task.status = "failed"
    db.add(
        TaskLog(
            task_id=task_id,
            action="Demo Flow Failed",
            status="failed",
            message=error[:500],
        )
    )
    db.commit()


def _get_or_create_task(db: Session, task_id: int | None, description: str) -> Task:
    if task_id is not None:
        task = db.get(Task, task_id)
        if task is None:
            raise DemoFlowError(f"Task {task_id} does not exist.")
        return task

    task = Task(description=description, status="pending")
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _query_references(db: Session, records: list[dict]) -> list[dict]:
    references: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for record in records:
        data = record["data"]
        supplier_id = data.get("supplier_id")
        order_id = data.get("order_id")
        if not supplier_id or not order_id:
            continue
        if not isinstance(supplier_id, str) or not isinstance(order_id, str):
            continue
        key = (supplier_id, order_id)
        if key in seen:
            continue
        seen.add(key)
        result = _require_success(
            query_bi(
                supplier_id=supplier_id,
                order_id=order_id,
                db=db,
            ),
            "query_bi",
        )
        references.extend(result["records"])

    return references


def _row_data_by_key(records: list[dict]) -> dict[tuple, dict]:
    by_key = {}
    for record in records:
        data = record["data"]
        supplier_id = data.get("supplier_id")
        order_id = data.get("order_id")
        if isinstance(supplier_id, str) and isinstance(order_id, str):
            by_key[(supplier_id, order_id)] = data
    return by_key


def run_normal_flow(
    db: Session,
    *,
    file_path=None,
    task_id: int | None = None,
    seed_bi: bool = True,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    if seed_bi:
        seed_financial_records(db)

    if file_path is None:
        file_path = settings.demo_data_dir / NORMAL_CASE.filename
    resolved_file = Path(file_path)

    task = _get_or_create_task(
        db,
        task_id,
        description="Demo: supplier reconciliation normal flow",
    )
    _set_running(db, task.id, f"Normal demo started for {resolved_file}.")

    try:
        before_hash = _file_hash(resolved_file)
        read_result = _require_success(
            read_data_file(str(resolved_file), settings=settings),
            "read_data_file",
        )
        records = read_result["records"]

        references = _query_references(db, records)

        validation_result = _require_success(
            validate_data(
                str(resolved_file),
                reference_records=references,
                settings=settings,
            ),
            "validate_data",
        )

        base_summary = {
            "flow": "normal",
            "task_id": task.id,
            "file_path": str(resolved_file),
            "row_count": validation_result["total_rows"],
            "valid_rows": validation_result["valid_rows"],
            "invalid_rows": validation_result["invalid_rows"],
            "bi_records": len(references),
            "source_unchanged": _unchanged(before_hash, resolved_file),
        }

        if (
            validation_result["invalid_rows"] > 0
            or validation_result["issues"]
        ):
            base_summary["issues"] = validation_result["issues"]
            _finish_task(
                db,
                task.id,
                "waiting_confirmation",
                base_summary,
                "Demo Flow Waiting Confirmation",
                "Normal demo input produced issues; human review is required.",
            )
            raise DemoFlowError(
                "The normal demo file produced business issues: "
                f"{[issue['type'] for issue in validation_result['issues']]}"
            )

        references_by_key = {
            (
                reference["supplier_id"],
                reference["order_id"],
            ): reference
            for reference in references
        }
        excel_by_key = _row_data_by_key(records)

        oa_record_ids = []
        for key in excel_by_key:
            bi_row = references_by_key.get(key)
            if bi_row is None:
                raise DemoFlowError(
                    f"No BI reference found for {key} during submission."
                )
            submit_data = {
                "supplier_id": bi_row["supplier_id"],
                "supplier_name": bi_row["supplier_name"],
                "order_id": bi_row["order_id"],
                "amount": bi_row["amount"],
                "date": bi_row["date"],
                "payment_status": bi_row["payment_status"],
                "record_status": "matched",
            }
            submitted = _require_success(
                submit_to_oa(
                    task_id=task.id,
                    record_type="reconciliation_result",
                    data=submit_data,
                    operation_id=(
                        f"normal:{task.id}:{key[0]}:{key[1]}"
                    ),
                    db=db,
                    settings=settings,
                ),
                "submit_to_oa",
            )
            oa_record_ids.append(submitted["record_id"])

        read_back = _require_success(
            read_oa_record(oa_record_ids[0], db=db, settings=settings),
            "read_oa_record",
        )

        summary = dict(
            base_summary,
            oa_records=oa_record_ids,
            read_back=read_back["record"]["data"],
            source_unchanged=_unchanged(before_hash, resolved_file),
        )
        _finish_task(
            db,
            task.id,
            "completed",
            summary,
            "Demo Flow Completed",
            (
                f"Normal demo completed; {len(oa_record_ids)} OA records "
                "archived."
            ),
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, task.id, str(exc))
        raise


def run_conflict_flow(
    db: Session,
    *,
    file_path=None,
    task_id: int | None = None,
    seed_bi: bool = True,
    settings: Settings | None = None,
) -> dict:
    settings = settings or get_settings()
    if seed_bi:
        seed_financial_records(db)

    if file_path is None:
        from backend.app.services.demo_data import (
            AMOUNT_CONFLICT_CASE,
        )

        file_path = settings.demo_data_dir / AMOUNT_CONFLICT_CASE.filename
    resolved_file = Path(file_path)

    task = _get_or_create_task(
        db,
        task_id,
        description="Demo: supplier reconciliation conflict flow",
    )
    _set_running(
        db, task.id, f"Conflict demo started for {resolved_file}."
    )

    try:
        before_hash = _file_hash(resolved_file)
        read_result = _require_success(
            read_data_file(str(resolved_file), settings=settings),
            "read_data_file",
        )
        records = read_result["records"]

        references = _query_references(db, records)
        validation_result = _require_success(
            validate_data(
                str(resolved_file),
                reference_records=references,
                settings=settings,
            ),
            "validate_data",
        )

        records_by_row = {
            record["row"]: record["data"] for record in records
        }

        conflicts = []
        unarchived_issues = []

        for issue in validation_result["issues"]:
            issue_type = issue.get("type")
            row_number = issue.get("row")
            excel_row = (
                records_by_row.get(row_number)
                if row_number is not None
                else None
            )
            supplier_id = (
                excel_row.get("supplier_id") if excel_row else None
            )
            order_id = excel_row.get("order_id") if excel_row else None

            archivable = (
                issue_type in CONFLICT_ISSUE_TYPES
                and excel_row is not None
                and bool(supplier_id)
                and bool(order_id)
            )
            if not archivable:
                unarchived_issues.append(
                    {
                        "row": row_number,
                        "field": issue.get("field"),
                        "type": issue_type,
                        "message": issue.get("message"),
                    }
                )
                continue

            conflict = {
                "row": row_number,
                "supplier_id": supplier_id,
                "order_id": order_id,
                "issue_type": issue_type,
                "message": issue.get("message"),
            }
            for extra in (
                "excel_amount",
                "bi_amount",
                "difference",
                "excel_value",
                "bi_value",
            ):
                if extra in issue:
                    conflict[extra] = issue[extra]
            conflicts.append(conflict)

        if not conflicts and not unarchived_issues:
            summary = {
                "flow": "conflict",
                "task_id": task.id,
                "file_path": str(resolved_file),
                "total_rows": validation_result["total_rows"],
                "valid_rows": validation_result["valid_rows"],
                "invalid_rows": validation_result["invalid_rows"],
                "conflicts": [],
                "unarchived_issues": [],
                "oa_records": [],
                "normal_result_recorded": False,
                "source_unchanged": _unchanged(
                    before_hash, resolved_file
                ),
                "message": (
                    "No conflicts or issues were found in the conflict "
                    "demo input, so there is nothing to hold for review."
                ),
            }
            _finish_task(
                db,
                task.id,
                "completed",
                summary,
                "Demo Flow Completed",
                "No conflicts were found in the conflict demo input.",
            )
            raise DemoFlowError(
                "The conflict demo file did not produce any conflict."
            )

        if not conflicts:
            summary = {
                "flow": "conflict",
                "task_id": task.id,
                "file_path": str(resolved_file),
                "total_rows": validation_result["total_rows"],
                "valid_rows": validation_result["valid_rows"],
                "invalid_rows": validation_result["invalid_rows"],
                "conflicts": [],
                "unarchived_issues": unarchived_issues,
                "oa_records": [],
                "normal_result_recorded": False,
                "source_unchanged": _unchanged(
                    before_hash, resolved_file
                ),
                "message": (
                    "Unresolved validation issues were found, but they "
                    "are not reconcilable conflict records that can be "
                    "archived; the task stays waiting for confirmation."
                ),
            }
            _finish_task(
                db,
                task.id,
                "waiting_confirmation",
                summary,
                "Demo Flow Waiting Confirmation",
                (
                    "Unresolved issues require correction before any "
                    "reconciliation can continue."
                ),
            )
            raise DemoFlowError(
                "The conflict demo input has unresolved issues that "
                "cannot be archived as conflicts: "
                f"{sorted({issue['type'] for issue in unarchived_issues})}"
            )

        oa_record_ids = []
        for conflict in conflicts:
            data = {
                "supplier_id": conflict["supplier_id"],
                "order_id": conflict["order_id"],
                "issue_type": conflict["issue_type"],
                "row": conflict["row"],
                "message": conflict["message"],
            }
            for extra in (
                "excel_amount",
                "bi_amount",
                "difference",
                "excel_value",
                "bi_value",
            ):
                if extra in conflict:
                    data[extra] = conflict[extra]
            submitted = _require_success(
                submit_to_oa(
                    task_id=task.id,
                    record_type="reconciliation_exception",
                    data=data,
                    operation_id=(
                        f"exception:{task.id}:{conflict['supplier_id']}:"
                        f"{conflict['order_id']}:{conflict['issue_type']}:"
                        f"{conflict['row']}"
                    ),
                    db=db,
                    settings=settings,
                ),
                "submit_to_oa",
            )
            conflict["oa_record_id"] = submitted["record_id"]
            conflict["review_status"] = submitted["review_status"]
            oa_record_ids.append(submitted["record_id"])

        normal_result_count = (
            db.query(OaReconciliationRecord)
            .filter(
                OaReconciliationRecord.task_id == task.id,
                OaReconciliationRecord.record_type
                == "reconciliation_result",
            )
            .count()
        )
        if normal_result_count:
            raise DemoFlowError(
                "A normal reconciliation result was recorded for a task "
                "that still has unresolved conflicts."
            )

        summary = {
            "flow": "conflict",
            "task_id": task.id,
            "file_path": str(resolved_file),
            "total_rows": validation_result["total_rows"],
            "valid_rows": validation_result["valid_rows"],
            "invalid_rows": validation_result["invalid_rows"],
            "conflicts": conflicts,
            "unarchived_issues": unarchived_issues,
            "oa_records": oa_record_ids,
            "normal_result_recorded": False,
            "source_unchanged": _unchanged(
                before_hash, resolved_file
            ),
            "message": (
                "Amount/status conflicts were archived as exceptions with "
                "review_status=pending_review. Manual verification is "
                "required; no normal reconciliation result was submitted "
                "and the source file was not modified."
            ),
        }
        _finish_task(
            db,
            task.id,
            "waiting_confirmation",
            summary,
            "Demo Flow Waiting Confirmation",
            (
                f"{len(conflicts)} conflict(s) archived for manual "
                "verification; task is waiting for confirmation."
            ),
        )

        if unarchived_issues:
            raise DemoFlowError(
                "The input also contains unresolved issues that cannot "
                "be archived as conflicts: "
                f"{sorted({issue['type'] for issue in unarchived_issues})}"
            )

        return summary
    except Exception as exc:  # noqa: BLE001
        _mark_failed(db, task.id, str(exc))
        raise
