"""Tests for the validate_data tool."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backend.app.tools import validate_data

CORE_FIELDS = [
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
]


def _row(
    supplier_id="SUP-001",
    supplier_name="ABC Ltd",
    order_id="ORD-1001",
    amount="5000.00",
    date="2026-09-18",
    payment_status="pending",
    record_status="active",
):
    return [
        supplier_id,
        supplier_name,
        order_id,
        amount,
        date,
        payment_status,
        record_status,
    ]


def _refs():
    return [
        {
            "supplier_id": "SUP-001",
            "supplier_name": "ABC Ltd",
            "order_id": "ORD-1001",
            "amount": 5000.00,
            "date": "2026-09-18",
            "payment_status": "pending",
            "record_status": "active",
        },
        {
            "supplier_id": "SUP-002",
            "supplier_name": "Bright Trading",
            "order_id": "ORD-2001",
            "amount": 8900.00,
            "date": "2026-09-20",
            "payment_status": "pending",
            "record_status": "active",
        },
    ]


def _issues_of(result, issue_type):
    return [
        issue
        for issue in result["issues"]
        if issue["type"] == issue_type
    ]


def test_clean_file_without_reference_is_valid(make_csv, temp_settings):
    path = make_csv([CORE_FIELDS, _row()])

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    assert result["total_rows"] == 1
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0
    assert result["issues"] == []
    assert result["reference_compared"] is False


def test_same_supplier_and_status_on_different_orders_is_not_duplicate(
    make_csv, temp_settings
):
    rows = [
        CORE_FIELDS,
        _row(order_id="ORD-1001"),
        _row(order_id="ORD-1002", date="2026-09-19"),
        _row(order_id="ORD-1003", date="2026-09-20"),
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    assert result["issues"] == []
    assert result["valid_rows"] == 3
    assert result["invalid_rows"] == 0


def test_missing_required_column_is_reported_once(make_csv, temp_settings):
    rows = [
        ["supplier_id", "order_id", "amount", "date"],
        ["SUP-001", "ORD-1001", "10.00", "2026-09-18"],
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    missing = _issues_of(result, "missing_column")
    assert [issue["field"] for issue in missing] == [
        "supplier_name",
        "payment_status",
        "record_status",
    ]
    assert all(issue["row"] is None for issue in missing)
    assert result["missing_columns"] == [
        "supplier_name",
        "payment_status",
        "record_status",
    ]
    assert result["total_rows"] == 1
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 0


def test_missing_cell_is_missing_value(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row(amount="")]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    issues = _issues_of(result, "missing_value")
    assert len(issues) == 1
    assert issues[0]["row"] == 2
    assert issues[0]["field"] == "amount"
    assert result["invalid_rows"] == 1
    assert result["valid_rows"] == 0


def test_bad_amounts_are_reported(make_csv, temp_settings):
    rows = [
        CORE_FIELDS,
        _row(order_id="ORD-1", amount="not-a-number"),
        _row(order_id="ORD-2", amount="-5.00"),
        _row(order_id="ORD-3", amount="5.001"),
        _row(order_id="ORD-4", amount="NaN"),
        _row(order_id="ORD-5", amount="Infinity"),
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    issues = _issues_of(result, "invalid_amount")
    assert len(issues) == 5
    assert [issue["row"] for issue in issues] == [2, 3, 4, 5, 6]
    assert result["invalid_rows"] == 5


def test_boolean_amount_is_rejected(make_xlsx, temp_settings):
    rows = [CORE_FIELDS, _row(amount=True)]
    path = make_xlsx(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert len(_issues_of(response["result"], "invalid_amount")) == 1


def test_zero_amount_is_allowed(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row(amount="0.00")]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert response["result"]["issues"] == []


def test_amount_with_thousands_separator_is_normalised(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row(amount="1,250.50")]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert response["result"]["issues"] == []


def test_bad_dates_are_reported(make_csv, temp_settings):
    rows = [
        CORE_FIELDS,
        _row(order_id="ORD-1", date="2026/09/18"),
        _row(order_id="ORD-2", date="2026-02-30"),
        _row(order_id="ORD-3", date="18-09-2026"),
        _row(order_id="ORD-4", date="not-a-date"),
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    issues = _issues_of(response["result"], "invalid_date")
    assert len(issues) == 4
    assert response["result"]["invalid_rows"] == 4


def test_excel_datetime_date_is_accepted(make_xlsx, temp_settings):
    rows = [CORE_FIELDS, _row(date=datetime(2026, 9, 18, 0, 0, 0))]
    path = make_xlsx(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    assert response["result"]["issues"] == []


def test_duplicate_business_key_is_reported(make_csv, temp_settings):
    rows = [
        CORE_FIELDS,
        _row(order_id="ORD-1001", amount="10.00"),
        _row(order_id="ORD-1001", amount="10.00"),
        _row(order_id="ORD-1002"),
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    issues = _issues_of(result, "duplicate_business_key")
    assert len(issues) == 2
    assert {issue["row"] for issue in issues} == {2, 3}
    assert result["duplicate_keys"] == [
        {
            "supplier_id": "SUP-001",
            "order_id": "ORD-1001",
            "rows": [2, 3],
        }
    ]
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 2


def test_row_with_multiple_issues_counts_once(make_csv, temp_settings):
    rows = [
        CORE_FIELDS,
        _row(),
        _row(order_id="", amount="bad", date="bad"),
    ]
    path = make_csv(rows)

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    assert result["total_rows"] == 2
    assert result["valid_rows"] == 1
    assert result["invalid_rows"] == 1
    assert len(result["issues"]) == 3


def test_reference_match_is_valid(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row()]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=_refs(),
        settings=temp_settings,
    )

    assert response["status"] == "success"
    result = response["result"]
    assert result["reference_compared"] is True
    assert result["reference_record_count"] == 2
    assert result["issues"] == []
    assert result["valid_rows"] == 1


def test_record_not_found_is_reported(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row(order_id="ORD-9999")]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=_refs(),
        settings=temp_settings,
    )

    assert response["status"] == "success"
    issues = _issues_of(response["result"], "record_not_found")
    assert len(issues) == 1
    assert issues[0]["row"] == 2
    assert issues[0]["field"] is None


def test_explicit_empty_reference_is_not_the_same_as_no_reference(
    make_csv, temp_settings
):
    rows = [CORE_FIELDS, _row()]
    path = make_csv(rows)

    without = validate_data(file_path=str(path), settings=temp_settings)
    with_empty = validate_data(
        file_path=str(path),
        reference_records=[],
        settings=temp_settings,
    )

    assert without["result"]["reference_compared"] is False
    assert without["result"]["issues"] == []
    assert with_empty["result"]["reference_compared"] is True
    assert with_empty["result"]["reference_record_count"] == 0
    assert len(_issues_of(with_empty["result"], "record_not_found")) == 1


def test_ambiguous_reference_is_reported(make_csv, temp_settings):
    refs = _refs() + [dict(_refs()[0], amount=5100.00)]
    rows = [CORE_FIELDS, _row()]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=refs,
        settings=temp_settings,
    )

    assert response["status"] == "success"
    issues = _issues_of(response["result"], "ambiguous_reference")
    assert len(issues) == 1
    assert issues[0]["row"] == 2


def test_amount_mismatch_reports_both_sides_and_difference(
    make_csv, temp_settings
):
    rows = [CORE_FIELDS, _row(amount="5200.00")]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=_refs(),
        settings=temp_settings,
    )

    assert response["status"] == "success"
    issues = _issues_of(response["result"], "amount_mismatch")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["row"] == 2
    assert issue["field"] == "amount"
    assert float(issue["excel_amount"]) == 5200.00
    assert float(issue["bi_amount"]) == 5000.00
    assert float(issue["difference"]) == 200.00


def test_status_mismatch_is_reported(make_csv, temp_settings):
    rows = [
        CORE_FIELDS,
        _row(order_id="ORD-1001", payment_status="paid"),
        _row(
            supplier_id="SUP-002",
            supplier_name="Bright Trading",
            order_id="ORD-2001",
            amount="8900.00",
            record_status="inactive",
        ),
    ]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=_refs(),
        settings=temp_settings,
    )

    assert response["status"] == "success"
    result = response["result"]
    payment_issues = _issues_of(result, "payment_status_mismatch")
    record_issues = _issues_of(result, "record_status_mismatch")
    assert len(payment_issues) == 1
    assert payment_issues[0]["field"] == "payment_status"
    assert len(record_issues) == 1
    assert record_issues[0]["field"] == "record_status"
    assert result["invalid_rows"] == 2


def test_missing_reference_key_is_reported(make_csv, temp_settings):
    refs = [{"supplier_name": "No Key Ltd", "amount": 1.0}]
    rows = [CORE_FIELDS, _row()]
    path = make_csv(rows)

    response = validate_data(
        file_path=str(path),
        reference_records=refs,
        settings=temp_settings,
    )

    assert response["status"] == "success"
    issues = _issues_of(response["result"], "invalid_reference_record")
    assert len(issues) == 1
    assert issues[0]["row"] is None


def test_empty_dataset_statistics(make_csv, temp_settings):
    path = make_csv([CORE_FIELDS])

    response = validate_data(file_path=str(path), settings=temp_settings)

    assert response["status"] == "success"
    result = response["result"]
    assert result["total_rows"] == 0
    assert result["valid_rows"] == 0
    assert result["invalid_rows"] == 0
    issues = _issues_of(result, "empty_dataset")
    assert len(issues) == 1


def test_validation_does_not_modify_source_file(make_csv, temp_settings):
    rows = [CORE_FIELDS, _row(amount="bad")]
    path = make_csv(rows)
    before = path.read_bytes()

    validate_data(file_path=str(path), settings=temp_settings)

    assert path.read_bytes() == before


def test_file_not_found_returns_technical_error(temp_settings):
    response = validate_data(
        file_path=str(temp_settings.upload_dir / "missing.csv"),
        settings=temp_settings,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "FILE_NOT_FOUND"


def test_reference_records_wrong_type_is_invalid_argument(
    make_csv, temp_settings
):
    path = make_csv([CORE_FIELDS, _row()])

    response = validate_data(
        file_path=str(path),
        reference_records="not-a-list",
        settings=temp_settings,
    )

    assert response["status"] == "error"
    assert response["error_code"] == "INVALID_ARGUMENTS"
