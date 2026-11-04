"""Real upload lifecycle checks on per-test synthetic stores."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from threading import Event

from fastapi import HTTPException
from fastapi.testclient import TestClient
from openpyxl import Workbook
import pytest

from product.api import create_app
from product.service import FIELDS, MAX_BYTES, MAX_ROWS, ProductService

DATA = b"a,b\n1,2\n"
BAD = b'a,b\n"unterminated'
FINANCE_ROW = ["001", "Example Supplies", "0001", "10.25", "2026-10-01", "pending", "active"]


class NoModel:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        self.calls.append(name)
        raise AssertionError(f"Unexpected model use: {name}")


@pytest.fixture
def model():
    fake = NoModel()
    yield fake
    assert fake.calls == []


@pytest.fixture
def service(tmp_path, model):
    instance = ProductService(tmp_path / "store", model=model)
    yield instance
    instance.executor.shutdown(wait=True)


def observe(service, label):
    root = service.store.root / "files"
    rows = service.store.all("SELECT * FROM files ORDER BY id")
    dirs = sorted(p.name for p in root.iterdir())
    disk = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.glob("*/*")) if p.is_file()}
    print(json.dumps({"label": label, "dirs": dirs, "originals": disk, "db_files": len(rows),
                      "ids": [row["id"] for row in rows]}, sort_keys=True))
    return rows, dirs, disk


def empty(service):
    assert observe(service, "expected empty") == ([], [], {})


@pytest.mark.parametrize("case", ["role", "suffix", "empty", "oversize"])
def test_preflight(service, case):
    name, content, role = "input.csv", DATA, "source"
    if case == "role":
        role = "invalid"
    elif case == "suffix":
        name = "input.xls"
    elif case == "empty":
        content = b""
    else:
        content = b"x" * (MAX_BYTES + 1)
    with pytest.raises(HTTPException) as caught:
        service.upload(name, content, role)
    assert caught.value.status_code == 422
    empty(service)


def test_mkdir_denied(service, monkeypatch):
    def deny(folder):
        assert folder.parent == service.store.root / "files"
        raise PermissionError("injected mkdir denial")
    monkeypatch.setattr(Path, "mkdir", deny)
    with pytest.raises(PermissionError, match="mkdir denial"):
        service.upload("x.csv", DATA, "source")
    empty(service)


def test_id_collision(service, monkeypatch):
    accepted = service.upload("x.csv", DATA, "source")
    before = observe(service, "before collision")
    monkeypatch.setattr("product.service.secrets.token_hex", lambda _: accepted["id"])
    with pytest.raises(FileExistsError):
        service.upload("x.csv", BAD, "source")
    assert observe(service, "after collision") == before


def test_partial_write(service, monkeypatch):
    write = Path.write_bytes

    def partial(raw, data):
        assert write(raw, data[:3]) == 3
        assert raw.read_bytes() == data[:3]
        raise OSError("injected partial write")
    monkeypatch.setattr(Path, "write_bytes", partial)
    with pytest.raises(OSError, match="partial write"):
        service.upload("x.csv", DATA, "source")
    empty(service)


@pytest.mark.parametrize("name,content,reason", [
    pytest.param("x.csv", BAD, "correctly closed", id="unclosed"),
    pytest.param("x.csv", b"a,b\n\xff,2\n", "UTF-8", id="bad-utf8"),
    pytest.param("x.xlsx", b"not-a-workbook", "valid .xlsx", id="bad-xlsx"),
])
def test_parser_rejection(service, name, content, reason):
    empty(service)
    with pytest.raises(ValueError, match=reason):
        service.upload(name, content, "source")
    rows, dirs, disk = observe(service, "after parser rejection")
    assert rows == []
    assert disk == {}, "Rejected upload left original bytes on disk"
    assert dirs == []


@pytest.mark.parametrize("content,reason", [
    pytest.param(b",b\n1,2\n", "Headers", id="empty-header"),
    pytest.param(b"a,a\n1,2\n", "Headers", id="duplicate-header"),
    pytest.param(b"a,b\n", "data rows", id="no-data"),
    pytest.param(b"a\n" + b"1\n" * (MAX_ROWS + 1), "5,000", id="rows"),
    pytest.param(b",".join([b"x"] * 201) + b"\n", "200 columns", id="columns"),
    pytest.param(b"a,b\n1,2,3\n", "CSV_STRUCTURE", id="reader-error"),
])
def test_table_rejection(service, content, reason):
    with pytest.raises(ValueError, match=reason):
        service.upload("x.csv", content, "source")
    empty(service)


def test_insert_rejected(service):
    with service.store.connect() as db:
        db.execute("CREATE TRIGGER reject_file BEFORE INSERT ON files BEGIN "
                   "SELECT RAISE(ABORT, 'injected INSERT failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="INSERT failure"):
        service.upload("x.csv", DATA, "source")
    empty(service)


@pytest.mark.parametrize("fault", ["pre-commit", "post-commit", "query-unavailable"])
def test_registration_exit(service, monkeypatch, fault):
    original_connect = sqlite3.connect
    events = []

    class FaultConnection(sqlite3.Connection):
        def commit(self):
            assert self.in_transaction
            assert self.execute("SELECT count(*) FROM files").fetchone()[0] == 1
            events.append("insert visible to writer")
            if fault == "post-commit":
                super().commit()
                events.append("commit completed")
            raise sqlite3.OperationalError("injected commit boundary")

        def rollback(self):
            events.append(("rollback", self.in_transaction))
            super().rollback()

    def connect(*args, **kwargs):
        assert Path(args[0]) == service.store.path
        if not events:
            kwargs["factory"] = FaultConnection
        elif fault == "query-unavailable":
            events.append("fresh lookup unavailable")
            raise sqlite3.OperationalError("injected lookup failure")
        return original_connect(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        if fault == "query-unavailable":
            with pytest.raises(HTTPException) as caught:
                service.upload("x.csv", DATA, "source")
            assert caught.value.status_code == 503 and "registration" in caught.value.detail
            assert isinstance(caught.value.__cause__, sqlite3.OperationalError)
        else:
            with pytest.raises(sqlite3.OperationalError, match="commit boundary"):
                service.upload("x.csv", DATA, "source")
    print(fault, events)
    assert ("rollback", fault != "post-commit") in events
    rows, dirs, disk = observe(service, fault)
    if fault == "pre-commit":
        assert (rows, dirs, disk) == ([], [], {})
    else:
        assert len(dirs) == 1
        assert disk == {dirs[0] + "/original.csv": sha256(DATA).hexdigest()}
        if fault == "post-commit":
            assert [r["id"] for r in rows] == dirs
            assert service.file_view(dirs[0])["preview"]
        else:
            assert rows == [] and "fresh lookup unavailable" in events


def deny_unlink(monkeypatch, service):
    unlink = Path.unlink

    def deny(raw, *args, **kwargs):
        if raw.name == "original.csv" and raw.parent.parent == service.store.root / "files":
            raise PermissionError("injected original lock")
        return unlink(raw, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny)


def test_cleanup_failure_chain(service, monkeypatch):
    accepted = service.upload("first.csv", DATA, "source")
    with monkeypatch.context() as patch:
        deny_unlink(patch, service)
        with pytest.raises(HTTPException) as caught:
            service.upload("other.csv", BAD, "source")
    assert caught.value.status_code == 503 and "cleanup" in caught.value.detail
    cause = caught.value.__cause__
    assert isinstance(cause, PermissionError) and isinstance(cause.__context__, ValueError)
    rows, dirs, disk = observe(service, "cleanup denied")
    assert [r["id"] for r in rows] == [accepted["id"]]
    assert len(dirs) == len(disk) == 2
    assert sorted(disk.values()) == sorted(sha256(d).hexdigest() for d in (DATA, BAD))
    assert service.file_view(accepted["id"]) == accepted


def finance_bytes(suffix):
    if suffix == ".csv":
        return (",".join(FIELDS) + "\n" + ",".join(FINANCE_ROW) + "\n").encode()
    book = Workbook()
    book.active.append(FIELDS)
    book.active.append(FINANCE_ROW)
    buffer = BytesIO()
    book.save(buffer)
    book.close()
    return buffer.getvalue()


@pytest.fixture
def http(tmp_path, model):
    app = create_app(tmp_path / "http", model=model)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        yield client, app.state.service


def login(client):
    assert client.post("/api/setup", json={"username": "synthetic", "password": "r4a-test-only"}).status_code == 200


def post(client, name, content, role="source"):
    return client.post("/api/files", files={"file": (name, content)}, data={"role": role})


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("role", ["source", "reference"])
def test_http_success(http, suffix, role):
    client, service = http
    login(client)
    name, content = "orders" + suffix, finance_bytes(suffix)
    response = post(client, name, content, role)
    assert response.status_code == 201
    view = response.json()
    assert (view["role"], view["name"], view["row_count"], view["ready"]) == (role, name, 1, True)
    assert view["columns"] == FIELDS and view["mapping"] == {f: f for f in FIELDS}
    assert view["sha256"] == sha256(content).hexdigest()
    assert view["preview"] == [{"row": 2, "data": dict(zip(FIELDS, FINANCE_ROW))}]
    assert client.get("/api/files/" + view["id"]).json() == view
    assert service.path(service.file(view["id"])["raw_path"]).read_bytes() == content
    observe(service, "HTTP 201 " + role + suffix)


def test_incomplete_mapping(service):
    alternate = ["field" + str(i) for i in range(len(FIELDS))]
    content = (",".join(alternate) + "\n" + ",".join(FINANCE_ROW) + "\n").encode()
    view = service.upload("later.csv", content, "source")
    assert view["ready"] is False and view["mapping"] == {} and view["columns"] == alternate
    mapped = service.map_file(view["id"], dict(zip(FIELDS, alternate)))
    assert mapped["ready"] is True and mapped["preview"][0]["data"] == dict(zip(FIELDS, FINANCE_ROW))


def test_same_name_task_preservation(service):
    content = finance_bytes(".csv")
    source = service.upload("same.csv", content, "source")
    reference = service.upload("same.csv", content, "reference")
    task = service.create("Synthetic task", "Compare synthetic records", source["id"], reference["id"], False)
    task_before = service.get_job(task["id"])
    historical = service.store.root / "files" / "synthetic-unregistered"
    historical.mkdir()
    (historical / "keep").write_bytes(b"sentinel")
    before = observe(service, "task before rejection")
    with pytest.raises(ValueError, match="correctly closed"):
        service.upload("same.csv", BAD, "source")
    assert observe(service, "task after rejection") == before
    another = service.upload("same.csv", content, "source")
    assert len({source["id"], reference["id"], another["id"]}) == 3
    assert service.get_job(task["id"]) == task_before
    assert service.file_view(source["id"]) == source and service.file_view(reference["id"]) == reference
    assert (historical / "keep").read_bytes() == b"sentinel"


def test_interleaved_requests(service, monkeypatch):
    written, accepted = Event(), Event()
    write = Path.write_bytes

    def pause(raw, data):
        size = write(raw, data)
        if data == BAD:
            written.set()
            assert accepted.wait(10)
        return size
    monkeypatch.setattr(Path, "write_bytes", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        failure = pool.submit(service.upload, "../same.csv", BAD, "source")
        try:
            assert written.wait(10)
            good = service.upload("../same.csv", DATA, "source")
            assert good["name"] == "same.csv"
            rows, dirs, disk = observe(service, "other request still in progress")
            assert len(rows) == 1 and len(dirs) == len(disk) == 2
        finally:
            accepted.set()
        with pytest.raises(ValueError, match="correctly closed"):
            failure.result(timeout=10)
    rows, dirs, disk = observe(service, "after interleaved rejection")
    assert [r["id"] for r in rows] == dirs == [good["id"]]
    assert disk == {good["id"] + "/original.csv": sha256(DATA).hexdigest()}
    assert service.file_view(good["id"]) == good


def test_redirected_folder(service, tmp_path, monkeypatch):
    outside = tmp_path / "separate"
    outside.mkdir()
    sentinel = outside / "original.csv"
    sentinel.write_bytes(b"protected")
    write = Path.write_bytes
    created = []

    def redirect(raw, data):
        write(raw, data)
        created.append(raw.parent)
        assert raw.parent.parent == service.store.root / "files"
        raw.parent.rename(tmp_path / "moved-original")
        if os.name == "nt":
            subprocess.run(["cmd", "/d", "/c", "mklink", "/j", str(raw.parent), str(outside)], check=True, capture_output=True)
        else:
            raw.parent.symlink_to(outside, target_is_directory=True)
        raise OSError("directory redirected")
    monkeypatch.setattr(Path, "write_bytes", redirect)
    with pytest.raises(HTTPException) as caught:
        service.upload("../x.csv", DATA, "source")
    assert caught.value.status_code == 503 and "cleanup" in caught.value.detail
    assert sentinel.read_bytes() == b"protected" and created[0].resolve() == outside
    assert (tmp_path / "moved-original" / "original.csv").read_bytes() == DATA
    assert service.store.all("SELECT id FROM files") == []


def test_http_failure_boundaries(http, monkeypatch):
    client, service = http
    assert post(client, "x.csv", DATA).status_code == 401
    empty(service)
    login(client)
    assert post(client, "invalid.csv", BAD).status_code == 422
    empty(service)
    original = post(client, "other.csv", DATA).json()

    def display_fault(_file_id):
        raise ValueError("Synthetic preview unavailable.")
    with monkeypatch.context() as patch:
        patch.setattr(service, "load_file", display_fault)
        result = post(client, "registered.csv", DATA)
    assert result.status_code == 422 and result.json() == {"detail": "Synthetic preview unavailable."}
    rows, dirs, disk = observe(service, "HTTP display failed after commit")
    assert len(rows) == len(dirs) == len(disk) == 2
    saved = next(row for row in rows if row["name"] == "registered.csv")
    assert service.path(saved["raw_path"]).read_bytes() == DATA
    recovered = client.get("/api/files/" + saved["id"])
    assert recovered.status_code == 200 and recovered.json()["preview"] == original["preview"]
    before = observe(service, "before HTTP cleanup failure")
    with monkeypatch.context() as patch:
        deny_unlink(patch, service)
        response = post(client, "denied.csv", BAD)
    assert response.status_code == 503
    assert response.json() == {"detail": "Upload failed and cleanup could not be confirmed."}
    rows, dirs, disk = observe(service, "HTTP cleanup failure")
    assert rows == before[0] and len(dirs) == len(disk) == 3
    assert set(before[2].items()) <= set(disk.items())
    assert list(disk.values()).count(sha256(BAD).hexdigest()) == 1
    assert service.file_view(original["id"]) == original


def test_unrelated_file_in_request_folder(service, monkeypatch):
    write = Path.write_bytes

    def add_sibling(raw, data):
        size = write(raw, data)
        write(raw.parent / "keep.txt", b"separate file")
        return size

    monkeypatch.setattr(Path, "write_bytes", add_sibling)
    with pytest.raises(HTTPException) as caught:
        service.upload("x.csv", BAD, "source")
    assert caught.value.status_code == 503 and "cleanup" in caught.value.detail
    rows, dirs, disk = observe(service, "nonempty directory retained")
    assert not rows and len(dirs) == 1
    assert disk == {dirs[0] + "/keep.txt": sha256(b"separate file").hexdigest()}


def test_workbook_open_error_boundary(service, monkeypatch):
    content = finance_bytes(".xlsx")
    original_open = Path.open
    reached = []

    def fail_reload(path, mode="r", *args, **kwargs):
        # ZipFile opens the container through io.open. This is the subsequent workbook read.
        if mode == "rb" and path.name == "original.xlsx":
            reached.append(path)
            raise PermissionError("injected workbook open denial")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_reload)
    with pytest.raises(ValueError, match="workbook could not be opened") as caught:
        service.upload("orders.xlsx", content, "reference")
    assert isinstance(caught.value.__cause__, PermissionError) and len(reached) == 1
    empty(service)
