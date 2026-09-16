from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "AI-RPA Backend is running"
    }


def test_system_status():
    response = client.get("/system/status")

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["status"] == "online"

    assert "statistics" in data
    assert "connectors" in data

    assert data["connectors"]["excel"] == "available"
    assert data["connectors"]["bi"] == "available"
    assert (
        data["connectors"]["office_automation"]
        == "available"
    )


def test_users_list():
    response = client.get("/users/")

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_invalid_task():
    response = client.post(
        "/agent/run/999999"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


def test_invalid_user():
    response = client.get(
        "/users/999999"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"