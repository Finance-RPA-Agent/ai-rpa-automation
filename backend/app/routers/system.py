from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models import (
    Task,
    ExcelException,
    BIInventory,
    User,
    OfficeApproval
)


router = APIRouter(
    prefix="/system",
    tags=["System"]
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


@router.get("/status")
def get_system_status(
    db: Session = Depends(get_db)
):
    total_tasks = db.query(Task).count()

    pending_tasks = db.query(Task).filter(
        Task.status == "pending"
    ).count()

    running_tasks = db.query(Task).filter(
        Task.status == "running"
    ).count()

    waiting_tasks = db.query(Task).filter(
        Task.status == "waiting_confirmation"
    ).count()

    completed_tasks = db.query(Task).filter(
        Task.status == "completed"
    ).count()

    failed_tasks = db.query(Task).filter(
        Task.status == "failed"
    ).count()

    pending_exceptions = db.query(
        ExcelException
    ).filter(
        ExcelException.status == "pending"
    ).count()

    pending_approvals = db.query(
        OfficeApproval
    ).filter(
        OfficeApproval.status == "pending"
    ).count()

    return {
        "success": True,
        "system": "AI-RPA Finance Automation Platform",
        "status": "online",
        "statistics": {
            "users": db.query(User).count(),
            "tasks": {
                "total": total_tasks,
                "pending": pending_tasks,
                "running": running_tasks,
                "waiting_confirmation": waiting_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks
            },
            "excel_exceptions": {
                "total": db.query(ExcelException).count(),
                "pending": pending_exceptions
            },
            "bi_inventory_records": db.query(
                BIInventory
            ).count(),
            "office_approvals": {
                "total": db.query(OfficeApproval).count(),
                "pending": pending_approvals
            }
        },
        "connectors": {
            "excel": "available",
            "bi": "available",
            "office_automation": "available"
        }
    }