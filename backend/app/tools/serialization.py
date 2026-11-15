"""JSON-safe conversion for tool results.

FastAPI's default encoder cannot serialise Decimal, dates, NumPy scalars
or NaN.  Tool results run through :func:`to_jsonable` so Python callers and
HTTP callers always see valid JSON-compatible values.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time
from decimal import Decimal

import pandas as pd


def to_jsonable(value):
    if value is None or isinstance(value, (str, bool)):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        # Keep ordinary whole amounts compatible without creating binary floats.
        # Larger integers must be text too: browser JSON numbers lose precision
        # beyond the exact safe-integer range. Fractions retain every decimal.
        if value == value.to_integral_value() and value.copy_abs() <= 9007199254740991:
            return int(value)
        return format(value, "f")

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return to_jsonable(item())
        except (TypeError, ValueError):
            pass

    return str(value)
