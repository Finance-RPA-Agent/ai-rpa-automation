"""Demonstration entry remains isolated from the ordinary owner workspace."""
from fastapi.testclient import TestClient
import pytest

from product.api import create_app, workspace_directory


def browser(app):
    return TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"})


def test_demo_entry_needs_no_credentials_and_logout_requires_a_new_click(tmp_path):
    app = create_app(tmp_path, demo=True)
    with browser(app) as client:
        assert client.get("/api/session").json() == {"setup_required": False, "username": None, "demo_mode": True}
        assert client.get("/api/tasks").status_code == 401
        login = client.post("/api/demo-login")
        assert login.status_code == 200 and login.json()["username"] == "Demo User"
        assert login.json()["demo_mode"] is True
        assert client.get("/api/tasks").status_code == 200
        assert client.post("/api/setup", json={"username": "other", "password": "123456"}).status_code == 409
        assert client.post("/api/password", json={"current_password": "demo", "new_password": "123456"}).status_code == 409
        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/api/session").json()["demo_mode"] is True
        assert client.post("/api/demo-login").status_code == 200
    assert app.state.service.store.root == tmp_path / "demo"
    assert not (tmp_path / "finance-flow.sqlite").exists()


def test_normal_owner_and_records_are_not_changed_by_demo(tmp_path):
    normal = create_app(tmp_path)
    with browser(normal) as client:
        assert client.post("/api/setup", json={"username": "Original Owner", "password": "123456"}).status_code == 200
        user = normal.state.service.store.one("SELECT * FROM users")
        assert client.post("/api/demo-login").status_code == 404
        assert client.post("/api/logout").status_code == 200
        assert client.post("/api/login", json={"username": "Original Owner", "password": "wrong"}).status_code == 401
    demo = create_app(tmp_path, demo=True)
    with browser(demo) as client:
        assert client.post("/api/demo-login").status_code == 200
    assert normal.state.service.store.one("SELECT * FROM users") == user
    reopened = create_app(tmp_path)
    with browser(reopened) as client:
        assert client.post("/api/login", json={"username": "Original Owner", "password": "123456"}).status_code == 200
        assert client.get("/api/session").json()["demo_mode"] is False


def test_demo_identity_survives_restart_without_resetting_a_workspace(tmp_path):
    app = create_app(tmp_path, demo=True)
    with browser(app) as client:
        client.post("/api/demo-login")
        user = app.state.service.store.one("SELECT * FROM users")
    reopened = create_app(tmp_path, demo=True)
    with browser(reopened) as client:
        assert client.post("/api/demo-login").status_code == 200
        assert reopened.state.service.store.one("SELECT * FROM users") == user


def test_demo_refuses_an_existing_unmarked_workspace(tmp_path):
    ordinary = create_app(tmp_path / "demo")
    with browser(ordinary) as client:
        client.post("/api/setup", json={"username": "Existing Owner", "password": "123456"})
        before = ordinary.state.service.store.one("SELECT * FROM users")
    with pytest.raises(ValueError, match="not a demo workspace"):
        create_app(tmp_path, demo=True)
    assert ordinary.state.service.store.one("SELECT * FROM users") == before
    assert not (tmp_path / "demo" / ".finance-flow-demo").exists()


def test_demo_entry_keeps_same_origin_and_session_boundaries(tmp_path):
    app = create_app(tmp_path, demo=True)
    with browser(app) as client:
        assert client.post("/api/demo-login", headers={"Origin": "https://other.invalid"}).status_code == 403
        client.headers.pop("X-Requested-With")
        assert client.post("/api/demo-login").status_code == 403
        assert client.get("/api/tasks").status_code == 401


def test_demo_workspace_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert workspace_directory() == tmp_path / "FinanceFlow"
    assert workspace_directory(demo=True) == tmp_path / "FinanceFlow" / "demo"
    assert workspace_directory(tmp_path / "custom", demo=True) == tmp_path / "custom" / "demo"
