from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
import os

from backend.app.database import SessionLocal
from backend.app.models import (
    Task,
    ExcelException,
    OfficeApproval,
    TaskLog
)

router = APIRouter(
    prefix="/reports",
    tags=["Final Audit Report"]
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/{task_id}")
def generate_final_audit_report(
    task_id: int,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(
        Task.id == task_id
    ).first()

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    exceptions = db.query(ExcelException).filter(
        ExcelException.task_id == task_id
    ).all()

    approval = db.query(OfficeApproval).filter(
        OfficeApproval.task_id == task_id
    ).order_by(
        OfficeApproval.id.desc()
    ).first()

    logs = db.query(TaskLog).filter(
        TaskLog.task_id == task_id
    ).order_by(
        TaskLog.id.asc()
    ).all()

    processed_file = None

    if task.filename:
        candidate = os.path.join(
            "outputs",
            f"processed_{task.filename}"
        )

        if os.path.exists(candidate):
            processed_file = candidate

    approved_count = sum(
        1 for item in exceptions
        if item.status == "approved"
    )

    modified_count = sum(
        1 for item in exceptions
        if item.status == "modified"
    )

    rejected_count = sum(
        1 for item in exceptions
        if item.status == "rejected"
    )

    pending_count = sum(
        1 for item in exceptions
        if item.status == "pending"
    )

    exception_details = []

    for item in exceptions:
        exception_details.append({
            "id": item.id,
            "row": item.row,
            "column": item.column,
            "type": item.type,
            "original_value": item.value,
            "message": item.message,
            "status": item.status,
            "resolution": item.resolution
        })

    operation_logs = []

    for log in logs:
        operation_logs.append({
            "action": log.action,
            "status": log.status,
            "message": log.message,
            "created_at": (
                log.created_at.isoformat()
                if log.created_at
                else None
            )
        })

    stored_result = None

    if task.result:
        try:
            stored_result = json.loads(task.result)
        except Exception:
            stored_result = task.result

    report = {
        "report_type": "finance_reimbursement_audit_report",
        "task": {
            "task_id": task.id,
            "user_id": task.user_id,
            "description": task.description,
            "status": task.status,
            "created_at": (
                task.created_at.isoformat()
                if task.created_at
                else None
            )
        },
        "files": {
            "source_file": task.filename,
            "processed_file": processed_file
        },
        "audit_summary": {
            "total_exceptions": len(exceptions),
            "approved": approved_count,
            "modified": modified_count,
            "rejected": rejected_count,
            "pending": pending_count
        },
        "exception_details": exception_details,
        "office_approval": {
            "approval_id": (
                approval.id if approval else None
            ),
            "status": (
                approval.status
                if approval
                else "not_created"
            ),
            "message": (
                approval.message
                if approval
                else None
            )
        },
        "agent_result": stored_result,
        "operation_logs": operation_logs,
        "final_status": task.status
    }

    return {
        "success": True,
        "report": report
    }