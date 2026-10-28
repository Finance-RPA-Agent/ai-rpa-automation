"""Bounded natural-language intake and automatic execution of the existing workflow."""
import csv
import io
import threading

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import httpx
import pytest

from product.api import create_app
from product.commands import Interpretation
from product.model import ModelUnavailable, OllamaProvider
from product.service import FIELDS


class Model:
    def __init__(self):
        self.payload = {"intent": "reconcile_folder", "folders": [], "message": "Reconcile the folder."}
        self.inputs = []

    def interpret_command(self, instruction, schema):
        self.inputs.append(instruction)
        return self.payload


@pytest.fixture
def local(tmp_path):
    model = Model()
    app = create_app(tmp_path / "workspace", model=model)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        client.post("/api/setup", json={"username": "Command Owner", "password": "123456"})
        inbox = tmp_path / "inbox"
        rows = [["001", "Acme", "0001", "100.00", "2026-10-01", "pending", "active"],
                ["002", "Cedar", "0002", "200.00", "2026-10-02", "paid", "active"]]
        for role in ("source", "reference"):
            folder = inbox / role
            folder.mkdir(parents=True)
            data = [list(row) for row in rows]
            if role == "source":
                data[1][3] = "225.00"
            with (folder / ("orders.csv" if role == "source" else "bi.csv")).open("w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(FIELDS)
                writer.writerows(data)
        yield client, app.state.service, model, inbox


def prepare(local, instruction="Reconcile this folder and create an Excel report."):
    client, _, _, inbox = local
    response = client.post("/api/commands/prepare", json={"instruction": instruction, "folder": str(inbox)})
    assert response.status_code == 200, response.text
    return response.json()


def test_one_command_scans_runs_archives_only_clean_rows_and_reports(local):
    client, service, model, inbox = local
    command = prepare(local)
    assert command["status"] == "prepared"
    assert service.batches.list() == []
    response = client.post(f"/api/commands/{command['id']}/execute")
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    service.future.result(timeout=60)
    batch = client.get(f"/api/batches/{batch_id}").json()
    assert batch["scan_complete"] and batch["status"] == "needs_review"
    assert batch["matched_rows"] == batch["archive_receipts"] == 1
    assert batch["unresolved_rows"] == 1
    assert len(batch["review_tasks"]) == 1
    assert batch["command"]["instruction"] == command["instruction"]
    assert service.batches.batch(batch_id)["report_path"]
    report = client.get(f"/api/batches/{batch_id}/report")
    workbook = load_workbook(io.BytesIO(report.content))
    assert workbook["Summary"]["A27"].value == command["instruction"]
    assert client.post(f"/api/commands/{command['id']}/execute").json()["id"] == batch_id
    assert len(service.batches.list()) == 1
    assert client.get("/api/commands").json()["commands"][0]["status"] == "needs_review"
    assert model.inputs == [command["instruction"]]


def test_chinese_request_extracts_literal_folder_and_no_file_content_is_sent(local):
    client, _, model, inbox = local
    instruction = f'检查 "{inbox}" 的订单，与参考表对账，只让我处理异常，生成 Excel 报告。'
    model.payload["folders"] = [str(inbox)]
    response = client.post("/api/commands/prepare", json={"instruction": instruction})
    assert response.status_code == 200, response.text
    assert response.json()["folder"] == str(inbox)
    assert model.inputs == [instruction]


def test_unsupported_missing_and_multiple_folders_never_start(local):
    client, service, model, inbox = local
    model.payload.update(intent="unsupported", message="Payments are not supported.")
    assert prepare(local)["status"] == "needs_input"
    model.payload.update(intent="reconcile_folder", folders=[])
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile my orders."}).json()["status"] == "needs_input"
    model.payload["folders"] = [str(inbox), str(inbox / "source")]
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile both folders."}).json()["status"] == "needs_input"
    assert service.store.all("SELECT * FROM commands") == []
    assert service.batches.list() == []


def test_invented_and_conflicting_paths_are_rejected(local):
    client, service, model, inbox = local
    model.payload["folders"] = [str(inbox)]
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile my orders."}).status_code == 422
    response = client.post("/api/commands/prepare", json={"instruction": f"Reconcile {inbox}", "folder": str(inbox / "source")})
    assert response.json()["status"] == "needs_input"
    model.payload["folders"] = []
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile files.", "folder": str(service.store.root)}).status_code == 422


def test_invalid_model_output_and_offline_model_do_not_create_commands(local):
    client, service, model, _ = local
    model.payload["tool"] = "execute_code"
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile my files."}).status_code == 503
    def offline(*args):
        raise ModelUnavailable("Start Ollama.")
    model.interpret_command = offline
    assert client.post("/api/commands/prepare", json={"instruction": "Reconcile my files."}).status_code == 503
    assert service.store.all("SELECT * FROM commands") == []


def test_auth_csrf_and_request_shape(local):
    client, service, _, _ = local
    assert client.post("/api/commands/prepare", json={"instruction": "Do this", "shell": "anything"}).status_code == 422
    assert client.post("/api/commands/prepare", headers={"X-Requested-With": "other"}, json={"instruction": "Do this"}).status_code == 403
    client.post("/api/logout")
    assert client.get("/api/commands").status_code == 401
    assert client.post("/api/commands/prepare", json={"instruction": "Do this"}).status_code == 401
    assert client.post("/api/commands/any/execute").status_code == 401


def test_auto_mode_without_reference_stops_for_table_setup(local):
    client, service, _, inbox = local
    (inbox / "reference" / "bi.csv").unlink()
    command = prepare(local)
    batch_id = client.post(f"/api/commands/{command['id']}/execute").json()["id"]
    service.future.result(timeout=60)
    batch = service.batches.describe(batch_id)
    assert batch["status"] == "needs_review" and batch["attention"]
    assert batch["archive_receipts"] == 0
    assert batch["report_available"]


def test_cancel_during_scan_never_runs_reconciliation(local, monkeypatch):
    client, service, _, _ = local
    command = prepare(local)
    entered, release = threading.Event(), threading.Event()
    original = service.batches._scan
    def blocked(batch_id):
        entered.set()
        assert release.wait(10)
        original(batch_id)
    monkeypatch.setattr(service.batches, "_scan", blocked)
    batch_id = client.post(f"/api/commands/{command['id']}/execute").json()["id"]
    assert entered.wait(10)
    try:
        assert client.post(f"/api/batches/{batch_id}/cancel").status_code == 200
    finally:
        release.set()
    service.future.result(timeout=60)
    assert service.batches.describe(batch_id)["status"] == "cancelled"
    assert service.batches.describe(batch_id)["archive_receipts"] == 0


def test_loopback_model_structured_request_and_transport_failure():
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]})
        import json
        body = json.loads(request.content)
        assert body["format"] == Interpretation.model_json_schema()
        assert body["messages"][-1]["content"] == "Reconcile my folder."
        return httpx.Response(200, json={"done": True, "message": {"content": '{"intent":"reconcile_folder","folders":[],"message":"Choose a folder."}'}})
    model = OllamaProvider(transport=httpx.MockTransport(handle))
    assert model.interpret_command("Reconcile my folder.", Interpretation.model_json_schema())["intent"] == "reconcile_folder"
    assert all(request.url.host == "127.0.0.1" for request in calls)
