"""Tests for the unified tool dispatcher."""

from __future__ import annotations

from backend.app.models import FinancialRecord, Task
from backend.app.tools import TOOL_SPECS, execute_tool, list_tools


def test_tool_whitelist_contains_the_four_tools():
    assert set(TOOL_SPECS) == {
        "read_data_file",
        "validate_data",
        "query_bi",
        "submit_to_oa",
    }


def test_list_tools_exposes_parameters():
    tools = {tool["name"]: tool for tool in list_tools()}

    assert tools["read_data_file"]["parameters"] == [
        "file_path",
        "sheet_name",
    ]
    assert tools["submit_to_oa"]["requires_database"] is True
    assert tools["read_data_file"]["requires_database"] is False


def test_unknown_tool_is_predictable():
    response = execute_tool("delete_everything", {})

    assert response["status"] == "error"
    assert response["error_code"] == "UNKNOWN_TOOL"


def test_arguments_must_be_an_object():
    response = execute_tool("read_data_file", ["not", "an", "object"])

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_ARGUMENTS"


def test_unexpected_argument_is_rejected():
    response = execute_tool(
        "query_bi",
        {"supplier_id": "SUP-001", "sql": "DROP TABLE tasks"},
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_ARGUMENTS"


def test_dispatch_read_data_file(make_csv, temp_settings):
    path = make_csv(
        [
            ["supplier_id", "order_id"],
            ["SUP-001", "ORD-1001"],
        ],
        name="dispatch.csv",
    )

    response = execute_tool(
        "read_data_file",
        {"file_path": str(path)},
        settings=temp_settings,
    )

    assert response["status"] == "success"
    assert response["result"]["row_count"] == 1


def test_dispatch_validate_data_reports_business_issues(
    make_csv, temp_settings
):
    path = make_csv(
        [
            ["supplier_id", "order_id"],
            ["SUP-001", "ORD-1001"],
        ],
        name="dispatch-bad.csv",
    )

    response = execute_tool(
        "validate_data",
        {"file_path": str(path)},
        settings=temp_settings,
    )

    assert response["status"] == "success"
    assert response["result"]["missing_columns"]


def test_dispatch_query_bi(db_session):
    db_session.add(
        FinancialRecord(
            supplier_id="SUP-001",
            supplier_name="ABC Ltd",
            order_id="ORD-1001",
            amount="5000.00",
            date="2026-09-18",
            payment_status="pending",
            record_status="active",
            source="test",
        )
    )
    db_session.commit()

    response = execute_tool(
        "query_bi",
        {"order_id": "ORD-1001"},
        db=db_session,
    )

    assert response["status"] == "success"
    assert response["result"]["count"] == 1


def test_dispatch_submit_to_oa(db_session):
    task = Task(description="dispatch task", status="running")
    db_session.add(task)
    db_session.commit()

    response = execute_tool(
        "submit_to_oa",
        {
            "task_id": task.id,
            "record_type": "reconciliation_result",
            "data": {
                "supplier_id": "SUP-001",
                "order_id": "ORD-1001",
                "amount": 5000.00,
                "date": "2026-09-18",
                "payment_status": "pending",
                "record_status": "matched",
            },
            "operation_id": "dispatch-op-1",
        },
        db=db_session,
    )

    assert response["status"] == "success"
    assert response["result"]["submitted"] is True
