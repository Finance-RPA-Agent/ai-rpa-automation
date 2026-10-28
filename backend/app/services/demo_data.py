"""Single source of truth for the synthetic demo data and expected results.

Tests, the seed script, the demo file builder and the demo runs all read
from this module so the BI source data and the expected outcomes cannot
drift apart.  No company data is used here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEMO_BI_RECORDS = [
    {
        "supplier_id": "SUP-001",
        "supplier_name": "ABC Ltd",
        "order_id": "ORD-1001",
        "amount": "5000.00",
        "date": "2026-09-18",
        "payment_status": "pending",
        "record_status": "active",
    },
    {
        "supplier_id": "SUP-001",
        "supplier_name": "ABC Ltd",
        "order_id": "ORD-1002",
        "amount": "1250.50",
        "date": "2026-09-19",
        "payment_status": "paid",
        "record_status": "active",
    },
    {
        "supplier_id": "SUP-002",
        "supplier_name": "Bright Trading",
        "order_id": "ORD-2001",
        "amount": "8900.00",
        "date": "2026-09-20",
        "payment_status": "pending",
        "record_status": "active",
    },
    {
        "supplier_id": "SUP-003",
        "supplier_name": "Cedar Supplies",
        "order_id": "ORD-3001",
        "amount": "320.75",
        "date": "2026-09-21",
        "payment_status": "paid",
        "record_status": "active",
    },
    {
        "supplier_id": "SUP-004",
        "supplier_name": "Delta Works",
        "order_id": "ORD-4001",
        "amount": "777.00",
        "date": "2026-09-22",
        "payment_status": "overdue",
        "record_status": "active",
    },
    {
        "supplier_id": "SUP-005",
        "supplier_name": "Echo Ltd",
        "order_id": "ORD-5001",
        "amount": "1500.00",
        "date": "2026-09-23",
        "payment_status": "pending",
        "record_status": "inactive",
    },
]

HEADERS = [
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
]


@dataclass(frozen=True)
class DemoCase:
    name: str
    filename: str
    file_type: str
    rows: list = field(default_factory=list)
    compare_with_bi: bool = False
    expected_issue_types: list = field(default_factory=list)
    expected_total_rows: int = 0
    expected_valid_rows: int = 0
    expected_invalid_rows: int = 0
    notes: str = ""


NORMAL_CASE = DemoCase(
    name="normal",
    filename="normal_orders.xlsx",
    file_type="xlsx",
    rows=[
        HEADERS,
        ["SUP-001", "ABC Ltd", "ORD-1001", 5000.00, "2026-09-18", "pending", "active"],
        ["SUP-002", "Bright Trading", "ORD-2001", 8900.00, "2026-09-20", "pending", "active"],
        ["SUP-003", "Cedar Supplies", "ORD-3001", 320.75, "2026-09-21", "paid", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=[],
    expected_total_rows=3,
    expected_valid_rows=3,
    expected_invalid_rows=0,
    notes="Three orders that match the simulated BI records exactly.",
)

MISSING_VALUES_CASE = DemoCase(
    name="missing_values",
    filename="missing_values.csv",
    file_type="csv",
    rows=[
        HEADERS,
        ["SUP-003", "", "ORD-3001", "320.75", "2026-09-21", "paid", "active"],
        ["SUP-004", "Delta Works", "ORD-4001", "", "2026-09-22", "overdue", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=["missing_value", "missing_value"],
    expected_total_rows=2,
    expected_valid_rows=0,
    expected_invalid_rows=2,
    notes="One empty supplier_name and one empty amount.",
)

INVALID_FORMATS_CASE = DemoCase(
    name="invalid_formats",
    filename="invalid_formats.xlsx",
    file_type="xlsx",
    rows=[
        HEADERS,
        ["SUP-004", "Delta Works", "ORD-4001", "not-a-number", "2026-09-22", "overdue", "active"],
        ["SUP-002", "Bright Trading", "ORD-2001", 8900.00, "2026/09/20", "pending", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=["invalid_amount", "invalid_date"],
    expected_total_rows=2,
    expected_valid_rows=0,
    expected_invalid_rows=2,
    notes="One unparseable amount and one non-ISO date.",
)

AMOUNT_CONFLICT_CASE = DemoCase(
    name="amount_conflict",
    filename="amount_conflict.csv",
    file_type="csv",
    rows=[
        HEADERS,
        ["SUP-001", "ABC Ltd", "ORD-1001", "5200.00", "2026-09-18", "pending", "active"],
        ["SUP-002", "Bright Trading", "ORD-2001", "8900.00", "2026-09-20", "paid", "active"],
        ["SUP-003", "Cedar Supplies", "ORD-3001", "320.75", "2026-09-21", "paid", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=[
        "amount_mismatch",
        "payment_status_mismatch",
    ],
    expected_total_rows=3,
    expected_valid_rows=1,
    expected_invalid_rows=2,
    notes=(
        "Excel 5200.00 vs BI 5000.00 (difference +200.00) and one "
        "payment status conflict."
    ),
)

DUPLICATE_KEYS_CASE = DemoCase(
    name="duplicate_keys",
    filename="duplicate_keys.xlsx",
    file_type="xlsx",
    rows=[
        HEADERS,
        ["SUP-004", "Delta Works", "ORD-4001", 777.00, "2026-09-22", "overdue", "active"],
        ["SUP-004", "Delta Works", "ORD-4001", 777.00, "2026-09-22", "overdue", "active"],
        ["SUP-003", "Cedar Supplies", "ORD-3001", 320.75, "2026-09-21", "paid", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=[
        "duplicate_business_key",
        "duplicate_business_key",
    ],
    expected_total_rows=3,
    expected_valid_rows=1,
    expected_invalid_rows=2,
    notes="The same supplier_id + order_id appears twice.",
)

NO_MATCH_CASE = DemoCase(
    name="no_match",
    filename="no_match.csv",
    file_type="csv",
    rows=[
        HEADERS,
        ["SUP-099", "Unknown Supplier", "ORD-9999", "10.00", "2026-09-18", "pending", "active"],
        ["SUP-005", "Echo Ltd", "ORD-5001", "1500.00", "2026-09-23", "pending", "active"],
    ],
    compare_with_bi=True,
    expected_issue_types=[
        "record_not_found",
        "record_status_mismatch",
    ],
    expected_total_rows=2,
    expected_valid_rows=0,
    expected_invalid_rows=2,
    notes="One order missing from BI and one record_status conflict.",
)

LEADING_ZERO_CASE = DemoCase(
    name="leading_zero",
    filename="leading_zero.csv",
    file_type="csv",
    rows=[
        HEADERS,
        ["00123", "Zero Ltd", "ORD-0007", "12.50", "2026-09-18", "pending", "active"],
    ],
    compare_with_bi=False,
    expected_issue_types=[],
    expected_total_rows=1,
    expected_valid_rows=1,
    expected_invalid_rows=0,
    notes="Text identifiers with leading zeros must survive the read.",
)

DEMO_CASES = [
    NORMAL_CASE,
    MISSING_VALUES_CASE,
    INVALID_FORMATS_CASE,
    AMOUNT_CONFLICT_CASE,
    DUPLICATE_KEYS_CASE,
    NO_MATCH_CASE,
    LEADING_ZERO_CASE,
]

DEMO_CASES_BY_NAME = {case.name: case for case in DEMO_CASES}


def reference_records() -> list[dict]:
    """Return a fresh copy of the simulated BI records."""

    return [dict(record) for record in DEMO_BI_RECORDS]
