from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
import os

from backend.app.database import SessionLocal
from backend.app.models import (
    OfficeApproval,
    Task,
    User,
    TaskLog,
    ExcelException
)

router = APIRouter(
    prefix="/office",
    tags=["Office Automation"]
)


class ApprovalCreate(BaseModel):
    task_id: int
    title: str
    requested_by: int | None = None
    message: str | None = None


class ApprovalUpdate(BaseModel):
    status: str
    message: str | None = None


class ApprovalResponse(BaseModel):
    id: int
    task_id: int
    title: str
    status: str
    requested_by: int | None
    message: str | None
    created_at: datetime | None
    updated_at: datetime | None

    class Config:
        from_attributes = True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def build_oa_form(task: Task, db: Session):
    exceptions = db.query(ExcelException).filter(
        ExcelException.task_id == task.id
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
        1 for item in exceptions if item.status == "approved"
    )

    modified_count = sum(
        1 for item in exceptions if item.status == "modified"
    )

    rejected_count = sum(
        1 for item in exceptions if item.status == "rejected"
    )

    pending_count = sum(
        1 for item in exceptions if item.status == "pending"
    )

    return {
        "form_type": "finance_reimbursement_review",
        "task_id": task.id,
        "user_id": task.user_id,
        "task_description": task.description,
        "source_file": task.filename,
        "processed_file": processed_file,
        "total_exceptions": len(exceptions),
        "approved_exceptions": approved_count,
        "modified_exceptions": modified_count,
        "rejected_exceptions": rejected_count,
        "pending_exceptions": pending_count,
        "rpa_status": "form_filled",
        "generated_by": "AI-RPA Agent"
    }


@router.post("/approvals", response_model=ApprovalResponse)
def create_approval(
    approval: ApprovalCreate,
    db: Session = Depends(get_db)
):
    task = db.query(Task).filter(
        Task.id == approval.task_id
    ).first()

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )

    if approval.requested_by is not None:
        user = db.query(User).filter(
            User.id == approval.requested_by
        ).first()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

    new_approval = OfficeApproval(
        task_id=approval.task_id,
        title=approval.title,
        requested_by=approval.requested_by,
        message=approval.message,
        status="pending"
    )

    db.add(new_approval)

    db.add(
        TaskLog(
            task_id=approval.task_id,
            action="Office Approval Created",
            status="pending",
            message=f"Office approval created: {approval.title}"
        )
    )

    db.commit()
    db.refresh(new_approval)

    return new_approval


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse)
def get_approval(
    approval_id: int,
    db: Session = Depends(get_db)
):
    approval = db.query(OfficeApproval).filter(
        OfficeApproval.id == approval_id
    ).first()

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail="Approval not found"
        )

    return approval


@router.patch("/approvals/{approval_id}", response_model=ApprovalResponse)
def update_approval(
    approval_id: int,
    update: ApprovalUpdate,
    db: Session = Depends(get_db)
):
    approval = db.query(OfficeApproval).filter(
        OfficeApproval.id == approval_id
    ).first()

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail="Approval not found"
        )

    allowed_statuses = [
        "pending",
        "approved",
        "rejected"
    ]

    if update.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Status must be pending, approved, or rejected"
        )

    approval.status = update.status
    approval.message = update.message
    approval.updated_at = datetime.now()

    db.add(
        TaskLog(
            task_id=approval.task_id,
            action="Office Approval Updated",
            status=update.status,
            message=update.message or f"Approval status changed to {update.status}"
        )
    )

    db.commit()
    db.refresh(approval)

    return approval


@router.post("/rpa/fill/{task_id}")
def fill_oa_finance_form(
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

    oa_form = build_oa_form(task, db)

    if oa_form["pending_exceptions"] > 0:
        raise HTTPException(
            status_code=400,
            detail="Excel exceptions must be handled before RPA fills the OA form"
        )

    existing_approval = db.query(OfficeApproval).filter(
        OfficeApproval.task_id == task_id
    ).order_by(
        OfficeApproval.id.desc()
    ).first()

    if existing_approval is None:
        existing_approval = OfficeApproval(
            task_id=task.id,
            title=f"Finance Reimbursement Review - Task {task.id}",
            status="pending",
            requested_by=task.user_id,
            message="OA finance form automatically filled by RPA."
        )

        db.add(existing_approval)
        db.flush()

    db.add(
        TaskLog(
            task_id=task.id,
            action="RPA OA Form Filled",
            status="completed",
            message="Finance review data was automatically transferred to the simulated OA form."
        )
    )

    db.commit()
    db.refresh(existing_approval)

    return {
        "success": True,
        "task_id": task.id,
        "rpa": {
            "action": "fill_oa_finance_form",
            "status": "completed"
        },
        "oa_form": oa_form,
        "approval": {
            "approval_id": existing_approval.id,
            "status": existing_approval.status
        },
        "message": "RPA automatically filled the simulated OA finance form."
    }


@router.get("/rpa/form/{task_id}")
def get_oa_finance_form(
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

    oa_form = build_oa_form(task, db)

    approval = db.query(OfficeApproval).filter(
        OfficeApproval.task_id == task_id
    ).order_by(
        OfficeApproval.id.desc()
    ).first()

    return {
        "success": True,
        "task_id": task.id,
        "oa_form": oa_form,
        "approval": {
            "approval_id": approval.id if approval else None,
            "status": approval.status if approval else "not_created"
        }
    }