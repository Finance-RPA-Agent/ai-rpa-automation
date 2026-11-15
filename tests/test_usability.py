"""Quick-start and real, persisted progress; synthetic data in isolated workspaces."""
import threading

import pytest

from test_local_product import app, client, upload, ROWS
from test_data_assistant import local, action, final


def inputs(client, rows=ROWS):
    return {"source_id": upload(client, rows)["id"],
            "reference_id": upload(client, ROWS, "reference", "BI.csv")["id"]}


def test_quick_start_completes_without_model_and_records_authorization(client, app, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Quick reconciliation must not call the model")
    monkeypatch.setattr(app.state.service.model, "plan", unexpected)
    response = client.post("/api/tasks/quick-start", json=inputs(client))
    assert response.status_code == 201, response.text
    job_id = response.json()["id"]
    app.state.service.future.result(timeout=20)
    result = client.get(f"/api/tasks/{job_id}").json()
    assert result["status"] == "completed", result
    assert result["archive_count"] == 2
    assert result["plan"]["mode"] == "deterministic"
    assert result["operation_started_at"]
    event = next(e for e in result["events"] if e["action"] == "Quick reconciliation authorized")
    assert "owner" in event["details_json"]
    assert client.get(f"/api/tasks/{job_id}/export").status_code == 200


def test_quick_start_holds_differences_and_never_changes_original(client, app):
    rows = [list(row) for row in ROWS]
    rows[0][3] = "125.00"
    ids = inputs(client, rows)
    service = app.state.service
    original = service.path(service.file(ids["source_id"])["canonical_path"])
    before = original.read_bytes()
    response = client.post("/api/tasks/quick-start", json=ids)
    assert response.status_code == 201
    service.future.result(timeout=20)
    task = client.get(f"/api/tasks/{response.json()['id']}").json()
    assert task["status"] == "waiting_confirmation", task
    assert any(issue["type"] == "amount_mismatch" for issue in task["issues"])
    assert task["decisions"] == [] and task["archive_count"] == 0
    assert original.read_bytes() == before


def test_busy_quick_start_does_not_create_another_job_and_can_be_cancelled(client, app, monkeypatch):
    ids = inputs(client)
    service = app.state.service
    entered, release = threading.Event(), threading.Event()
    real_execute = service.execute
    def blocked(*args):
        entered.set()
        assert release.wait(10)
        return real_execute(*args)
    monkeypatch.setattr(service, "execute", blocked)
    try:
        first = client.post("/api/tasks/quick-start", json=ids)
        assert first.status_code == 201
        assert entered.wait(5)
        second = client.post("/api/tasks/quick-start", json=ids)
        assert second.status_code == 409
        assert len(service.store.all("SELECT id FROM jobs")) == 1
        job_id = first.json()["id"]
        assert client.post(f"/api/tasks/{job_id}/cancel").status_code == 200
    finally:
        release.set()
        service.future.result(timeout=20)
    task = client.get(f"/api/tasks/{job_id}").json()
    assert task["status"] == "cancelled" and task["archive_count"] == 0


def test_quick_start_rejects_bad_inputs_without_orphan_jobs(client, app):
    ids = inputs(client)
    assert client.post("/api/tasks/quick-start", json={**ids, "ai": True}).status_code == 422
    assert client.post("/api/tasks/quick-start", json={**ids, "title": " "}).status_code == 422
    assert client.post("/api/tasks/quick-start", json={**ids, "reference_id": ids["source_id"]}).status_code == 422
    assert not app.state.service.store.all("SELECT id FROM jobs")
    client.post("/api/logout")
    assert client.post("/api/tasks/quick-start", json=ids).status_code == 401


@pytest.mark.parametrize("phase", ["planning", "waiting_model", "tool"])
def test_assistant_reports_actual_inflight_phase_and_cancel_request(local, monkeypatch, phase):
    client, service, model, chat, _ = local
    entered, release = threading.Event(), threading.Event()
    if phase == "planning":
        owner, method = model, "data_plan"
    elif phase == "waiting_model":
        owner, method = model, "data_action"
    else:
        from product.data_tools import DataTools
        owner, method = DataTools, "call"
    original = getattr(owner, method)
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    monkeypatch.setattr(owner, method, blocked)
    model.actions = [action("list_files"), final()]
    try:
        response = client.post(f"/api/assistant/chats/{chat['id']}/turns", json={"instruction": "List the available input tables."})
        assert response.status_code == 202, response.text
        assert entered.wait(5)
        turn = client.get(f"/api/assistant/chats/{chat['id']}").json()["turns"][-1]
        assert turn["status"] == "running" and turn["progress"]["phase"] == phase
        assert turn["progress"]["since"] and turn["created_at"] and turn["updated_at"]
        if phase == "tool": assert turn["progress"]["tool"] == "list_files"
        assert client.post(f"/api/assistant/turns/{turn['id']}/cancel").status_code == 200
        assert client.get(f"/api/assistant/chats/{chat['id']}").json()["turns"][-1]["cancel_requested"]
    finally:
        release.set()
        service.future.result(timeout=20)
    done = client.get(f"/api/assistant/chats/{chat['id']}").json()["turns"][-1]
    assert done["status"] == "cancelled" and not done["cancel_requested"]
