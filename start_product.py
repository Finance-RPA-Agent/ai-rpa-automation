"""Launch the local desktop product or restore a backup into a new data directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import sqlite3
import stat
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def restore_backup(archive_path, target):
    if target.exists() and any(target.iterdir()):
        raise ValueError("Restore requires a new, empty data directory. Existing files will not be overwritten.")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if sum(item.file_size for item in entries) > 2 * 1024 ** 3:
            raise ValueError("Backup exceeds the 2 GB restore limit.")
        manifest = json.loads(archive.read("manifest.json"))
        expected = manifest.get("files", {})
        if manifest.get("version") != 1 or "finance-flow.sqlite" not in expected:
            raise ValueError("Unsupported or incomplete backup manifest.")
        if len({item.filename for item in entries}) != len(entries):
            raise ValueError("Backup contains duplicate paths.")
        actual = {item.filename for item in entries if item.filename != "manifest.json"}
        if actual != set(expected):
            raise ValueError("Backup entries do not match the manifest.")
        for item in entries:
            path = PurePosixPath(item.filename)
            if ("\\" in item.filename or ":" in item.filename or path.is_absolute() or ".." in path.parts
                    or stat.S_ISLNK(item.external_attr >> 16) or item.is_dir()):
                raise ValueError("Backup contains an unsafe path.")
            if item.filename != "manifest.json":
                if path.parts[0] not in ("files", "jobs", "exports", "finance-flow.sqlite"):
                    raise ValueError("Unexpected backup path.")
                if hashlib.sha256(archive.read(item)).hexdigest() != expected[item.filename]:
                    raise ValueError("Backup checksum verification failed.")
        target.mkdir(parents=True, exist_ok=True)
        for item in entries:
            if item.filename == "manifest.json":
                continue
            destination = target.joinpath(*PurePosixPath(item.filename).parts)
            if not destination.resolve().is_relative_to(target.resolve()):
                raise ValueError("Restore path escapes the destination.")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(item))
    with sqlite3.connect(target / "finance-flow.sqlite") as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Restored metadata database failed its integrity check.")
        db.execute("DELETE FROM sessions")
    print("Backup restored and previous sessions revoked:", target)


def main():
    parser = argparse.ArgumentParser(description="Finance Flow — fully local reconciliation")
    parser.add_argument("--browser", action="store_true", help="Use the default browser instead of the desktop window")
    parser.add_argument("--no-open", action="store_true", help="Run the local service without opening a window")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--restore", type=Path, help="Restore a verified backup into an empty --data-dir")
    options = parser.parse_args()
    from product.api import create_app, data_directory
    from product import __version__
    directory = (options.data_dir or data_directory()).resolve()
    if options.restore:
        if not options.data_dir:
            parser.error("--restore requires an explicit empty --data-dir.")
        restore_backup(options.restore, directory)
        return 0
    if not 1024 <= options.port <= 65535:
        parser.error("Port must be between 1024 and 65535.")
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "application.lock"
    lock = lock_path.open("a+b")
    # Reading an existing locked byte itself raises PermissionError on Windows.
    # Inspect file size instead; only the locking call determines ownership.
    if lock_path.stat().st_size == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Finance Flow is already using this data directory.")
        try:
            info = json.loads((directory / "instance.json").read_text())
            port = int(info["port"])
            if 1024 <= port <= 65535 and not options.no_open:
                webbrowser.open(f"http://127.0.0.1:{port}")
        except (OSError, ValueError, KeyError):
            pass
        lock.close()
        return 0
    try:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", options.port))
            except OSError:
                print(f"Port {options.port} is occupied. Use --port {options.port + 1}.")
                return 1
        url = f"http://127.0.0.1:{options.port}"
        (directory / "instance.json").write_text(json.dumps({"port": options.port, "pid": os.getpid()}))
        import uvicorn
        app = create_app(directory)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=options.port, log_level="warning"))
        print(f"Finance Flow {__version__}\nWorkspace: {directory}\nLocal address: {url}")
        if options.no_open:
            server.run()
        else:
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    raise RuntimeError("The local server could not start.")
                time.sleep(0.1)
            if not server.started:
                raise RuntimeError("The local server did not become ready.")
            try:
                if options.browser:
                    webbrowser.open(url)
                    print("Keep this terminal open. Press Ctrl+C to stop.")
                    thread.join()
                else:
                    import webview
                    # pywebview disables downloads by default. Enable the native
                    # Save dialog for reports, exports, public files and backups.
                    webview.settings["ALLOW_DOWNLOADS"] = True
                    webview.create_window("Finance Flow", url, width=1400, height=900, min_size=(960, 680))
                    webview.start(gui="edgechromium", private_mode=False, storage_path=str(directory / "webview"))
            finally:
                app.state.service.cancel_signal.set()
                server.should_exit = True
                # Retain the workspace lock until the worker and lifespan have
                # actually stopped, including any bounded local-model request.
                thread.join()
        return 0
    finally:
        lock.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print("Finance Flow could not start:", error)
        print("See product/README.md for setup, model and WebView2 troubleshooting.")
        raise SystemExit(1)
