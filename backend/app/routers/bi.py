from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal
from backend.app.models import BIInventory

router = APIRouter(
    prefix="/bi",
    tags=["BI"]
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/inventory")
def get_inventory(
    material_code: str | None = None,
    warehouse: str | None = None,
    db: Session = Depends(get_db)
):
    query = db.query(BIInventory)

    if material_code:
        query = query.filter(
            BIInventory.material_code == material_code
        )

    if warehouse:
        query = query.filter(
            BIInventory.warehouse == warehouse
        )

    inventory = query.all()

    return {
        "success": True,
        "count": len(inventory),
        "data": inventory
    }