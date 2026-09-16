from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Form
from sqlalchemy.orm import Session
import pandas as pd
import os

from backend.app.database import SessionLocal
from backend.app.models import ExcelException, Task

router = APIRouter(
    prefix="/excel",
    tags=["Excel"]
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename.endswith((".xlsx", ".xls")):
        return {
            "success": False,
            "message": "Please upload an Excel file."
        }

    os.makedirs("uploads", exist_ok=True)

    file_path = os.path.join("uploads", file.filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    df = pd.read_excel(file_path)

    return {
        "success": True,
        "filename": file.filename,
        "rows": len(df),
        "columns": list(df.columns)
    }

@router.post("/validate")
async def validate_excel(
    task_id: int = Form(...),
    file: UploadFile = File(...),
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

    if not file.filename.endswith((".xlsx", ".xls")):
        return {
            "success": False,
            "message": "Please upload an Excel file."
        }

    os.makedirs("uploads", exist_ok=True)

    file_path = os.path.join("uploads", file.filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    df = pd.read_excel(file_path)

    exceptions = []

    for index, row in df.iterrows():
        excel_row = index + 2

        for column in df.columns:
            value = row[column]

            if pd.isna(value):
                exception = {
                    "type": "missing_value",
                    "row": excel_row,
                    "column": str(column),
                    "value": None,
                    "message": f"{column} is missing.",
                    "suggestion": "Please manually enter the missing value."
                }

                exceptions.append(exception)

            elif pd.api.types.is_number(value) and value < 0:
                exception = {
                    "type": "negative_value",
                    "row": excel_row,
                    "column": str(column),
                    "value": value,
                    "message": f"{column} cannot be negative.",
                    "suggestion": "Please check whether the value was entered incorrectly."
                }

                exceptions.append(exception)

    for column in df.columns:
        duplicated = df[column].duplicated(keep=False)

        for index in df.index[duplicated]:
            value = df.loc[index, column]

            if pd.notna(value):
                exception = {
                    "type": "duplicate_value",
                    "row": index + 2,
                    "column": str(column),
                    "value": value,
                    "message": f"Duplicate value found in {column}.",
                    "suggestion": "Please check whether this record is duplicated."
                }

                exceptions.append(exception)

    saved_exceptions = []

    for exception in exceptions:
        database_exception = ExcelException(
            task_id=task_id,
            filename=file.filename,
            row=exception["row"],
            column=exception["column"],
            value=str(exception["value"]) if exception["value"] is not None else None,
            type=exception["type"],
            message=exception["message"],
            suggestion=exception["suggestion"],
            status="pending"
        )

        db.add(database_exception)
        db.flush()

        exception["id"] = database_exception.id
        saved_exceptions.append(exception)

    db.commit()

    return {
        "success": True,
        "task_id": task_id,
        "filename": file.filename,
        "rows": len(df),
        "exceptions_count": len(saved_exceptions),
        "exceptions": saved_exceptions
    }

@router.get("/{task_id}/exceptions")
def get_task_exceptions(
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

    return {
        "success": True,
        "task_id": task_id,
        "exceptions_count": len(exceptions),
        "exceptions": exceptions
    }