"""R4B read-only model checks and manual retry against the real ASGI app."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from product.api import create_app
from product.issue_explanation import AdviceFailure
from product.model import MODEL, OllamaProvider
from test_finance_r3_http import durable, local, request_body, route, task


@pytest.mark.parametrize("condition", ["installed", "missing", "unreachable"])
def test_connection_check(tmp_path, condition):
    calls = []

    def tags(request):
        calls.append((request.method, request.url.path))
        assert calls == [("GET", "/api/tags")]
        if condition == "unreachable":
            raise httpx.ConnectError("Synthetic outage", request=request)
        models = [{"name": MODEL}] if condition == "installed" else []
        return httpx.Response(200, json={"models": models})

    provider = OllamaProvider(transport=httpx.MockTransport(tags))
    app = create_app(tmp_path / "status", model=provider)
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-Requested-With": "FinanceFlow"}) as client:
        assert client.post("/api/setup", json={"username": "Synthetic", "password": "r4b-test-only"}).status_code == 200
        result = client.get("/api/model")
    assert result.status_code == 200 and calls == [("GET", "/api/tags")]
    data = result.json()
    assert data["available"] is (condition != "unreachable")
    assert data["installed"] is (condition == "installed")
    if condition == "installed":
        assert "ready for local inference" not in data["message"].lower()
        assert "first request" in data["message"].lower()
    print(json.dumps({"probe": calls, "condition": condition, "status": data}))


def fingerprint(service):
    snapshot = durable(service)
    return {k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
            for k, v in snapshot.items()}


@pytest.mark.parametrize("outcome", ["model_timeout", "model_busy"])
def test_manual_retry_is_read_only(local, outcome):
    client, service, provider, _ = local
    detail = task(local)
    initial = fingerprint(service)
    provider.block = True
    provider.output = AdviceFailure(outcome)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(client.post, route(detail), json=request_body(detail))
        try:
            assert provider.entered.wait(5)
            assert fingerprint(service) == initial
        finally:
            provider.release.set()
        first = pending.result(timeout=10)
    assert first.status_code == 200
    fallback = first.json()
    assert (fallback["mode"], fallback["status"], fallback["model"]) == ("rules_only", outcome, None)
    assert fingerprint(service) == initial

    fresh = client.get(f"/api/tasks/{detail['id']}")
    assert fresh.status_code == 200 and request_body(fresh.json()) == request_body(detail)
    assert len(provider.calls) == 1 and fingerprint(service) == initial
    provider.block = False
    provider.output = None
    second = client.post(route(fresh.json()), json=request_body(fresh.json()))
    assert second.status_code == 200 and len(provider.calls) == 2
    advice = second.json()
    assert advice["mode"] == "local_model" and advice["status"] == "advice_ready"
    assert advice["facts"] == fallback["facts"]
    assert advice["advisory_only"] and all(s["requires_human_decision"] for s in advice["suggestions"])
    final = fingerprint(service)
    assert final == initial
    print(json.dumps({"outcome": outcome, "provider_calls": len(provider.calls), "revision": detail["revision"],
                      "read_only_before": initial, "read_only_after": final}, sort_keys=True))
