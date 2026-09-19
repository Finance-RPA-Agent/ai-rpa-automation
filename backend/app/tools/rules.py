"""Central business rules for the supplier finance reconciliation demo.

The values here are the team's *demo assumptions* for the first runnable
version.  They are not confirmed company policy.  Keep every rule in this
module so group members can adjust them in one place.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

CORE_FIELDS = (
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
)

REQUIRED_FIELDS = CORE_FIELDS
BUSINESS_KEY = ("supplier_id", "order_id")

DATE_FORMAT = "YYYY-MM-DD"
AMOUNT_SCALE = 2
CURRENCY_MODE = "single_currency_two_decimals"
ALLOW_NEGATIVE_AMOUNT = False

RECORD_TYPES = (
    "reconciliation_result",
    "reconciliation_exception",
)

PAYMENT_STATUSES = ("pending", "paid", "overdue")
RECORD_STATUSES = ("active", "inactive", "matched")
EXCEPTION_ISSUE_TYPES = (
    "amount_mismatch",
    "payment_status_mismatch",
    "record_status_mismatch",
    "record_not_found",
    "invalid_amount",
    "invalid_date",
    "missing_value",
    "duplicate_business_key",
)

DEMO_ASSUMPTIONS = (
    "All seven core fields are required for the demo.",
    "supplier_id + order_id is the business key.",
    "Amounts use one currency with two decimals; no FX conversion.",
    "Dates use YYYY-MM-DD.",
    "Negative amounts are treated as invalid in the demo rule set.",
    "These rules are team demo assumptions, not confirmed company policy.",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Plain digits or correctly grouped thousands (1-3 digits, then groups of
# exactly three), with at most two decimal places.  Commas are only valid
# as thousands separators; malformed text is rejected, never repaired.
_AMOUNT_TEXT_RE = re.compile(
    r"^-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,2})?$"
)


class AmountError(ValueError):
    pass


class DateRuleError(ValueError):
    pass


def parse_amount(value) -> Decimal:
    """Parse an amount into an exact Decimal.

    Rejects booleans, non-finite numbers, values with more than two
    decimals (no silent rounding) and, per the demo rule, negatives.
    """

    if value is None:
        raise AmountError("amount is missing")

    if isinstance(value, bool):
        raise AmountError("boolean values are not valid amounts")

    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise AmountError("amount must be a finite number")
        parsed = Decimal(repr(value))
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise AmountError("amount is empty")
        if not _AMOUNT_TEXT_RE.match(text):
            raise AmountError(
                f"'{value}' is not a valid amount format (use digits "
                "with optional correctly grouped thousands and at most "
                "two decimals)"
            )
        parsed = Decimal(text.replace(",", ""))
    else:
        raise AmountError(
            f"unsupported amount type: {type(value).__name__}"
        )

    if not parsed.is_finite():
        raise AmountError("amount must be a finite number")

    if parsed.as_tuple().exponent < -AMOUNT_SCALE:
        raise AmountError(
            f"amount must have at most {AMOUNT_SCALE} decimal places"
        )

    if parsed < 0 and not ALLOW_NEGATIVE_AMOUNT:
        raise AmountError("negative amounts are not allowed in the demo")

    return parsed


def format_amount(value: Decimal) -> str:
    return f"{value.quantize(Decimal(1).scaleb(-AMOUNT_SCALE)):f}"


def parse_date(value) -> date:
    """Parse a date into a datetime.date following the YYYY-MM-DD rule."""

    if value is None:
        raise DateRuleError("date is missing")

    if isinstance(value, bool):
        raise DateRuleError("boolean values are not valid dates")

    if isinstance(value, datetime):
        if value.time() != time(0, 0):
            raise DateRuleError(
                "date values must not contain a non-midnight time"
            )
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        text = value.strip()
        if not _DATE_RE.match(text):
            raise DateRuleError(
                f"'{value}' does not match the YYYY-MM-DD rule"
            )
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise DateRuleError(f"'{value}' is not a real date") from exc

    raise DateRuleError(f"unsupported date type: {type(value).__name__}")


def normalise_status(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value)


def normalise_identifier(value) -> str | None:
    """Keep identifiers as text; never turn '00123' into 123."""

    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text or None
