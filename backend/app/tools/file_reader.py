"""read_data_file: load .xlsx / .csv data into a structured, row-aware form.

Security notes:
- only files inside the configured upload / demo data directories are read;
- ``..``, absolute paths outside those roots and symlink escapes are rejected;
- identifiers (for example ``00123`` or the text ``NA``) are kept as text,
  never coerced to int or mistaken for a missing-value placeholder.

Row semantics:
- the first record is the header; data rows keep their physical source row
  number (first data row is row 2);
- for CSV, blank physical lines are skipped but still counted, so later
  rows keep the same line number the user sees in a text editor;
- a record that contains quoted line breaks occupies several physical
  lines; row numbers point at the line where the record starts.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime, time
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from backend.app.config import Settings, get_settings
from backend.app.tools.errors import ErrorCode, ToolError, success
from backend.app.tools.serialization import to_jsonable

HEADER_ROW = 1
FIRST_DATA_ROW = 2


class TableData(NamedTuple):
    resolved_path: Path
    file_type: str
    sheet_name: str | None
    columns: list[str]
    records: list[dict]
    column_issues: list[dict]

    @property
    def row_count(self) -> int:
        return len(self.records)


class RawTable(NamedTuple):
    raw_headers: list
    data_rows: list[tuple[int, list]]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_input_path(file_path, settings: Settings) -> Path:
    """Resolve a caller-supplied path inside the allowed roots only."""

    if file_path is None or not isinstance(file_path, str):
        raise ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            "file_path is required and must be a string.",
        )

    text = file_path.strip()
    if not text:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENTS,
            "file_path must not be empty.",
        )

    roots = tuple(root.resolve() for root in settings.allowed_file_roots())
    candidate = Path(text)
    escaped = False

    resolved_candidates: list[Path] = []
    if candidate.is_absolute():
        resolved_candidates.append(candidate)
    else:
        for root in roots:
            resolved_candidates.append(root / candidate)
        resolved_candidates.append(settings.base_dir.resolve() / candidate)

    for resolved in resolved_candidates:
        resolved = resolved.resolve()
        if not any(_is_within(resolved, root) for root in roots):
            escaped = True
            continue
        if resolved.is_file():
            return resolved

    if escaped:
        raise ToolError(
            ErrorCode.PATH_NOT_ALLOWED,
            "The file path is outside the allowed upload and demo data "
            "directories.",
        )

    raise ToolError(
        ErrorCode.FILE_NOT_FOUND,
        "The specified file does not exist.",
    )


def _is_blank_header(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    if isinstance(value, str):
        return not value.strip()
    return False


def _build_columns(raw_headers) -> tuple[list[str], list[dict]]:
    """Assign collision-free unique column names, preserving raw headers.

    Empty / whitespace-only headers get a generated ``column_N`` name.
    Any name that collides with an already assigned name is renamed with a
    numeric suffix, so no cell can silently overwrite another cell.
    """

    columns: list[str] = []
    issues: list[dict] = []
    used: set[str] = set()

    for index, raw in enumerate(raw_headers):
        blank = _is_blank_header(raw)
        base = f"column_{index + 1}" if blank else str(raw).strip()
        name = base
        renamed = False

        if name in used:
            suffix = 2
            while f"{name}__{suffix}" in used:
                suffix += 1
            name = f"{base}__{suffix}"
            renamed = True

        used.add(name)
        columns.append(name)

        if blank:
            issues.append(
                {
                    "column": name,
                    "type": "empty_header",
                    "message": (
                        f"Header cell {index + 1} is empty or whitespace "
                        f"only; generated column name '{name}' was used."
                    ),
                }
            )
        elif renamed:
            issues.append(
                {
                    "column": base,
                    "type": "duplicate_header",
                    "message": (
                        f"Header '{base}' collides with an existing "
                        f"column name; this column was renamed to '{name}'."
                    ),
                }
            )

    return columns, issues


def _cell_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass

    if isinstance(value, datetime):
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")

    if isinstance(value, str) and value == "":
        return None

    return value


def _rows_to_table(
    raw: RawTable,
    resolved_path: Path,
    file_type: str,
    sheet_name: str | None,
) -> TableData:
    columns, column_issues = _build_columns(raw.raw_headers)

    records: list[dict] = []
    for row_number, values in raw.data_rows:
        data = {
            column: _cell_value(
                values[position] if position < len(values) else None
            )
            for position, column in enumerate(columns)
        }
        records.append({"row": row_number, "data": data})

    return TableData(
        resolved_path=resolved_path,
        file_type=file_type,
        sheet_name=sheet_name,
        columns=columns,
        records=records,
        column_issues=column_issues,
    )


def load_xlsx(path: Path, sheet_name: str | None) -> TableData:
    try:
        excel = pd.ExcelFile(path)
    except Exception as exc:  # noqa: BLE001 - map any reader error
        raise ToolError(
            ErrorCode.FILE_READ_ERROR,
            f"Unable to read the Excel file: {exc}",
        ) from exc

    try:
        if sheet_name is None:
            sheet = excel.sheet_names[0]
        elif sheet_name in excel.sheet_names:
            sheet = sheet_name
        else:
            raise ToolError(
                ErrorCode.SHEET_NOT_FOUND,
                f"Worksheet '{sheet_name}' was not found. Available "
                f"worksheets: {', '.join(excel.sheet_names)}.",
            )

        try:
            frame = excel.parse(
                sheet,
                header=None,
                dtype=object,
                keep_default_na=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolError(
                ErrorCode.FILE_READ_ERROR,
                f"Unable to read worksheet '{sheet}': {exc}",
            ) from exc
    finally:
        excel.close()

    if frame.shape[0] == 0:
        raise ToolError(
            ErrorCode.EMPTY_FILE,
            "The worksheet does not contain any rows, including the "
            "header row.",
        )

    raw_headers = list(frame.iloc[0])
    data_rows = []
    for offset in range(1, frame.shape[0]):
        values = list(frame.iloc[offset])
        data_rows.append((offset + HEADER_ROW, values))

    return _rows_to_table(
        RawTable(raw_headers=raw_headers, data_rows=data_rows),
        path,
        "xlsx",
        sheet,
    )


def load_csv(path: Path) -> TableData:
    reader = None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            rows: list[tuple[int, list]] = []
            last_line = 0
            for values in reader:
                start_line = last_line + 1
                last_line = reader.line_num
                rows.append((start_line, values))
    except UnicodeDecodeError as exc:
        raise ToolError(
            ErrorCode.UNSUPPORTED_ENCODING,
            "The CSV file is not valid UTF-8 or UTF-8 BOM text.",
        ) from exc
    except csv.Error as exc:
        line = getattr(reader, "line_num", 0) or 1
        raise ToolError(
            ErrorCode.CSV_PARSE_ERROR,
            (
                "Malformed CSV syntax near line "
                f"{line}: {exc}. The file was not read; missing or "
                "mismatched quotes are never guessed."
            ),
        ) from exc
    except OSError as exc:
        raise ToolError(
            ErrorCode.FILE_READ_ERROR,
            f"Unable to read the CSV file: {exc}",
        ) from exc

    if not any(values for _, values in rows):
        raise ToolError(
            ErrorCode.EMPTY_FILE,
            "The CSV file does not contain any non-blank rows, including "
            "the header row.",
        )

    raw_headers = rows[0][1]
    header_width = len(raw_headers)

    for line, values in rows[1:]:
        if not values:
            continue
        if len(values) > header_width:
            raise ToolError(
                ErrorCode.INVALID_CSV_STRUCTURE,
                (
                    f"CSV row {line} has {len(values)} values but the "
                    f"header defines {header_width} columns; the file was "
                    "rejected instead of truncating or guessing data."
                ),
            )

    data_rows = [
        (line, values) for line, values in rows[1:] if values
    ]

    return _rows_to_table(
        RawTable(raw_headers=raw_headers, data_rows=data_rows),
        path,
        "csv",
        None,
    )


def load_table(file_path, settings: Settings, sheet_name=None) -> TableData:
    resolved = resolve_input_path(file_path, settings)

    if resolved.stat().st_size == 0:
        raise ToolError(
            ErrorCode.EMPTY_FILE,
            "The specified file is empty.",
        )

    suffix = resolved.suffix.lower()
    if suffix == ".xlsx":
        if sheet_name is not None and not isinstance(sheet_name, str):
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "sheet_name must be a string when provided.",
            )
        return load_xlsx(resolved, sheet_name)
    if suffix == ".csv":
        if sheet_name is not None:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENTS,
                "sheet_name is only supported for .xlsx files.",
            )
        return load_csv(resolved)

    raise ToolError(
        ErrorCode.UNSUPPORTED_FILE_TYPE,
        "Only .xlsx and UTF-8 .csv files are supported by this tool.",
    )


def read_data_file(file_path=None, sheet_name=None, *, settings=None) -> dict:
    settings = settings or get_settings()

    try:
        table = load_table(file_path, settings, sheet_name=sheet_name)
    except ToolError as exc:
        return exc.as_envelope()

    result = {
        "file_path": str(table.resolved_path),
        "file_type": table.file_type,
        "sheet_name": table.sheet_name,
        "header_row": HEADER_ROW,
        "first_data_row": FIRST_DATA_ROW,
        "row_count": table.row_count,
        "columns": table.columns,
        "column_issues": table.column_issues,
        "records": table.records,
    }

    return success(to_jsonable(result))
