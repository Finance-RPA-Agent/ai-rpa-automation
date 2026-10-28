"""Natural-language intake; only the fixed local reconciliation workflow can run."""
import json
from pathlib import Path
import secrets
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from product.model import ModelUnavailable, MODEL
from product.input_folders import select_inputs
from product.storage import encode, timestamp


class Interpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    intent: Literal["reconcile_folder", "clarify", "unsupported"]
    folders: list[str] = Field(max_length=4)
    message: str = Field(min_length=1, max_length=900)


STEPS = ["Scan CSV and Excel tables", "Match source tables to imported references",
         "Reconcile and archive matching rows", "Keep exceptions for human review",
         "Generate an Excel report"]


class Commands:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def prepare(self, instruction, folder, actor, bi_folder=None):
        try:
            payload = self.service.model.interpret_command(instruction, Interpretation.model_json_schema())
            parsed = Interpretation.model_validate(payload)
        except ModelUnavailable:
            raise
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise ModelUnavailable("The local model returned an invalid command. No files were processed. Try again.") from exc
        if parsed.intent != "reconcile_folder":
            message = parsed.message
            if any("\u3400" <= c <= "\u9fff" for c in message):
                message = "Describe a folder reconciliation task. Payments, file deletion and custom data transformations are not supported."
            return {"status": "needs_input", "message": message}
        if folder:
            chosen = folder.strip()
            if parsed.folders and any(Path(path) not in {Path(chosen), *([Path(bi_folder)] if bi_folder else [])} for path in parsed.folders):
                return {"status": "needs_input", "message": "The selected folder differs from the folder in your request. Use the same folder in both."}
        elif len(parsed.folders) == 1:
            chosen = parsed.folders[0]
            # A model may extract a path; it may never invent or expand one.
            if not chosen or chosen not in instruction:
                raise ValueError("The proposed folder was not present in your request. Select the folder explicitly.")
        else:
            return {"status": "needs_input", "message": "Choose one input folder containing both source files and reference exports."}
        selected = Path(chosen)
        if not selected.is_absolute() or not selected.is_dir():
            raise ValueError("Choose an existing absolute folder path.")
        if str(selected).startswith(("\\\\", "//")):
            raise ValueError("Choose a local folder on this computer.")
        selected = selected.resolve()
        if selected == self.store.root or selected.is_relative_to(self.store.root):
            raise ValueError("Choose an input folder outside the application data directory.")
        selected, bi = select_inputs(str(selected), bi_folder, self.store.root)
        command_id = secrets.token_hex(16)
        plan = {"summary": "Reconcile the selected folder, archive matching rows, keep exceptions for review and generate an Excel report.",
                "steps": STEPS, "model": MODEL}
        with self.store.connect() as db:
            db.execute("INSERT INTO commands(id,instruction,folder,plan_json,actor,created_at,bi_folder) VALUES(?,?,?,?,?,?,?)",
                       (command_id, instruction, str(selected), encode(plan), actor, timestamp(), str(bi) if bi else None))
        return self.describe(command_id)

    def describe(self, command_id):
        row = self.store.one("SELECT * FROM commands WHERE id=?", (command_id,))
        if not row:
            raise HTTPException(404, "Command was not found.")
        return {"id": row["id"], "instruction": row["instruction"], "folder": row["folder"], "bi_folder": row["bi_folder"],
                "plan": json.loads(row["plan_json"]), "actor": row["actor"], "created_at": row["created_at"],
                "batch_id": row["batch_id"], "status": self.service.batches.describe(row["batch_id"])["status"] if row["batch_id"] else "prepared"}

    def list(self):
        return [self.describe(row["id"]) for row in self.store.all("SELECT id FROM commands ORDER BY created_at DESC,rowid DESC LIMIT 20")]

    def execute(self, command_id, actor):
        # One lock covers idempotency, batch reservation and the stored association.
        with self.service.guard:
            command = self.describe(command_id)
            if command["batch_id"]:
                return self.service.batches.describe(command["batch_id"])
            if command["actor"] != actor:
                raise HTTPException(403, "This command belongs to another account.")
            return self.service.batches.scan(command["folder"], actor, command_id=command_id, bi_folder=command["bi_folder"])
