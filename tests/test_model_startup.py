"""Local model startup without downloads, inference or touching a user's process."""
from unittest.mock import Mock

import httpx
import pytest

from product import model_startup as startup
from product.model import MODEL, OllamaProvider


def test_running_service_is_reused_without_starting_a_process(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": True, "installed": True})
    spawn = Mock(side_effect=AssertionError("Must reuse the existing server"))
    monkeypatch.setattr(startup.subprocess, "Popen", spawn)
    result = startup.ensure_ollama()
    assert result["available"] and result["installed"] and not result["started"]
    spawn.assert_not_called()


def test_missing_ollama_does_not_block_fixed_rule_workflows(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": False})
    monkeypatch.setattr(startup, "find_ollama", lambda: None)
    result = startup.ensure_ollama()
    assert not result["available"] and not result["started"]
    assert "File-based reconciliation remains available" in result["message"]


def test_windows_install_path_is_found_without_path_refresh(tmp_path, monkeypatch):
    executable = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(startup.shutil, "which", lambda _: None)
    assert startup.find_ollama() == str(executable)


def test_starts_hidden_loopback_server_then_observes_installed_model(monkeypatch):
    statuses = iter([{"available": False}, {"available": True, "installed": True}])
    monkeypatch.setattr(startup, "_status", lambda: next(statuses))
    monkeypatch.setattr(startup, "find_ollama", lambda: "C:/Ollama/ollama.exe")
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    spawn = Mock()
    monkeypatch.setattr(startup.subprocess, "Popen", spawn)
    result = startup.ensure_ollama()
    args, options = spawn.call_args
    assert args == (["C:/Ollama/ollama.exe", "serve"],)
    assert options["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert options["stdin"] == options["stdout"] == options["stderr"] == startup.subprocess.DEVNULL
    if startup.os.name == "nt": assert options["creationflags"] & startup.subprocess.CREATE_NO_WINDOW
    else: assert options["start_new_session"] is True
    assert startup.os.environ["OLLAMA_HOST"] == "0.0.0.0:11434"
    assert result["available"] and result["started"]
    spawn.return_value.terminate.assert_not_called()


def test_installed_tag_check_never_downloads_or_runs_inference(monkeypatch):
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"models": [{"name": MODEL}]})
    provider = OllamaProvider(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(startup, "OllamaProvider", lambda: provider)
    result = startup.ensure_ollama()
    assert result["installed"] and calls == [("GET", "/api/tags")]


def test_missing_model_reports_install_command_without_downloading(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": True, "installed": False})
    spawn = Mock(side_effect=AssertionError("Running service must not be replaced"))
    monkeypatch.setattr(startup.subprocess, "Popen", spawn)
    result = startup.ensure_ollama()
    assert result["available"] and not result["installed"]
    assert "ollama pull " + MODEL in result["message"]
    spawn.assert_not_called()


def test_launch_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": False})
    monkeypatch.setattr(startup, "find_ollama", lambda: "ollama")
    monkeypatch.setattr(startup.subprocess, "Popen", Mock(side_effect=OSError("Synthetic failure")))
    result = startup.ensure_ollama()
    assert not result["available"] and "Synthetic failure" in result["message"]


def test_readiness_wait_is_bounded_and_does_not_kill_service(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": False})
    monkeypatch.setattr(startup, "find_ollama", lambda: "ollama")
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(startup.subprocess, "Popen", Mock(return_value=process))
    clock = iter([0, 0.1, 0.6])
    monkeypatch.setattr(startup.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(startup.time, "sleep", lambda _: None)
    result = startup.ensure_ollama(wait_seconds=0.5)
    assert not result["available"] and result["started"]
    assert "still starting" in result["message"]
    process.terminate.assert_not_called()


def test_exited_process_reports_failure(monkeypatch):
    monkeypatch.setattr(startup, "_status", lambda: {"available": False})
    monkeypatch.setattr(startup, "find_ollama", lambda: "ollama")
    process = Mock()
    process.poll.return_value = 1
    monkeypatch.setattr(startup.subprocess, "Popen", Mock(return_value=process))
    result = startup.ensure_ollama()
    assert not result["available"] and "exited" in result["message"]


@pytest.mark.parametrize("skip", [False, True])
def test_desktop_launcher_checks_ollama_unless_explicitly_disabled(tmp_path, monkeypatch, skip):
    import sys
    from types import SimpleNamespace
    import product.api
    import start_product
    calls = []
    monkeypatch.setattr(startup, "ensure_ollama", lambda: calls.append("ollama") or {"message": "Synthetic startup"})
    monkeypatch.setattr(product.api, "create_app", lambda *args, **kwargs: calls.append("app") or object())
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(
        Config=lambda *args, **kwargs: None,
        Server=lambda _: SimpleNamespace(run=lambda: calls.append("server"))))
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): pass
    monkeypatch.setattr(start_product.socket, "socket", lambda: Probe())
    args = ["start_product.py", "--demo", "--no-open", "--data-dir", str(tmp_path), "--port", "8897"]
    if skip: args.append("--no-auto-ollama")
    monkeypatch.setattr(sys, "argv", args)
    assert start_product.main() == 0
    assert calls == (["app", "server"] if skip else ["ollama", "app", "server"])
