"""Regression tests for CSV structural validation (round 2: R2-1 / R2-2)."""

from __future__ import annotations

from backend.app.models import OaReconciliationRecord, Task
from backend.app.services.demo_workflow import (
    DemoFlowError,
    run_normal_flow,
)
from backend.app.tools import read_data_file, validate_data

HEADER = (
    "supplier_id,supplier_name,order_id,amount,date,payment_status,"
    "record_status\n"
)
VALID_ROW = "SUP-001,ABC Ltd,ORD-1001,5000.00,2026-09-18,pending,active"
REFERENCE = {
    "supplier_id": "SUP-001",
    "supplier_name": "ABC Ltd",
    "order_id": "ORD-1001",
    "amount": "5000.00",
    "date": "2026-09-18",
    "payment_status": "pending",
    "record_status": "active",
}
FIELDS = [
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
]


def _write(settings, text, name="structure.csv"):
    path = settings.upload_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


# ----------------------------------------------------------------- R2-1
def test_extra_data_cell_is_rejected(temp_settings):
    path = _write(temp_settings, HEADER + VALID_ROW + ",5200.00\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_CSV_STRUCTURE"
    assert "row 2" in response["message"].lower()
    assert "8" in response["message"]
    assert "7" in response["message"]


def test_extra_cell_blocks_normal_flow(db_session, temp_settings):
    path = _write(temp_settings, HEADER + VALID_ROW + ",5200.00\n")

    try:
        run_normal_flow(db_session, file_path=path, settings=temp_settings)
    except DemoFlowError:
        pass
    else:  # pragma: no cover
        raise AssertionError("normal flow accepted a truncated CSV row")

    task = db_session.query(Task).order_by(Task.id.desc()).first()
    assert task.status != "completed"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_extra_cell_later_in_file_reports_its_row(temp_settings):
    second = "SUP-002,Bright Trading,ORD-2001,8900.00,2026-09-20,pending,active"
    path = _write(
        temp_settings,
        HEADER + VALID_ROW + "\n" + second + ",1.00\n",
    )

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_CSV_STRUCTURE"
    assert "row 3" in response["message"].lower()


def test_extra_empty_cell_from_trailing_separator_is_rejected(temp_settings):
    path = _write(temp_settings, HEADER + VALID_ROW + ",\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_CSV_STRUCTURE"


def test_validate_data_reports_extra_cell_as_error(temp_settings):
    path = _write(temp_settings, HEADER + VALID_ROW + ",5200.00\n")

    response = validate_data(
        str(path),
        reference_records=[REFERENCE],
        settings=temp_settings,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_CSV_STRUCTURE"


def test_short_row_is_padded_and_missing_required_fields_flagged(
    temp_settings,
):
    path = _write(temp_settings, HEADER + "SUP-001,ABC Ltd,ORD-1001\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "success"
    data = response["result"]["records"][0]["data"]
    assert data["supplier_id"] == "SUP-001"
    assert data["amount"] is None
    assert data["record_status"] is None

    check = validate_data(str(path), settings=temp_settings)

    assert check["status"] == "success"
    result = check["result"]
    missing_fields = {
        issue["field"]
        for issue in result["issues"]
        if issue["type"] == "missing_value"
    }
    assert missing_fields == {
        "amount",
        "date",
        "payment_status",
        "record_status",
    }
    assert result["invalid_rows"] == 1


def test_exact_width_rows_still_pass(temp_settings):
    second_row = (
        "SUP-002,Bright Trading,ORD-2001,8900.00,2026-09-20,pending,active"
    )
    reference_two = {
        "supplier_id": "SUP-002",
        "supplier_name": "Bright Trading",
        "order_id": "ORD-2001",
        "amount": "8900.00",
        "date": "2026-09-20",
        "payment_status": "pending",
        "record_status": "active",
    }
    path = _write(
        temp_settings, HEADER + VALID_ROW + "\n" + second_row + "\n"
    )

    response = validate_data(
        str(path),
        reference_records=[REFERENCE, reference_two],
        settings=temp_settings,
    )

    assert response["status"] == "success"
    assert response["result"]["issues"] == []


# ----------------------------------------------------------------- R2-2
def test_unterminated_quote_is_a_tool_error(temp_settings):
    path = _write(
        temp_settings,
        HEADER + VALID_ROW.removesuffix("active") + '"active',
    )

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "error"
    assert response["error_code"] == "CSV_PARSE_ERROR"


def test_unterminated_quote_blocks_validation_and_normal_flow(
    db_session, temp_settings
):
    path = _write(
        temp_settings,
        HEADER + VALID_ROW.removesuffix("active") + '"active',
    )

    check = validate_data(
        str(path),
        reference_records=[REFERENCE],
        settings=temp_settings,
    )
    assert check["status"] == "error"
    assert check["error_code"] == "CSV_PARSE_ERROR"

    try:
        run_normal_flow(db_session, file_path=path, settings=temp_settings)
    except DemoFlowError:
        pass
    else:  # pragma: no cover
        raise AssertionError("normal flow accepted a broken CSV quote")

    task = db_session.query(Task).order_by(Task.id.desc()).first()
    assert task.status != "completed"
    assert db_session.query(OaReconciliationRecord).count() == 0


def test_unterminated_quote_mid_file_is_rejected(temp_settings):
    text = (
        HEADER
        + VALID_ROW
        + "\n"
        + 'SUP-002,"Bright Trading,ORD-2001,8900.00,2026-09-20,pending,active\n'
    )
    path = _write(temp_settings, text)

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "error"
    assert response["error_code"] == "CSV_PARSE_ERROR"
    assert "line" in response["message"].lower()


# ------------------------------------------- preserved legitimate quoting
def test_escaped_quotes_still_parse(temp_settings):
    row = (
        'SUP-001,"ABC ""Ltd""",ORD-1001,5000.00,2026-09-18,pending,active'
    )
    path = _write(temp_settings, HEADER + row + "\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert (
        response["result"]["records"][0]["data"]["supplier_name"]
        == 'ABC "Ltd"'
    )


def test_quoted_comma_and_newline_still_parse(temp_settings):
    row = 'SUP-001,"ABC, Ltd\nSecond line",ORD-1001,5000.00,2026-09-18,pending,active'
    path = _write(temp_settings, HEADER + row + "\n" + VALID_ROW + "\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    assert result["row_count"] == 2
    assert (
        result["records"][0]["data"]["supplier_name"]
        == "ABC, Ltd\nSecond line"
    )
    assert result["records"][1]["row"] == 4


def test_blank_lines_still_keep_row_numbers(temp_settings):
    path = _write(temp_settings, HEADER + "\n" + VALID_ROW + "\n")

    response = read_data_file(str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert response["result"]["row_count"] == 1
    assert response["result"]["records"][0]["row"] == 3
