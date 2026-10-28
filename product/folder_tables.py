"""Bounded folder-table recognition. Ambiguous fields and roles stay explicit."""
import csv
from datetime import date, datetime, time
import io
from pathlib import Path
import re
import zipfile

import pandas as pd
from openpyxl import load_workbook

from product.service import FIELDS, MAX_BYTES, MAX_ROWS

MAX_FILES = 100
MAX_TABLES = 200
MAX_BATCH_ROWS = 50000
MAX_BATCH_BYTES = 100 * 1024 * 1024
ALIASES = {
    "supplier_id": ["supplier id", "vendor id", "supplier code", "vendor code", "counterparty id"],
    "supplier_name": ["supplier name", "vendor name", "counterparty name", "company name"],
    "order_id": ["order id", "order number", "order no", "po number", "po no", "purchase order", "invoice number", "invoice no", "invoice id"],
    "amount": ["amount", "total amount", "order amount", "invoice amount", "gross amount", "total"],
    "date": ["date", "order date", "invoice date", "transaction date"],
    "payment_status": ["payment status", "payment state", "paid status"],
    "record_status": ["record status", "record state", "order status"],
}


def token(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def automatic_mapping(columns):
    mapping = {}
    for field, aliases in ALIASES.items():
        accepted = {token(field), *(token(alias) for alias in aliases)}
        matches = [column for column in columns if token(column) in accepted]
        if len(matches) == 1:
            mapping[field] = matches[0]
    return mapping


def infer_role(relative, sheet):
    def role(value):
        words = set(re.findall(r"[a-z0-9]+", value.lower()))
        reference = bool(words & {"reference", "references", "bi", "ledger", "master"})
        source = bool(words & {"source", "sources", "order", "orders", "transactions"})
        return "unknown" if source == reference else "reference" if reference else "source"
    # A named worksheet is more specific than its container workbook.
    if sheet and role(sheet) != "unknown":
        return role(sheet)
    return role(str(relative))


def clean_cell(value):
    if value is None or (not isinstance(value, (str, list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def prepare_table(rows):
    rows = [[clean_cell(cell) for cell in row] for row in rows]
    nonempty = [i for i, row in enumerate(rows) if any(str(cell).strip() for cell in row)]
    if not nonempty:
        raise ValueError("The table is empty.")
    candidates = nonempty[:20]
    header = max(candidates, key=lambda i: len(automatic_mapping([str(v).strip() for v in rows[i]])))
    columns = [str(value).strip() for value in rows[header]]
    while columns and not columns[-1]:
        columns.pop()
    if not columns or any(not column for column in columns) or len(set(columns)) != len(columns):
        raise ValueError("Headers are empty or duplicated. Correct the file and scan again.")
    if len(columns) > 200:
        raise ValueError("A table may contain at most 200 columns.")
    records, origins = [], []
    for index, row in enumerate(rows[header + 1:], header + 2):
        if not any(str(cell).strip() for cell in row):
            continue
        if any(str(cell).strip() for cell in row[len(columns):]):
            raise ValueError(f"Source row {index} contains values beyond its headers.")
        records.append(dict(zip(columns, row + [""] * max(0, len(columns) - len(row)))))
        origins.append(index)
        if len(records) > MAX_ROWS:
            raise ValueError(f"A table may contain at most {MAX_ROWS:,} records.")
    if not records:
        raise ValueError("No records were found below the header.")
    currency_columns = [column for column in columns if token(column) in {"currency", "currencycode", "ccy"}]
    currencies = sorted({r[c].strip().upper() for c in currency_columns for r in records if r[c].strip()})
    return {"columns": columns, "rows": records, "origin_rows": origins,
            "mapping": automatic_mapping(columns), "currencies": currencies}


def read_tables(path):
    """Yield every worksheet separately, including a visible failure for bad sheets."""
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        yield "", None, "The file exceeds 10 MB."
        return
    if path.suffix.lower() == ".csv":
        try:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = []
                for row in csv.reader(handle, strict=True):
                    if len(row) > 200:
                        raise ValueError("The CSV contains more than 200 columns.")
                    rows.append(row)
                    if len(rows) > MAX_ROWS + 21:
                        raise ValueError("The CSV exceeds the record/header-row limit.")
            # pandas performs CSV parsing after locating the actual header.
            table = prepare_table(rows)
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=table["columns"])
            writer.writeheader()
            writer.writerows(table["rows"])
            frame = pd.read_csv(io.StringIO(buffer.getvalue()), dtype=str, keep_default_na=False)
            table["rows"] = frame.to_dict("records")
            yield "CSV", table, None
        except Exception as exc:
            yield "CSV", None, f"CSV could not be read: {exc}"
        return
    try:
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > 100 * 1024 * 1024:
                raise ValueError("The decompressed workbook exceeds 100 MB.")
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            sheets = [(sheet.title, sheet.max_row, sheet.max_column) for sheet in workbook.worksheets]
        finally:
            workbook.close()
        if not sheets or len(sheets) > 20:
            raise ValueError("Choose a workbook with 1 to 20 worksheets.")
        for name, row_count, column_count in sheets:
            try:
                if (row_count and row_count > MAX_ROWS + 21) or (column_count and column_count > 200):
                    raise ValueError("The worksheet exceeds 5,000 records plus 20 header rows, or 200 columns.")
                frame = pd.read_excel(path, sheet_name=name, header=None, dtype=object,
                                      keep_default_na=False, nrows=MAX_ROWS + 21, engine="openpyxl")
                yield name, prepare_table(frame.values.tolist()), None
            except Exception as exc:
                yield name, None, f"Worksheet could not be read: {exc}"
    except Exception as exc:
        yield "", None, f"Workbook could not be read: {exc}"


def canonical_bytes(table, mapping=None, indexes=None):
    mapping = table["mapping"] if mapping is None else mapping
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    selected = table["rows"] if indexes is None else [table["rows"][i] for i in indexes]
    writer.writerows({field: row.get(mapping.get(field), "") for field in FIELDS} for row in selected)
    return output.getvalue().encode("utf-8-sig")


def choose_folder():
    """Native desktop folder selection; browser mode falls back to tkinter."""
    import webview
    if webview.windows:
        chosen = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        return str(chosen[0]) if chosen else None
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(parent=root, title="Choose reconciliation folder", mustexist=True)
        return chosen or None
    finally:
        root.destroy()
