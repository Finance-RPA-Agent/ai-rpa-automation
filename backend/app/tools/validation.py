"""validate_data: file-internal checks plus optional Excel-vs-BI comparison.

Business findings (missing cells, bad formats, mismatches) are *not* tool
failures: they are returned as ``status=success`` with an ``issues`` list.
Technical problems (missing file, unreadable workbook) return the error
envelope instead.
"""

from __future__ import annotations

from backend.app.config import get_settings
from backend.app.tools.errors import ErrorCode, ToolError, success
from backend.app.tools.file_reader import load_table
from backend.app.tools.rules import (
    AMOUNT_SCALE,
    ALLOW_NEGATIVE_AMOUNT,
    AmountError,
    BUSINESS_KEY,
    CURRENCY_MODE,
    DATE_FORMAT,
    DateRuleError,
    REQUIRED_FIELDS,
    normalise_identifier,
    normalise_status,
    parse_amount,
    parse_date,
)
from backend.app.tools.serialization import to_jsonable


def _issue(row, field, issue_type, message, **extra) -> dict:
    issue = {
        "row": row,
        "field": field,
        "type": issue_type,
        "message": message,
    }
    issue.update(extra)
    return issue


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _reference_rule_set() -> dict:
    return {
        "required_fields": list(REQUIRED_FIELDS),
        "business_key": list(BUSINESS_KEY),
        "amount_scale": AMOUNT_SCALE,
        "currency_mode": CURRENCY_MODE,
        "allow_negative_amount": ALLOW_NEGATIVE_AMOUNT,
        "date_format": DATE_FORMAT,
    }


def validate_data(
    file_path=None,
    reference_records=None,
    *,
    sheet_name=None,
    settings=None,
) -> dict:
    settings = settings or get_settings()

    if reference_records is not None and not isinstance(
        reference_records, (list, tuple)
    ):
        return ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            "reference_records must be a list of objects when provided.",
        ).as_envelope()

    try:
        table = load_table(file_path, settings, sheet_name=sheet_name)
    except ToolError as exc:
        return exc.as_envelope()

    missing_columns = [
        field for field in REQUIRED_FIELDS if field not in table.columns
    ]

    file_issues: list[dict] = []

    for column_issue in table.column_issues:
        file_issues.append(
            _issue(
                None,
                column_issue.get("column"),
                column_issue.get("type", "header_issue"),
                column_issue.get(
                    "message", "Ambiguous column header."
                ),
            )
        )

    for field in missing_columns:
        file_issues.append(
            _issue(
                None,
                field,
                "missing_column",
                f"Required column '{field}' is missing from the file.",
            )
        )
    if table.row_count == 0:
        file_issues.append(
            _issue(
                None,
                None,
                "empty_dataset",
                "The file has a header but no data rows.",
            )
        )

    row_issues: dict[int, list[dict]] = {}
    parsed: dict[int, dict] = {}

    for record in table.records:
        row_number = record["row"]
        data = record["data"]
        issues: list[dict] = []
        amount = None
        parsed_date = None

        for field in REQUIRED_FIELDS:
            if field in missing_columns:
                continue
            raw = data.get(field)
            if _is_blank(raw):
                issues.append(
                    _issue(
                        row_number,
                        field,
                        "missing_value",
                        f"{field} is missing.",
                    )
                )
                continue
            if field == "amount":
                try:
                    amount = parse_amount(raw)
                except AmountError as exc:
                    issues.append(
                        _issue(
                            row_number,
                            field,
                            "invalid_amount",
                            f"Invalid amount '{raw}': {exc}.",
                            value=to_jsonable(raw),
                        )
                    )
            elif field == "date":
                try:
                    parsed_date = parse_date(raw)
                except DateRuleError as exc:
                    issues.append(
                        _issue(
                            row_number,
                            field,
                            "invalid_date",
                            f"Invalid date '{raw}': {exc}.",
                            value=to_jsonable(raw),
                        )
                    )

        key = None
        if not any(
            field in missing_columns
            for field in BUSINESS_KEY
        ):
            supplier_id = normalise_identifier(data.get("supplier_id"))
            order_id = normalise_identifier(data.get("order_id"))
            if supplier_id and order_id:
                key = (supplier_id, order_id)

        parsed[row_number] = {
            "data": data,
            "key": key,
            "amount": amount,
            "date": parsed_date,
        }
        row_issues[row_number] = issues

    key_rows: dict[tuple, list[int]] = {}
    for row_number, row in parsed.items():
        if row["key"]:
            key_rows.setdefault(row["key"], []).append(row_number)

    duplicate_keys = []
    for key, rows in key_rows.items():
        if len(rows) > 1:
            duplicate_keys.append(
                {
                    "supplier_id": key[0],
                    "order_id": key[1],
                    "rows": rows,
                }
            )
            for row_number in rows:
                row_issues[row_number].append(
                    _issue(
                        row_number,
                        None,
                        "duplicate_business_key",
                        (
                            "Business key "
                            f"({key[0]}, {key[1]}) appears in rows "
                            f"{rows}; each order may only appear once."
                        ),
                    )
                )

    reference_compared = reference_records is not None
    reference_by_key: dict[tuple, list[dict]] = {}

    if reference_compared:
        for index, reference in enumerate(reference_records):
            if not isinstance(reference, dict):
                file_issues.append(
                    _issue(
                        None,
                        None,
                        "invalid_reference_record",
                        (
                            f"Reference record #{index} is not an object "
                            "and was ignored."
                        ),
                    )
                )
                continue
            supplier_id = normalise_identifier(reference.get("supplier_id"))
            order_id = normalise_identifier(reference.get("order_id"))
            if not supplier_id or not order_id:
                file_issues.append(
                    _issue(
                        None,
                        None,
                        "invalid_reference_record",
                        (
                            f"Reference record #{index} is missing "
                            "supplier_id and/or order_id and was ignored."
                        ),
                    )
                )
                continue
            reference_by_key.setdefault(
                (supplier_id, order_id), []
            ).append(reference)

        for row_number, row in parsed.items():
            if not row["key"]:
                continue
            matches = reference_by_key.get(row["key"], [])
            if not matches:
                row_issues[row_number].append(
                    _issue(
                        row_number,
                        None,
                        "record_not_found",
                        (
                            "No BI reference record matches "
                            f"supplier_id={row['key'][0]}, "
                            f"order_id={row['key'][1]}."
                        ),
                    )
                )
                continue
            if len(matches) > 1:
                row_issues[row_number].append(
                    _issue(
                        row_number,
                        None,
                        "ambiguous_reference",
                        (
                            f"{len(matches)} BI reference records match "
                            f"supplier_id={row['key'][0]}, "
                            f"order_id={row['key'][1]}; cannot choose one."
                        ),
                    )
                )
                continue

            reference = matches[0]

            bi_amount = None
            if "amount" not in missing_columns:
                try:
                    bi_amount = parse_amount(reference.get("amount"))
                except AmountError as exc:
                    row_issues[row_number].append(
                        _issue(
                            row_number,
                            "amount",
                            "invalid_reference_amount",
                            (
                                "The matching BI record has an unusable "
                                f"amount: {exc}."
                            ),
                        )
                    )

            if (
                row["amount"] is not None
                and bi_amount is not None
                and row["amount"] != bi_amount
            ):
                difference = row["amount"] - bi_amount
                row_issues[row_number].append(
                    _issue(
                        row_number,
                        "amount",
                        "amount_mismatch",
                        (
                            "Excel amount does not match the BI record; "
                            "manual verification is required."
                        ),
                        excel_amount=to_jsonable(row["amount"]),
                        bi_amount=to_jsonable(bi_amount),
                        difference=to_jsonable(difference),
                    )
                )

            for field in ("payment_status", "record_status"):
                if field in missing_columns:
                    continue
                excel_value = normalise_status(
                    row["data"].get(field)
                )
                if not excel_value:
                    continue

                raw_bi_value = reference.get(field)
                if raw_bi_value is None or (
                    isinstance(raw_bi_value, str)
                    and not raw_bi_value.strip()
                ):
                    row_issues[row_number].append(
                        _issue(
                            row_number,
                            field,
                            "missing_reference_status",
                            (
                                f"The matching BI record has no usable "
                                f"{field}; consistency cannot be "
                                "confirmed."
                            ),
                        )
                    )
                    continue
                if not isinstance(raw_bi_value, str):
                    row_issues[row_number].append(
                        _issue(
                            row_number,
                            field,
                            "invalid_reference_status",
                            (
                                f"The matching BI record {field} has an "
                                f"unsupported type "
                                f"({type(raw_bi_value).__name__})."
                            ),
                        )
                    )
                    continue

                bi_value = raw_bi_value.strip()
                if excel_value != bi_value:
                    row_issues[row_number].append(
                        _issue(
                            row_number,
                            field,
                            f"{field}_mismatch",
                            (
                                f"Excel {field}='{excel_value}' does not "
                                f"match the BI record value '{bi_value}'."
                            ),
                            excel_value=excel_value,
                            bi_value=bi_value,
                        )
                    )

    invalid_row_numbers = {
        row_number
        for row_number, issues in row_issues.items()
        if issues
    }

    ordered_issues = list(file_issues)
    for row_number in sorted(row_issues):
        ordered_issues.extend(row_issues[row_number])

    result = {
        "file_path": str(table.resolved_path),
        "file_type": table.file_type,
        "sheet_name": table.sheet_name,
        "total_rows": table.row_count,
        "valid_rows": table.row_count - len(invalid_row_numbers),
        "invalid_rows": len(invalid_row_numbers),
        "issues_count": len(ordered_issues),
        "issues": ordered_issues,
        "missing_columns": missing_columns,
        "duplicate_keys": duplicate_keys,
        "reference_compared": reference_compared,
        "reference_record_count": (
            len(reference_records) if reference_compared else None
        ),
        "rule_set": _reference_rule_set(),
    }

    return success(to_jsonable(result))
