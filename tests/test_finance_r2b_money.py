"""R2B exact money regressions through real tools, HTTP, SQLite and reports."""
import csv
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from fastapi.testclient import TestClient
import numpy as np
from openpyxl import Workbook, load_workbook
import pytest

from backend.app.models import FinancialRecord, OaReconciliationRecord, Task
from backend.app.tools import query_bi, read_data_file, submit_to_oa, validate_data
from backend.app.tools.oa_submitter import read_oa_record
from backend.app.tools.serialization import to_jsonable
import backend.app.tools.serialization as serialization_module
import product.excel_report as excel_report
import product.service as service_module
from product.api import create_app
from product.service import FIELDS


AMOUNTS = ["9007199254740991.01", "9007199254740992.99", "9007199254740993.01",
           "9007199254740993.00", "100.50", "9999999999999.99", "10000000000000.01", "0.01", "0.99",
           "9999999999999.12", "9999999999999.13", "8796093022208.12", "8796093022208.13",
           "8796093022209.12", "8796093022209.13"]
EXCEL_BOUNDARIES = ["9999999999999.12", "9999999999999.13", "8796093022208.12",
                    "8796093022208.13", "8796093022209.12", "8796093022209.13"]
EXCEL_CONTROLS = ["0.00", "0.01", "0.99", "100.12", "100.13", "9007199254740993.01"]
DELTAS = [("9007199254740993.02", "9007199254740993.01", "0.01"),
          ("9007199254740993.00", "9007199254740993.01", "-0.01"),
          ("9007199254740994.00", "9007199254740993.01", "0.99"),
          ("9007199254740992.02", "9007199254740993.01", "-0.99")]


def dump(folder, name, data):
    (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


@pytest.fixture(autouse=True)
def evidence(tmp_path, request):
    expected = os.getenv("R2B_EXPECT_SOURCE")
    root = Path(service_module.__file__).resolve().parents[1]
    if expected:
        assert root == Path(expected).resolve()
        assert Path(serialization_module.__file__).resolve().is_relative_to(root)
        assert Path(__file__).resolve().is_relative_to(root)
    folder = Path(os.getenv("R2B_ARTIFACTS", str(tmp_path / "evidence"))) / hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:12]
    folder.mkdir(parents=True)
    dump(folder, "identity.json", {"test": request.node.nodeid, "source_root": str(root),
                                  "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                  "serializer_sha256": hashlib.sha256(Path(serialization_module.__file__).read_bytes()).hexdigest()})
    yield folder
    dump(folder, "file_manifest.json", [{"path": p.relative_to(folder).as_posix(), "bytes": p.stat().st_size,
                                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                        for p in sorted(folder.rglob("*")) if p.is_file()])


def row(amount, index=1):
    return [f"{index:03d}", "Synthetic money supplier", f"{index:04d}", amount, "2026-10-01", "pending", "active"]


def write_source(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(FIELDS)
            writer.writerows(rows)
    else:
        book = Workbook()
        book.active.title = "Orders" if "source" in path.parts else "BI"
        book.active.append(FIELDS)
        for item in rows:
            book.active.append(item)
            assert book.active.cell(book.active.max_row, 4).data_type == "s"
        book.save(path)
        book.close()


def exact(actual, expected, *, forbid_float=True):
    if forbid_float:
        assert not isinstance(actual, float), (actual, expected)
    assert Decimal(str(actual)) == Decimal(expected), (actual, expected)


def db_snapshot(path, output):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as origin, sqlite3.connect(output) as target:
        origin.backup(target)


@pytest.mark.parametrize("value", ["9007199254740993.01", "9007199254740992.99", "9007199254740993.00",
                                  "9007199254740991.00", "0.01", "-0.01", "0.99", "-0.99", "100.50", "5200.00", "5000.00", "0.00"])
def test_decimal_serialization_preserves_exact_money_without_float(value, evidence):
    result = to_jsonable({"amount": Decimal(value), "count": 1, "ok": True})
    dump(evidence, "serialized.json", result)
    exact(result["amount"], value)
    assert type(result["count"]) is int and type(result["ok"]) is bool
    if Decimal(value) != Decimal(value).to_integral_value() or abs(Decimal(value)) > 9007199254740991:
        assert type(result["amount"]) is str
    else:
        assert type(result["amount"]) is int


def test_shared_serializer_keeps_existing_nonfinancial_types(evidence):
    values = {"count": 2, "flag": False, "ratio": 1.25, "missing": None,
              "date": date(2026, 10, 30), "time": time(12, 30), "timestamp": datetime(2026, 10, 30, 12),
              "np_count": np.int64(4), "np_ratio": np.float64(2.5), "nan": float("nan"),
              "decimal_nan": Decimal("NaN"), "decimal_inf": Decimal("Infinity"),
              "nested": (Decimal("5200.00"), [Decimal("0.01")]), "original_text": "00123"}
    actual = to_jsonable(values)
    dump(evidence, "consumer_types.json", actual)
    assert actual == {"count": 2, "flag": False, "ratio": 1.25, "missing": None,
                      "date": "2026-10-30", "time": "12:30:00", "timestamp": "2026-10-30T12:00:00",
                      "np_count": 4, "np_ratio": 2.5, "nan": None, "decimal_nan": None, "decimal_inf": None,
                      "nested": [5200, ["0.01"]], "original_text": "00123"}
    assert type(actual["count"]) is int and type(actual["ratio"]) is float
    assert type(actual["np_count"]) is int and type(actual["np_ratio"]) is np.float64
    json.dumps(actual, allow_nan=False)


def test_nonfinancial_numpy_compatibility_matches_original(evidence):
    # np.float64 already satisfies isinstance(value, float) in the original
    # serializer, so it must retain that exact type rather than be coerced.
    values = {"count": np.int64(4), "ratio": np.float64(2.5), "plain": 1.25, "flag": True}
    actual = to_jsonable(values)
    dump(evidence, "original_compatible_types.json", {"values": actual,
         "types": {key: type(value).__module__ + "." + type(value).__name__ for key, value in actual.items()}})
    assert type(actual["count"]) is int
    assert type(actual["ratio"]) is np.float64
    assert type(actual["plain"]) is float
    assert type(actual["flag"]) is bool
    assert json.loads(json.dumps(actual, allow_nan=False)) == {"count": 4, "ratio": 2.5, "plain": 1.25, "flag": True}


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_exact_text_input_real_sqlite_query_and_validation(extension, evidence, temp_settings, db_session):
    source = temp_settings.upload_dir / ("source" + extension)
    rows = [row(amount, index) for index, amount in enumerate(AMOUNTS, 1)]
    write_source(source, rows)
    shutil.copyfile(source, evidence / source.name)
    for values in rows:
        db_session.add(FinancialRecord(**dict(zip(FIELDS, values)), source="synthetic_r2b"))
    db_session.commit()
    read = read_data_file(str(source), settings=temp_settings)
    responses = [query_bi(supplier_id=values[0], order_id=values[2], db=db_session) for values in rows]
    refs = [response["result"]["records"][0] for response in responses]
    checked = validate_data(str(source), reference_records=refs, settings=temp_settings)
    dump(evidence, "read_query_validate.json", {"read": read, "queries": responses, "validation": checked})
    db_snapshot(Path(db_session.bind.url.database).resolve(), evidence / "financial.sqlite")
    assert checked["result"]["issues"] == []
    assert checked["result"]["valid_rows"] == len(rows)
    assert type(checked["result"]["reference_compared"]) is bool
    for source_row, reference, values in zip(read["result"]["records"], refs, rows):
        assert source_row["data"]["amount"] == values[3]
        assert reference["supplier_id"] == values[0] and reference["order_id"] == values[2]
        exact(reference["amount"], values[3])
        assert type(reference["record_id"]) is int
    with sqlite3.connect(evidence / "financial.sqlite") as saved:
        assert saved.execute("SELECT amount FROM bi_financial_records ORDER BY id").fetchall() == [(value,) for value in AMOUNTS]


@pytest.mark.parametrize("source,reference,difference", DELTAS + [("5200.00", "5000.00", "200.00")])
def test_real_validation_difference_and_exception_receipt(source, reference, difference, evidence, temp_settings, db_session):
    path = temp_settings.upload_dir / "delta.csv"
    write_source(path, [row(source)])
    shutil.copyfile(path, evidence / "source.csv")
    db_session.add(FinancialRecord(**dict(zip(FIELDS, row(reference))), source="synthetic_r2b"))
    task = Task(description="Synthetic exact exception", status="waiting_confirmation")
    db_session.add(task)
    db_session.commit()
    queried = query_bi(supplier_id="001", order_id="0001", db=db_session)
    checked = validate_data(str(path), reference_records=queried["result"]["records"], settings=temp_settings)
    dump(evidence, "query_validate.json", {"query": queried, "validation": checked, "expected_difference": difference})
    assert len(checked["result"]["issues"]) == 1
    issue = checked["result"]["issues"][0]
    assert issue["type"] == "amount_mismatch"
    data = {"supplier_id": "001", "order_id": "0001", "issue_type": "amount_mismatch",
            **{key: issue[key] for key in ("excel_amount", "bi_amount", "difference")}}
    submitted = submit_to_oa(task.id, "reconciliation_exception", data, operation_id="synthetic-exception", db=db_session)
    saved = db_session.query(OaReconciliationRecord).one()
    readback = read_oa_record(saved.record_id, db=db_session)
    dump(evidence, "receipt.json", {"submission": submitted, "raw_payload": saved.payload, "readback": readback})
    db_snapshot(Path(db_session.bind.url.database).resolve(), evidence / "financial.sqlite")
    for key, value in (("excel_amount", source), ("bi_amount", reference), ("difference", difference)):
        exact(issue[key], value)
        exact(json.loads(saved.payload)[key], value)
        exact(readback["result"]["record"]["data"][key], value)
    assert saved.review_status == "pending_review"
    replay = submit_to_oa(task.id, "reconciliation_exception", data, operation_id="synthetic-exception", db=db_session)
    assert replay["result"]["idempotent_replay"] is True
    assert db_session.query(OaReconciliationRecord).count() == 1


def test_decimal_oa_payload_is_exact_and_idempotent(evidence, db_session):
    task = Task(description="Synthetic Decimal payload", status="pending")
    db_session.add(task)
    db_session.commit()
    data = dict(zip(FIELDS, row("9007199254740993.01")))
    data.update(amount=Decimal("9007199254740993.01"), record_status="matched")
    result = submit_to_oa(task.id, "reconciliation_result", data, operation_id="decimal-result", db=db_session)
    assert result["status"] == "success"
    record = db_session.query(OaReconciliationRecord).one()
    read = read_oa_record(record.record_id, db=db_session)
    dump(evidence, "oa_decimal.json", {"result": result, "payload": record.payload, "read": read})
    db_snapshot(Path(db_session.bind.url.database).resolve(), evidence / "financial.sqlite")
    exact(read["result"]["record"]["data"]["amount"], "9007199254740993.01")
    replay = submit_to_oa(task.id, "reconciliation_result", dict(data, amount="9007199254740993.01"), operation_id="decimal-result", db=db_session)
    assert replay["result"]["idempotent_replay"] is True
    assert db_session.query(OaReconciliationRecord).count() == 1


def test_existing_frontend_formatter_preserves_json_money(evidence):
    script_file = Path(service_module.__file__).parent / "static" / "app.js"
    source = script_file.read_text(encoding="utf-8")
    formatter = source[source.index("const esc ="):source.index("const date =")]
    actual_input = [to_jsonable(Decimal(value)) for value in ("9007199254740993.01", "9007199254740993.00", "0.01", "-0.99", "5200.00")]
    script = formatter + '\nprocess.stdout.write(JSON.stringify(JSON.parse(require("fs").readFileSync(0,"utf8")).map(amount)));'
    node = shutil.which("node")
    assert node, "Node is required to verify the unchanged frontend formatter; no GUI is used."
    run = subprocess.run([node, "-e", script], input=json.dumps(actual_input), capture_output=True, text=True, check=False)
    dump(evidence, "frontend_formatter.json", {"source_sha256": hashlib.sha256(script_file.read_bytes()).hexdigest(),
                                               "input": actual_input, "exit_code": run.returncode,
                                               "stdout": run.stdout, "stderr": run.stderr})
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["9,007,199,254,740,993.01", "9,007,199,254,740,993.00", "0.01", "-0.99", "5,200.00"]


def workbook_money(path, source_rows, reference_rows, *, final, evidence):
    expected_source = {item[2]: item for item in source_rows}
    expected_reference = {item[2]: item for item in reference_rows}
    book = load_workbook(path, data_only=False)
    sheet = book["Reconciliation"]
    with zipfile.ZipFile(path) as zipped:
        xml = zipped.read("xl/worksheets/sheet3.xml")
    (evidence / (path.stem + "_reconciliation.xml")).write_bytes(xml)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cells = {cell.attrib["r"]: cell for cell in ET.fromstring(xml).findall(".//s:sheetData/s:row/s:c", ns)}
    observed = []
    for number, item in enumerate(sheet.iter_rows(min_row=6, values_only=True), 6):
        order = item[5]
        original, reference = expected_source[order], expected_reference[order]
        current = reference[3] if final else original[3]
        expected = [original[3], current, reference[3], str(Decimal(current) - Decimal(reference[3]))]
        assert item[4] == original[0] and order == original[2]
        for col, value in zip("GHIJ", expected):
            cell = sheet[f"{col}{number}"]
            # Excel's existing numeric cells are checked by both loaded value and raw decimal XML.
            exact(cell.value, value, forbid_float=False)
            if cell.data_type == "n":
                raw = cells[cell.coordinate].find("s:v", ns).text
                exact(raw, value)
            else:
                assert cell.data_type == "s"
                exact(cell.value, value)
        observed.append({"order_id": order, "amounts": item[6:10], "types": [sheet[f"{col}{number}"].data_type for col in "GHIJ"]})
    assert len(observed) == len(source_rows)
    assert book["Summary"]["B4"].value == ("FINAL - completed" if final else "INTERIM - needs review")
    assert not any(cell.data_type == "f" for worksheet in book for line in worksheet for cell in line)
    book.close()
    dump(evidence, path.stem + "_opened.json", observed)


@pytest.mark.parametrize("original", EXCEL_BOUNDARIES + EXCEL_CONTROLS)
def test_existing_excel_money_boundary_raw_xml(original, evidence):
    book = Workbook()
    book.active.title = "Money"
    excel_report.put(book.active, 1, 1, original)
    excel_report.put(book.active, 1, 2, excel_report.numeric_decimal(Decimal(original)))
    path = evidence / "actual_excel_writer.xlsx"
    book.save(path)
    book.close()
    reopened = load_workbook(path, data_only=False)
    value = reopened["Money"]["B1"]
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml")
    (evidence / "actual_saved.xml").write_bytes(xml)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    stored = ET.fromstring(xml).find('.//s:c[@r="B1"]', ns)
    raw = stored.find("s:v", ns).text if value.data_type == "n" else "".join(stored.itertext())
    dump(evidence, "saved_boundary.json", {"input": original, "loaded": str(value.value), "cell_type": value.data_type,
         "raw_xml": raw, "exact_delta": str(Decimal(raw) - Decimal(original)),
         "writer_sha256": hashlib.sha256(Path(excel_report.__file__).read_bytes()).hexdigest()})
    loaded = value.value
    reopened.close()
    # Reopening as a float can mask the saved .001 error; require raw XML equality.
    exact(loaded, original, forbid_float=False)
    exact(raw, original)


def test_saved_money_supports_exact_decimal_arithmetic(evidence):
    pairs = [("9999999999999.13", "9999999999999.12"),
             ("8796093022208.13", "8796093022208.12"),
             ("9007199254740993.01", "9007199254740993.00"),
             ("100.13", "100.12"), ("0.01", "0.99"), ("0.00", "0.00")]
    book = Workbook()
    for number, (left, right) in enumerate(pairs, 1):
        excel_report.put(book.active, number, 1, excel_report.numeric_decimal(Decimal(left)))
        excel_report.put(book.active, number, 2, excel_report.numeric_decimal(Decimal(right)))
        excel_report.put(book.active, number, 3, excel_report.difference(left, right))
    path = evidence / "saved_arithmetic.xlsx"
    book.save(path)
    book.close()
    reopened = load_workbook(path, data_only=False)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml")
    (evidence / "saved_arithmetic.xml").write_bytes(xml)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    cells = {cell.attrib["r"]: cell for cell in ET.fromstring(xml).findall(".//s:sheetData/s:row/s:c", ns)}
    def stored_decimal(coordinate):
        cell = cells[coordinate]
        value = cell.find("s:v", ns)
        return Decimal(value.text if value is not None else "".join(cell.itertext()))
    observed, restored_sum = [], Decimal(0)
    for number, (left, right) in enumerate(pairs, 1):
        saved_left, saved_right, saved_difference = [stored_decimal(f"{column}{number}") for column in "ABC"]
        recomputed = saved_left - saved_right
        restored_sum += saved_left + saved_right
        expected = Decimal(left) - Decimal(right)
        observed.append({"left": str(saved_left), "right": str(saved_right), "computed_difference": str(recomputed),
                         "stored_report_difference": str(saved_difference), "expected": str(expected)})
        assert saved_left == Decimal(left) and saved_right == Decimal(right)
        assert recomputed == saved_difference == expected
        for column, value in zip("ABC", (saved_left, saved_right, saved_difference)):
            exact(reopened.active[f"{column}{number}"].value, str(value), forbid_float=False)
    expected_sum = sum((Decimal(value) for pair in pairs for value in pair), Decimal(0))
    dump(evidence, "actual_saved_arithmetic.json", {"rows": observed, "saved_values_sum": str(restored_sum),
         "expected_sum": str(expected_sum), "sum_delta": str(restored_sum - expected_sum),
         "method": "Exact Decimal arithmetic from saved XML values; no Excel formula evaluation is claimed."})
    reopened.close()
    assert restored_sum == expected_sum


@pytest.mark.parametrize("extension", [".csv", ".xlsx"])
def test_real_api_batch_money_receipts_json_csv_and_xlsx(extension, tmp_path, evidence):
    source_rows = [row(value, index) for index, value in enumerate(AMOUNTS, 1)]
    reference_rows = [list(item) for item in source_rows]
    for source, reference, _ in DELTAS:
        index = len(source_rows) + 1
        source_rows.append(row(source, index))
        reference_rows.append(row(reference, index))
    for field in (5, 6):
        index = len(source_rows) + 1
        source_rows.append(row("100.50", index))
        reference_rows.append(row("100.50", index))
        source_rows[-1][field] = "paid" if field == 5 else "closed"
    inbox = tmp_path / "inbox"
    for role, rows in (("source", source_rows), ("reference", reference_rows)):
        path = inbox / role / (role + extension)
        write_source(path, rows)
        shutil.copyfile(path, evidence / (role + extension))
    app = create_app(tmp_path / "workspace")
    service = app.state.service
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        assert client.post("/api/setup", json={"username": "Synthetic money reviewer", "password": secrets.token_urlsafe(24)}).status_code == 200
        scan = client.post("/api/batches/scan", json={"folder": str(inbox)})
        assert scan.status_code == 202, scan.text
        batch_id = scan.json()["id"]
        service.future.result(timeout=60)
        scanned = client.get(f"/api/batches/{batch_id}").json()
        dump(evidence, "batch_scanned.json", scanned)
        assert scanned["runnable_tables"] == 1
        assert client.post(f"/api/batches/{batch_id}/run").status_code == 200
        service.future.result(timeout=60)
        interim = client.get(f"/api/batches/{batch_id}").json()
        dump(evidence, "batch_interim.json", interim)
        response = client.get(f"/api/batches/{batch_id}/report")
        assert response.status_code == 200
        interim_book = evidence / "interim.xlsx"
        interim_book.write_bytes(response.content)
        # Preserve baseline failure output even when the unexpected false issues block final reports.
        initial_tasks = [client.get(f"/api/tasks/{item['job_id']}").json() for item in service.batches._jobs(batch_id)]
        dump(evidence, "tasks_interim.json", initial_tasks)
        assert interim["status"] == "needs_review"
        assert interim["matched_rows"] == interim["archive_receipts"] == len(AMOUNTS), interim
        assert interim["unresolved_rows"] == 6
        workbook_money(interim_book, source_rows, reference_rows, final=False, evidence=evidence)
        differences = []
        for item in interim["review_tasks"]:
            task = client.get(f"/api/tasks/{item['job_id']}").json()
            blocked = client.post(f"/api/tasks/{task['id']}/run")
            dump(evidence, f"task_{task['id']}_unconfirmed.json", {"http": blocked.status_code, "body": blocked.json()})
            assert blocked.status_code == 409
            for issue in task["issues"]:
                if issue["type"] == "amount_mismatch":
                    differences.append(str(Decimal(str(issue["difference"]))))
                    exact(issue["excel_amount"], issue["original_value"])
                    exact(issue["bi_amount"], issue["reference_value"])
                    exact(issue["difference"], str(Decimal(issue["original_value"]) - Decimal(issue["reference_value"])))
            types = {issue["type"] for issue in task["issues"]}
            assert types <= {"amount_mismatch", "payment_status_mismatch", "record_status_mismatch"}
            response = client.post(f"/api/tasks/{task['id']}/review", json={"revision": task["revision"], "evidence_digest": task["evidence_digest"],
                "changes": [{"issue_id": issue["id"], "mode": "reference", "value": None} for issue in task["issues"]],
                "reason": "Synthetic reviewer verified exact cent values and source status evidence."})
            assert response.status_code == 200, response.text
            assert not response.json()["issues"]
            assert client.post(f"/api/tasks/{task['id']}/run").status_code == 200
            service.future.result(timeout=60)
        assert sorted(differences) == sorted([item[2] for item in DELTAS])
        final = client.get(f"/api/batches/{batch_id}").json()
        dump(evidence, "batch_final.json", final)
        assert final["status"] == "completed", final
        assert final["matched_rows"] == final["archive_receipts"] == len(source_rows)
        response = client.get(f"/api/batches/{batch_id}/report")
        assert response.status_code == 200
        final_book = evidence / "final.xlsx"
        final_book.write_bytes(response.content)
        workbook_money(final_book, source_rows, reference_rows, final=True, evidence=evidence)
        expected = {item[2]: item[3] for item in reference_rows}
        receipts, exported = [], []
        for association in service.batches._jobs(batch_id):
            job_id = association["job_id"]
            response = client.get(f"/api/tasks/{job_id}/report")
            assert response.status_code == 200
            path = evidence / f"task_{job_id}_report.json"
            path.write_bytes(response.content)
            report = json.loads(path.read_text(encoding="utf-8"))
            assert report["report_kind"] == "final" and report["status"] == "completed"
            receipts.extend(report["archive"])
            for receipt in report["archive"]:
                exact(receipt["data"]["amount"], expected[receipt["data"]["order_id"]])
            for step in report["trace"]:
                if step["tool"] == "query_bi":
                    for record in step["envelope"]["result"]["records"]:
                        exact(record["amount"], expected[record["order_id"]])
            response = client.get(f"/api/tasks/{job_id}/export")
            assert response.status_code == 200
            csv_path = evidence / f"task_{job_id}_reconciled.csv"
            csv_path.write_bytes(response.content)
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                exported.extend(csv.DictReader(handle))
            db_path = service.store.root / "jobs" / str(job_id) / "financial.sqlite"
            db_snapshot(db_path, evidence / f"task_{job_id}_financial.sqlite")
            with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as db:
                bi_rows = db.execute("SELECT supplier_id,order_id,amount FROM bi_financial_records").fetchall()
                oa_rows = db.execute("SELECT operation_id,payload FROM oa_reconciliation_records").fetchall()
            for _, order, amount in bi_rows:
                assert amount == expected[order]
            for _, payload in oa_rows:
                record = json.loads(payload)
                exact(record["amount"], expected[record["order_id"]])
            dump(evidence, f"task_{job_id}_database_rows.json", {"bi": bi_rows, "oa": oa_rows})
        assert len(receipts) == len({receipt["id"] for receipt in receipts}) == len(source_rows)
        assert len(exported) == len(source_rows)
        for record in exported:
            assert record["amount"] == expected[record["order_id"]]
            assert len(record["supplier_id"]) == 3 and len(record["order_id"]) == 4
        central = service.store.all("SELECT * FROM archive ORDER BY id")
        dump(evidence, "central_archive.json", central)
        assert len(central) == len(receipts)
        for record in central:
            payload = json.loads(record["payload_json"])
            exact(payload["amount"], expected[payload["order_id"]])
        # Source/reference originals stay byte-identical throughout correction and export.
        for role in ("source", "reference"):
            assert (inbox / role / (role + extension)).read_bytes() == (evidence / (role + extension)).read_bytes()
