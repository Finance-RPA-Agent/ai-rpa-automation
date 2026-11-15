"""Start an installed local Ollama server, without downloading or loading models."""
import os
from pathlib import Path
import shutil
import subprocess
import time

from product.model import MODEL, OllamaProvider


def find_ollama():
    executable = shutil.which("ollama")
    if executable:
        return executable
    # A Windows app launched from Explorer can inherit an older PATH.
    for variable, suffix in (("LOCALAPPDATA", "Programs/Ollama/ollama.exe"),
                             ("ProgramFiles", "Ollama/ollama.exe")):
        base = os.environ.get(variable)
        if base:
            candidate = Path(base) / suffix
            if candidate.is_file():
                return str(candidate)
    return None


def _status():
    try:
        return OllamaProvider().status()
    except (AttributeError, KeyError, TypeError, ValueError, OSError):
        # A different application on this port must not block the desktop UI.
        return {"available": False, "installed": False}


def _ready(status, *, started):
    return {"available": True, "installed": status["installed"], "started": started,
            "message": ("Local Ollama is running; the model is installed. First inference may take longer."
                        if status["installed"] else f"Local Ollama is running. Install the model once: ollama pull {MODEL}")}


def ensure_ollama(*, wait_seconds=12):
    """Reuse a running server or launch one hidden, with a bounded readiness wait.

    The shared model service is intentionally left running when Finance Flow exits.
    Readiness here checks /api/tags only; it does not perform inference.
    """
    status = _status()
    if status["available"]:
        return _ready(status, started=False)
    executable = find_ollama()
    if not executable:
        return {"available": False, "installed": False, "started": False,
                "message": f"Ollama is not installed. Install it, then run: ollama pull {MODEL}. File-based reconciliation remains available."}
    environment = os.environ.copy()
    environment["OLLAMA_HOST"] = "127.0.0.1:11434"
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    try:
        process = subprocess.Popen([executable, "serve"], env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
    except OSError as exc:
        return {"available": False, "installed": False, "started": False,
                "message": f"Ollama could not be started: {exc}. File-based reconciliation remains available."}
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status = _status()
        if status["available"]:
            return _ready(status, started=True)
        if process.poll() is not None:
            return {"available": False, "installed": False, "started": True,
                    "message": "Ollama exited before becoming available. Check the local installation and port 11434. File-based reconciliation remains available."}
        time.sleep(0.25)
    return {"available": False, "installed": False, "started": True,
            "message": "Ollama is still starting. Use Settings > Refresh connection before retrying. File-based reconciliation remains available."}
