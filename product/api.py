"""Authenticated loopback application. No legacy unauthenticated routes are mounted."""
from contextlib import asynccontextmanager
import hashlib
import hmac
import io
import json
import os
import re
from pathlib import Path
import secrets
import time

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pwdlib import PasswordHash
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from product import __version__
from product.service import FIELDS, MAX_BYTES, ProductService
from product.storage import encode, timestamp

HERE = Path(__file__).resolve().parent
PASSWORDS = PasswordHash.recommended()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Credentials(Input):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Username must contain at least 2 characters.")
        if not re.fullmatch(r"[A-Za-z0-9_.@ -]+", value):
            raise ValueError("Username may contain English letters, numbers, spaces, and . _ @ - only.")
        return value


class MappingRequest(Input):
    mapping: dict[str, str]


class ScanFolder(Input):
    folder: str = Field(min_length=1, max_length=4096)
    bi_folder: str | None = Field(default=None, min_length=1, max_length=4096)


class AssistantFolder(Input):
    folder: str = Field(min_length=1, max_length=4096)
    bi_folder: str | None = Field(default=None, min_length=1, max_length=4096)


class AssistantTurn(Input):
    instruction: str = Field(min_length=3, max_length=3000)
    retry_turn_id: int | None = Field(default=None, ge=1)


class CommandInput(Input):
    instruction: str = Field(min_length=3, max_length=3000)
    folder: str | None = Field(default=None, min_length=1, max_length=4096)
    bi_folder: str | None = Field(default=None, min_length=1, max_length=4096)


class BatchTable(Input):
    role: str = Field(pattern="^(source|reference|skip|unknown)$")
    reference_id: int | None = Field(default=None, ge=1)
    mapping: dict[str, str] | None = None


class CreateTask(Input):
    title: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=3, max_length=3000)
    source_id: str
    reference_id: str
    ai: bool = True


class Change(Input):
    issue_id: str
    mode: str = Field(pattern="^(reference|manual)$")
    value: str | None = Field(default=None, max_length=500)


class Review(Input):
    revision: int = Field(ge=1)
    evidence_digest: str = Field(min_length=64, max_length=64)
    changes: list[Change] = Field(min_length=1, max_length=200)
    reason: str = Field(default="", max_length=1500)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)


def data_directory():
    base = Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "FinanceFlow"


def create_app(directory=None, *, model=None):
    service = ProductService(Path(directory or data_directory()), model=model)
    login_failures = []

    @asynccontextmanager
    async def lifespan(_app):
        yield
        service.cancel_signal.set()
        service.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title="Finance Flow Local", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.service = service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if request.headers.get("x-requested-with") != "FinanceFlow" or (origin and origin != expected):
                return JSONResponse({"detail": "Cross-origin requests are not permitted."}, status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        })
        return response

    @app.exception_handler(ValueError)
    async def invalid_value(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(OSError)
    async def file_error(_request, _error):
        return JSONResponse({"detail": "Local storage is unavailable. Check free disk space and file permissions."}, status_code=503)

    def account(request: Request):
        token = request.cookies.get("finance_session", "")
        row = service.store.one(
            "SELECT users.username FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ) if token else None
        if not row:
            raise HTTPException(401, "Sign in to your local workspace.")
        return row["username"]

    def sign_in(username, response):
        token = secrets.token_urlsafe(32)
        with service.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,1,?)", (hashlib.sha256(token.encode()).hexdigest(), time.time() + 12 * 3600))
        response.set_cookie("finance_session", token, max_age=12 * 3600, httponly=True, samesite="strict", path="/")
        return {"username": username}

    @app.get("/api/health")
    def health():
        return {"product": "finance-flow-local", "version": __version__, "status": "ok"}

    @app.get("/api/session")
    def session(request: Request):
        setup = service.store.one("SELECT id FROM users WHERE id=1") is None
        try:
            username = account(request)
        except HTTPException:
            username = None
        return {"setup_required": setup, "username": username}

    @app.post("/api/setup")
    def setup(body: Credentials, response: Response):
        if len(body.password) < 6 or not body.username.strip():
            raise HTTPException(422, "Choose a username and a password of at least 6 characters.")
        with service.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT id FROM users WHERE id=1").fetchone():
                raise HTTPException(409, "Workspace is already configured. Sign in instead.")
            db.execute("INSERT INTO users VALUES(1,?,?,?)", (body.username.strip(), PASSWORDS.hash(body.password), timestamp()))
        return sign_in(body.username.strip(), response)

    @app.post("/api/login")
    def login(body: Credentials, response: Response):
        cutoff = time.time() - 60
        login_failures[:] = [value for value in login_failures if value > cutoff]
        if len(login_failures) >= 5:
            raise HTTPException(429, "Too many attempts. Wait one minute before trying again.")
        user = service.store.one("SELECT * FROM users WHERE id=1")
        valid = bool(user and hmac.compare_digest(body.username.strip(), user["username"]) and PASSWORDS.verify(body.password, user["password_hash"]))
        if not valid:
            login_failures.append(time.time())
            raise HTTPException(401, "Username or password is incorrect.")
        login_failures.clear()
        return sign_in(user["username"], response)

    @app.post("/api/logout")
    def logout(request: Request, response: Response, _actor=Depends(account)):
        token = request.cookies.get("finance_session", "")
        with service.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie("finance_session", path="/")
        return {"signed_out": True}

    @app.post("/api/password")
    def change_password(body: PasswordChange, response: Response, actor=Depends(account)):
        user = service.store.one("SELECT * FROM users WHERE id=1")
        if not PASSWORDS.verify(body.current_password, user["password_hash"]):
            raise HTTPException(401, "Current password is incorrect.")
        with service.store.connect() as db:
            db.execute("UPDATE users SET password_hash=? WHERE id=1", (PASSWORDS.hash(body.new_password),))
            db.execute("DELETE FROM sessions")
        return sign_in(actor, response)

    @app.get("/api/files")
    def files(_actor=Depends(account)):
        return {"files": [service.file_view(row["id"], preview=False) for row in service.store.all("SELECT id FROM files ORDER BY created_at DESC")]}

    @app.post("/api/batches/pick-folder")
    def pick_folder(_actor=Depends(account)):
        from product.folder_tables import choose_folder
        try:
            return {"folder": choose_folder()}
        except Exception as exc:
            raise HTTPException(503, "The folder dialog could not open. Paste the full folder path instead.") from exc

    @app.get("/api/assistant/chats")
    def assistant_chats(_actor=Depends(account)):
        return {"chats": service.assistant.list()}

    @app.post("/api/assistant/chats", status_code=201)
    def assistant_create(body: AssistantFolder, actor=Depends(account)):
        return service.assistant.create(body.folder, actor, bi_folder=body.bi_folder)

    @app.get("/api/assistant/chats/{chat_id}")
    def assistant_detail(chat_id: int, _actor=Depends(account)):
        return service.assistant.describe(chat_id)

    @app.post("/api/assistant/chats/{chat_id}/turns", status_code=202)
    def assistant_turn(chat_id: int, body: AssistantTurn, actor=Depends(account)):
        return service.assistant.start(chat_id, body.instruction.strip(), actor, retry_turn_id=body.retry_turn_id)

    @app.post("/api/assistant/turns/{turn_id}/cancel")
    def assistant_cancel(turn_id: int, _actor=Depends(account)):
        return service.assistant.cancel(turn_id)

    @app.get("/api/assistant/artifacts/{artifact_id}")
    def assistant_report(artifact_id: str, _actor=Depends(account)):
        path = service.assistant.artifact(artifact_id)
        return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/assistant/artifacts/{artifact_id}/export")
    def assistant_export(artifact_id: str, _actor=Depends(account)):
        from product.native_reports import save_report
        path = service.assistant.artifact(artifact_id)
        saved = save_report(path, path.name)
        if not saved["handled"]: saved["download_url"] = f"/api/assistant/artifacts/{artifact_id}"
        return saved

    @app.get("/api/commands")
    def commands(_actor=Depends(account)):
        return {"commands": service.commands.list()}

    @app.post("/api/commands/prepare")
    async def prepare_command(body: CommandInput, actor=Depends(account)):
        from product.model import ModelUnavailable
        try:
            return await run_in_threadpool(service.commands.prepare, body.instruction, body.folder, actor, body.bi_folder)
        except ModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.post("/api/commands/{command_id}/execute", status_code=202)
    def execute_command(command_id: str, actor=Depends(account)):
        return service.commands.execute(command_id, actor)

    @app.get("/api/batches")
    def batches(_actor=Depends(account)):
        return {"batches": service.batches.list(), "active_batch": service.batch_active}

    @app.post("/api/batches/scan", status_code=202)
    def scan_folder(body: ScanFolder, actor=Depends(account)):
        return service.batches.scan(body.folder, actor, bi_folder=body.bi_folder)

    @app.get("/api/batches/{batch_id}")
    def batch_details(batch_id: int, _actor=Depends(account)):
        return service.batches.describe(batch_id)

    @app.post("/api/batches/{batch_id}/tables/{entry_id}")
    def batch_table(batch_id: int, entry_id: int, body: BatchTable, _actor=Depends(account)):
        return service.batches.update(batch_id, entry_id, body.role, body.reference_id, body.mapping)

    @app.post("/api/batches/{batch_id}/run")
    def batch_run(batch_id: int, actor=Depends(account)):
        return service.batches.start(batch_id, actor)

    @app.post("/api/batches/{batch_id}/cancel")
    def batch_cancel(batch_id: int, _actor=Depends(account)):
        return service.batches.cancel(batch_id)

    @app.get("/api/batches/{batch_id}/report")
    def batch_excel(batch_id: int, _actor=Depends(account)):
        path = service.batches.report(batch_id)
        return FileResponse(path, filename=f"FinanceFlow-BATCH-{batch_id:05d}.xlsx",
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/batches/{batch_id}/export")
    def export_batch_report(batch_id: int, _actor=Depends(account)):
        from product.native_reports import save_report
        path = service.batches.report(batch_id)
        saved = save_report(path, f"FinanceFlow-BATCH-{batch_id:05d}.xlsx")
        if not saved["handled"]:
            saved["download_url"] = f"/api/batches/{batch_id}/report-file/{path.name}"
        return saved

    @app.get("/api/batches/{batch_id}/report-file/{filename}")
    def prepared_batch_report(batch_id: int, filename: str, _actor=Depends(account)):
        service.batches.batch(batch_id)
        if not re.fullmatch(rf"FinanceFlow-BATCH-{batch_id:05d}-[a-f0-9]{{10}}\.xlsx", filename):
            raise HTTPException(404, "Report file was not found.")
        path = service.path("exports/" + filename)
        if not path.is_file():
            raise HTTPException(404, "Report file was not found.")
        return FileResponse(path, filename=f"FinanceFlow-BATCH-{batch_id:05d}.xlsx",
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/files", status_code=201)
    async def upload(file: UploadFile = File(...), role: str = Form(...), _actor=Depends(account)):
        content = await file.read(MAX_BYTES + 1)
        return await run_in_threadpool(service.upload, file.filename, content, role)

    @app.post("/api/files/{file_id}/mapping")
    def mapping(file_id: str, body: MappingRequest, _actor=Depends(account)):
        return service.map_file(file_id, body.mapping)

    @app.get("/api/files/{file_id}")
    def file_details(file_id: str, _actor=Depends(account)):
        return service.file_view(file_id)

    @app.get("/api/examples/{kind}")
    def example(kind: str, _actor=Depends(account)):
        names = {"source": "public_orders_with_findings.csv", "reference": "public_reference.csv"}
        filename = names.get(kind)
        if not filename or not (HERE / "examples" / filename).is_file():
            raise HTTPException(404, "Public benchmark files are not installed. Use the field template or run the documented dataset preparation script.")
        return FileResponse(HERE / "examples" / filename, filename=filename)

    @app.get("/api/template")
    def template(_actor=Depends(account)):
        return Response("\ufeff" + ",".join(FIELDS) + "\r\n", media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="finance-flow-template.csv"'})

    @app.get("/api/tasks")
    def tasks(_actor=Depends(account)):
        return {"tasks": service.tasks(), "active_task": service.active}

    @app.post("/api/tasks", status_code=201)
    def create(body: CreateTask, _actor=Depends(account)):
        if not body.title.strip() or not body.instruction.strip():
            raise HTTPException(422, "Task title and instructions are required.")
        return service.create(body.title.strip(), body.instruction.strip(), body.source_id, body.reference_id, body.ai)

    @app.get("/api/tasks/{job_id}")
    def detail(job_id: int, batch_id: int | None = None, _actor=Depends(account)):
        return service.detail(job_id, batch_id=batch_id)

    @app.post("/api/tasks/{job_id}/plan")
    def plan(job_id: int, actor=Depends(account)):
        return service.schedule(job_id, "plan", actor)

    @app.post("/api/tasks/{job_id}/run")
    def run(job_id: int, actor=Depends(account)):
        return service.schedule(job_id, "run", actor)

    @app.post("/api/tasks/{job_id}/review")
    def review(job_id: int, body: Review, actor=Depends(account)):
        return service.review(job_id, body.revision, body.evidence_digest, [item.model_dump() for item in body.changes], body.reason, actor)

    @app.post("/api/tasks/{job_id}/cancel")
    def cancel(job_id: int, actor=Depends(account)):
        return service.cancel(job_id, actor)

    @app.get("/api/tasks/{job_id}/report")
    def report(job_id: int, _actor=Depends(account)):
        data = service.detail(job_id, full=True)
        data["events"] = service.store.all("SELECT * FROM events WHERE job_id=? ORDER BY id", (job_id,))
        data.update(product="Finance Flow", version=__version__, reference_source="User-imported BI export",
                    archive_destination="Local reconciliation archive", report_generated_at=timestamp(),
                    report_kind="final" if data["status"] == "completed" else "interim")
        return Response(encode(data), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="FF-{job_id:05d}-report.json"'})

    @app.get("/api/tasks/{job_id}/export")
    def export(job_id: int, _actor=Depends(account)):
        job, state = service.get_job(job_id)
        if job["status"] != "completed" or not state.get("export"):
            raise HTTPException(409, "A clean completed task is required for a reconciled CSV export.")
        return FileResponse(service.path(state["export"]), filename=f"FF-{job_id:05d}-reconciled.csv")

    @app.get("/api/archive")
    def archive(_actor=Depends(account)):
        return {"records": [dict(row, data=json.loads(row["payload_json"])) for row in service.store.all("SELECT * FROM archive ORDER BY created_at DESC")]}

    @app.get("/api/model")
    def model_status(_actor=Depends(account)):
        return service.model.status()

    @app.post("/api/backup")
    def backup(_actor=Depends(account)):
        path = service.backup()
        return FileResponse(path, filename=path.name)

    app.mount("/assets", StaticFiles(directory=HERE / "static"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(HERE / "static" / "index.html")

    return app
