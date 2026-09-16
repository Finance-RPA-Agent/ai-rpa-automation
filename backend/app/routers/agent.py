from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import pandas as pd
import os
import json

from backend.app.database import SessionLocal
from backend.app.models import (
    Task,
    TaskLog,
    ExcelException,
    BIInventory,
    User,
    OfficeApproval
)


router = APIRouter(
    prefix="/agent",
    tags=["Agent"]
)


class AgentTaskRequest(BaseModel):
    description: str
    filename: str | None = None
    user_id: int | None = None


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def parse_description(description: str):
    text = description.lower()

    steps = []

    if "excel" in text or "表格" in text:
        steps.append("excel_validate")

    if "bi" in text or "库存" in text:
        steps.append("bi_check")

    if "异常" in text:
        steps.append("exception_handle")

    steps.append("office_approval")
    steps.append("generate_result")

    return steps


@router.post("/parse")
def parse_task(
    request: AgentTaskRequest,
    db: Session = Depends(get_db)
):
    if request.user_id is not None:
        user = db.query(User).filter(
            User.id == request.user_id
        ).first()

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

    steps = parse_description(request.description)

    new_task = Task(
        description=request.description,
        status="pending",
        filename=request.filename,
        user_id=request.user_id
    )

    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    return {
        "success": True,
        "task_id": new_task.id,
        "user_id": new_task.user_id,
        "description": request.description,
        "filename": new_task.filename,
        "task_type": "finance_data_processing",
        "status": new_task.status,
        "steps": steps
    }


@router.post("/run/{task_id}")
def run_task(
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

    steps = parse_description(task.description)

    if task.status == "completed":
        try:
            saved_result = (
                json.loads(task.result)
                if task.result
                else None
            )
        except (json.JSONDecodeError, TypeError):
            saved_result = task.result

        return {
            "success": True,
            "task_id": task.id,
            "user_id": task.user_id,
            "status": task.status,
            "filename": task.filename,
            "steps": steps,
            "result": saved_result,
            "message": "Task has already been completed."
        }

    task.status = "running"

    db.add(
        TaskLog(
            task_id=task.id,
            action="Agent Start",
            status="started",
            message="Agent started task execution."
        )
    )

    db.commit()

    excel_result = None
    bi_result = None
    office_result = None

    for step in steps:

        if step == "excel_validate":
            if not task.filename:
                raise HTTPException(
                    status_code=400,
                    detail="Excel filename is required."
                )

            file_path = os.path.join(
                "uploads",
                task.filename
            )

            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=404,
                    detail="Excel file not found."
                )

            df = pd.read_excel(file_path)

            exceptions = []

            for index, row in df.iterrows():
                excel_row = index + 2

                for column in df.columns:
                    value = row[column]

                    if pd.isna(value):
                        exceptions.append({
                            "type": "missing_value",
                            "row": excel_row,
                            "column": str(column),
                            "value": None,
                            "message": f"{column} is missing.",
                            "suggestion": (
                                "Please manually enter the missing value."
                            )
                        })

                    elif (
                        pd.api.types.is_number(value)
                        and value < 0
                    ):
                        exceptions.append({
                            "type": "negative_value",
                            "row": excel_row,
                            "column": str(column),
                            "value": value,
                            "message": f"{column} cannot be negative.",
                            "suggestion": (
                                "Please check whether the value "
                                "was entered incorrectly."
                            )
                        })

            for column in df.columns:
                duplicated = df[column].duplicated(
                    keep=False
                )

                for index in df.index[duplicated]:
                    value = df.loc[index, column]

                    if pd.notna(value):
                        exceptions.append({
                            "type": "duplicate_value",
                            "row": index + 2,
                            "column": str(column),
                            "value": value,
                            "message": (
                                f"Duplicate value found in {column}."
                            ),
                            "suggestion": (
                                "Please check whether this "
                                "record is duplicated."
                            )
                        })

            existing_exceptions = (
                db.query(ExcelException)
                .filter(
                    ExcelException.task_id == task.id
                )
                .all()
            )

            if not existing_exceptions:
                for exception in exceptions:
                    db.add(
                        ExcelException(
                            task_id=task.id,
                            filename=task.filename,
                            row=exception["row"],
                            column=exception["column"],
                            value=(
                                str(exception["value"])
                                if exception["value"] is not None
                                else None
                            ),
                            type=exception["type"],
                            message=exception["message"],
                            suggestion=exception["suggestion"],
                            status="pending"
                        )
                    )

            db.flush()

            saved_exceptions = (
                db.query(ExcelException)
                .filter(
                    ExcelException.task_id == task.id
                )
                .all()
            )

            pending_count = sum(
                1
                for exception in saved_exceptions
                if exception.status == "pending"
            )

            handled_count = (
                len(saved_exceptions) - pending_count
            )

            processed_filename = (
                f"processed_{task.filename}"
            )

            processed_path = os.path.join(
                "outputs",
                processed_filename
            )

            excel_result = {
                "filename": task.filename,
                "rows": len(df),
                "exceptions_count": len(saved_exceptions),
                "pending_exceptions": pending_count,
                "handled_exceptions": handled_count,
                "processed_file": (
                    processed_path
                    if os.path.exists(processed_path)
                    else None
                )
            }

            db.add(
                TaskLog(
                    task_id=task.id,
                    action="Excel Validation",
                    status="completed",
                    message=(
                        f"Excel validation completed. "
                        f"{len(saved_exceptions)} exceptions found."
                    )
                )
            )

        elif step == "bi_check":
            inventory = db.query(
                BIInventory
            ).all()

            bi_result = [
                {
                    "material_code": item.material_code,
                    "warehouse": item.warehouse,
                    "quantity": item.quantity
                }
                for item in inventory
            ]

            db.add(
                TaskLog(
                    task_id=task.id,
                    action="BI Inventory Query",
                    status="completed",
                    message=(
                        f"BI inventory query completed. "
                        f"{len(bi_result)} records found."
                    )
                )
            )

        elif step == "exception_handle":
            exceptions = (
                db.query(ExcelException)
                .filter(
                    ExcelException.task_id == task.id
                )
                .all()
            )

            pending_count = sum(
                1
                for exception in exceptions
                if exception.status == "pending"
            )

            if pending_count > 0:
                task.status = "waiting_confirmation"

                db.add(
                    TaskLog(
                        task_id=task.id,
                        action="Exception Handling",
                        status="waiting_confirmation",
                        message=(
                            f"{pending_count} exceptions are waiting "
                            f"for human confirmation."
                        )
                    )
                )

                db.commit()

                return {
                    "success": True,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "pending_exceptions": pending_count,
                    "message": (
                        "Task is waiting for Excel exception "
                        "human confirmation."
                    )
                }

            db.add(
                TaskLog(
                    task_id=task.id,
                    action="Exception Handling",
                    status="completed",
                    message="All exceptions have been handled."
                )
            )

        elif step == "office_approval":
            existing_approval = (
                db.query(OfficeApproval)
                .filter(
                    OfficeApproval.task_id == task.id
                )
                .first()
            )

            if existing_approval is None:
                new_approval = OfficeApproval(
                    task_id=task.id,
                    title=(
                        "Finance Data Processing Approval "
                        f"- Task {task.id}"
                    ),
                    status="pending",
                    requested_by=task.user_id,
                    message=(
                        "Please review and approve the "
                        "processed finance data."
                    )
                )

                db.add(new_approval)
                db.flush()

                task.status = "waiting_confirmation"

                db.add(
                    TaskLog(
                        task_id=task.id,
                        action="Office Approval",
                        status="waiting_confirmation",
                        message=(
                            f"Office approval {new_approval.id} "
                            f"created and is waiting for "
                            f"human confirmation."
                        )
                    )
                )

                db.commit()

                return {
                    "success": True,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "office_result": {
                        "approval_id": new_approval.id,
                        "status": new_approval.status,
                        "title": new_approval.title
                    },
                    "message": (
                        "Excel exceptions have been handled. "
                        "Task is now waiting for Office approval."
                    )
                }

            office_result = {
                "approval_id": existing_approval.id,
                "status": existing_approval.status,
                "title": existing_approval.title
            }

            if existing_approval.status == "pending":
                task.status = "waiting_confirmation"

                db.commit()

                return {
                    "success": True,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "office_result": office_result,
                    "message": (
                        "Task is waiting for Office approval."
                    )
                }

            if existing_approval.status == "rejected":
                task.status = "waiting_confirmation"

                db.add(
                    TaskLog(
                        task_id=task.id,
                        action="Office Approval",
                        status="rejected",
                        message=(
                            f"Office approval "
                            f"{existing_approval.id} "
                            f"was rejected."
                        )
                    )
                )

                db.commit()

                return {
                    "success": False,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "office_result": office_result,
                    "message": (
                        "Office approval was rejected. "
                        "Task cannot be completed."
                    )
                }

            if existing_approval.status == "approved":
                db.add(
                    TaskLog(
                        task_id=task.id,
                        action="Office Approval",
                        status="completed",
                        message=(
                            f"Office approval "
                            f"{existing_approval.id} "
                            f"has been approved."
                        )
                    )
                )

        elif step == "generate_result":
            exceptions = (
                db.query(ExcelException)
                .filter(
                    ExcelException.task_id == task.id
                )
                .all()
            )

            pending_count = sum(
                1
                for exception in exceptions
                if exception.status == "pending"
            )

            if pending_count > 0:
                task.status = "waiting_confirmation"

                db.commit()

                return {
                    "success": True,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "office_result": office_result,
                    "pending_exceptions": pending_count,
                    "message": (
                        "Task is waiting for human confirmation."
                    )
                }

            approval = (
                db.query(OfficeApproval)
                .filter(
                    OfficeApproval.task_id == task.id
                )
                .first()
            )

            if (
                approval is None
                or approval.status != "approved"
            ):
                task.status = "waiting_confirmation"

                db.commit()

                return {
                    "success": True,
                    "task_id": task.id,
                    "user_id": task.user_id,
                    "status": task.status,
                    "filename": task.filename,
                    "steps": steps,
                    "excel_result": excel_result,
                    "bi_result": bi_result,
                    "office_result": office_result,
                    "message": (
                        "Task is waiting for Office approval."
                    )
                }

            original_file = os.path.join(
                "uploads",
                task.filename
            )

            processed_filename = (
                f"processed_{task.filename}"
            )

            processed_file = os.path.join(
                "outputs",
                processed_filename
            )

            if not os.path.exists(processed_file):
                processed_file = None

            final_result = {
                "task_id": task.id,
                "user_id": task.user_id,
                "status": "completed",
                "filename": task.filename,
                "original_file": original_file,
                "processed_file": processed_file,
                "excel": excel_result,
                "bi_records": (
                    len(bi_result)
                    if bi_result
                    else 0
                ),
                "exceptions_total": len(exceptions),
                "exceptions_approved": sum(
                    1
                    for exception in exceptions
                    if exception.status == "approved"
                ),
                "exceptions_modified": sum(
                    1
                    for exception in exceptions
                    if exception.status == "modified"
                ),
                "exceptions_rejected": sum(
                    1
                    for exception in exceptions
                    if exception.status == "rejected"
                ),
                "exceptions_pending": pending_count,
                "office_approval": {
                    "approval_id": approval.id,
                    "status": approval.status
                }
            }

            task.result = json.dumps(
                final_result,
                ensure_ascii=False
            )

            task.status = "completed"

            db.add(
                TaskLog(
                    task_id=task.id,
                    action="Generate Result",
                    status="completed",
                    message=(
                        "Final result generated successfully."
                    )
                )
            )

    db.commit()
    db.refresh(task)

    return {
        "success": True,
        "task_id": task.id,
        "user_id": task.user_id,
        "status": task.status,
        "filename": task.filename,
        "steps": steps,
        "excel_result": excel_result,
        "bi_result": bi_result,
        "office_result": office_result,
        "message": (
            "Agent executed the workflow successfully."
        )
    }