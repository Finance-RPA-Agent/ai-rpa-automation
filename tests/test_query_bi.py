"""Tests for the query_bi tool."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from backend.app.models import FinancialRecord
from backend.app.tools import query_bi


def _seed(db):
    records = [
        FinancialRecord(
            supplier_id="SUP-001",
            supplier_name="ABC Ltd",
            order_id="ORD-1001",
            amount="5000.00",
            date="2026-09-18",
            payment_status="pending",
            record_status="active",
            source="test",
        ),
        FinancialRecord(
            supplier_id="SUP-001",
            supplier_name="ABC Ltd",
            order_id="ORD-1002",
            amount="1250.50",
            date="2026-09-19",
            payment_status="paid",
            record_status="active",
            source="test",
        ),
        FinancialRecord(
            supplier_id="SUP-002",
            supplier_name="Bright Trading",
            order_id="ORD-2001",
            amount="8900.00",
            date="2026-09-20",
            payment_status="pending",
            record_status="active",
            source="test",
        ),
    ]
    db.add_all(records)
    db.commit()


def test_query_both_keys_returns_exact_record(db_session):
    _seed(db_session)

    response = query_bi(
        supplier_id="SUP-001",
        order_id="ORD-1001",
        db=db_session,
    )

    assert response["status"] == "success"
    result = response["result"]
    assert result["count"] == 1
    assert result["query"] == {
        "supplier_id": "SUP-001",
        "order_id": "ORD-1001",
    }
    record = result["records"][0]
    assert record["supplier_id"] == "SUP-001"
    assert record["supplier_name"] == "ABC Ltd"
    assert record["order_id"] == "ORD-1001"
    assert float(record["amount"]) == 5000.00
    assert record["date"] == "2026-09-18"
    assert record["payment_status"] == "pending"
    assert record["record_status"] == "active"


def test_query_supplier_only_returns_all_orders(db_session):
    _seed(db_session)

    response = query_bi(supplier_id="SUP-001", db=db_session)

    assert response["status"] == "success"
    orders = {
        record["order_id"]
        for record in response["result"]["records"]
    }
    assert orders == {"ORD-1001", "ORD-1002"}


def test_query_order_only(db_session):
    _seed(db_session)

    response = query_bi(order_id="ORD-2001", db=db_session)

    assert response["status"] == "success"
    assert response["result"]["count"] == 1


def test_query_empty_result_is_success(db_session):
    _seed(db_session)

    response = query_bi(
        supplier_id="SUP-404",
        order_id="ORD-404",
        db=db_session,
    )

    assert response["status"] == "success"
    assert response["result"]["records"] == []
    assert response["result"]["count"] == 0


def test_query_requires_at_least_one_key(db_session):
    response = query_bi(db=db_session)

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_ARGUMENTS"


def test_query_failure_returns_error_and_session_stays_usable(db_session):
    _seed(db_session)
    original_query = db_session.query

    def broken_query(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("simulated BI outage"))

    db_session.query = broken_query
    try:
        response = query_bi(supplier_id="SUP-001", db=db_session)
    finally:
        db_session.query = original_query

    assert response["status"] == "error"
    assert response["error_code"] == "BI_QUERY_FAILED"

    retry = query_bi(supplier_id="SUP-001", db=db_session)
    assert retry["status"] == "success"
    assert retry["result"]["count"] == 2
