"""Folder snapshots, conservative pairing and exception-only reconciliation jobs."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import secrets

from fastapi import HTTPException

from backend.app.tools import read_data_file, validate_data
from backend.app.tools.rules import normalise_identifier
from product.folder_tables import (
    MAX_BATCH_BYTES, MAX_BATCH_ROWS, MAX_FILES, MAX_TABLES,
    canonical_bytes, infer_role, read_tables,
)
from product.input_folders import select_inputs
from product.service import Cancelled, FIELDS, MAX_BYTES, result
from product.storage import digest, encode, timestamp


class FolderBatches:
    def __init__(self, service):
        self.service = service
        self.store = service.store

    def batch(self, batch_id):
        row = self.store.one("SELECT * FROM batches WHERE id=?", (batch_id,))
        if not row:
            raise HTTPException(404, "Folder batch was not found.")
        return row

    def entries(self, batch_id):
        return [dict(row, state=json.loads(row["state_json"])) for row in self.store.all(
            "SELECT * FROM batch_entries WHERE batch_id=? ORDER BY id", (batch_id,))]

    def save_entry(self, entry):
        with self.store.connect() as db:
            db.execute("UPDATE batch_entries SET role=?,reference_id=?,state_json=? WHERE id=?",
                       (entry["role"], entry["reference_id"], encode(entry["state"]), entry["id"]))

    def set_status(self, batch_id, status, error=None):
        with self.store.connect() as db:
            db.execute("UPDATE batches SET status=?,error=?,updated_at=? WHERE id=?",
                       (status, error, timestamp(), batch_id))

    def idle(self):
        if self.service.active is not None or self.service.batch_active is not None or self.service.assistant_active is not None:
            raise HTTPException(409, "Wait for the active operation to finish.")

    def scan(self, folder, actor, *, command_id=None, bi_folder=None):
        selected, bi = select_inputs(folder, bi_folder, self.store.root)
        with self.service.guard:
            self.idle()
            with self.store.connect() as db:
                cursor = db.execute("INSERT INTO batches(folder,status,actor,created_at,updated_at,bi_folder) VALUES(?,?,?,?,?,?)",
                                    (str(selected), "scanning", actor, timestamp(), timestamp(), str(bi) if bi else None))
                batch_id = cursor.lastrowid
                if command_id:
                    changed = db.execute("UPDATE commands SET batch_id=? WHERE id=? AND batch_id IS NULL", (batch_id, command_id))
                    if changed.rowcount != 1:
                        raise HTTPException(409, "This command has already started or no longer exists.")
            self.service.batch_active = batch_id
            self.service.cancel_signal.clear()
            self.service.future = self.service.executor.submit(self._work, batch_id, "auto" if command_id else "scan", actor)
        return self.describe(batch_id)

    def run_for_assistant(self, folder, bi_folder, actor, turn_id, *, expected, attached, existing_id=None):
        """Run on the already reserved assistant worker; never queue behind ourselves."""
        selected, bi = select_inputs(folder, bi_folder, self.store.root)
        if not bi: raise ValueError("Select a BI system folder for financial reconciliation.")
        with self.service.guard:
            if self.service.assistant_active != turn_id or self.service.active is not None or self.service.batch_active is not None:
                raise HTTPException(409, "The assistant must own the idle financial worker.")
            operation = "auto"
            if existing_id:
                batch = self.batch(existing_id)
                if batch["actor"] != actor or batch["folder"] != str(selected) or batch["bi_folder"] != str(bi):
                    raise HTTPException(409, "The retained batch does not match this request's owner and folders.")
                if batch["status"] in ("completed", "needs_review", "cancelled"):
                    return self.describe(existing_id)
                if batch["scan_complete"]: operation = "run"
                else: existing_id = None
            if not existing_id:
                with self.store.connect() as db:
                    cursor = db.execute("INSERT INTO batches(folder,bi_folder,status,actor,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (str(selected), str(bi), "scanning", actor, timestamp(), timestamp()))
                    existing_id = cursor.lastrowid
            self.service.batch_active = existing_id
            self.set_status(existing_id, "scanning" if operation == "auto" else "running")
        try:
            attached(existing_id)
            self._work(existing_id, operation, actor, expected=expected)
            return self.describe(existing_id)
        finally:
            with self.service.guard: self.service.batch_active = None

    def _work(self, batch_id, operation, actor, *, expected=None):
        try:
            if operation in ("scan", "auto"):
                self._scan(batch_id)
                if expected is not None:
                    captured = {(entry["state"].get("input_group", "input"), entry["state"].get("origin_relative", entry["relative_path"])): entry["state"]["file_sha256"] for entry in self.entries(batch_id) if entry["state"].get("file_sha256")}
                    if captured != expected: raise ValueError("The source or BI data changed during handoff. Start a new conversation before processing it.")
                with self.store.connect() as db:
                    db.execute("UPDATE batches SET scan_complete=1 WHERE id=?", (batch_id,))
                self.set_status(batch_id, "scanned")
            if operation in ("run", "auto"):
                self.cancelled()
                self.set_status(batch_id, "running")
                self._run(batch_id, actor)
                self.set_status(batch_id, "needs_review")
                view = self.describe(batch_id)
                self.set_status(batch_id, view["status"])
        except Cancelled:
            self.set_status(batch_id, "cancelled", "Stopped at a safe boundary. Existing receipts were retained.")
        except Exception as exc:
            self.set_status(batch_id, "failed", str(exc)[:1500])
        finally:
            self.service.active = None
            if operation in ("run", "auto"):
                try:
                    self.report(batch_id, internal=True)
                except Exception as exc:
                    batch = self.batch(batch_id)
                    with self.store.connect() as db:
                        db.execute("UPDATE batches SET error=? WHERE id=?",
                                   ((batch.get("error") or "") + f" Report generation failed: {exc}", batch_id))
            with self.service.guard:
                self.service.batch_active = None

    def cancelled(self):
        if self.service.cancel_signal.is_set():
            raise Cancelled()

    def _files(self, folder):
        excluded = {".git", ".venv", "node_modules", "__pycache__", "runtime", "backups", "exports"}
        def unreadable(error):
            raise OSError(f"An input folder could not be read: {error.filename}. Check its permissions and scan again.") from error
        for base, directories, files in os.walk(folder, followlinks=False, onerror=unreadable):
            root = Path(base)
            directories[:] = sorted(name for name in directories
                                    if name.lower() not in excluded and not name.startswith(".")
                                    and not (root / name).is_symlink()
                                    and not (root / name).is_junction()
                                    and not (root / name).resolve().is_relative_to(self.store.root))
            if len(root.relative_to(folder).parts) >= 5:
                directories[:] = []
            for name in sorted(files):
                path = root / name
                if path.suffix.lower() not in (".csv", ".xlsx") or name.startswith(("~$", ".", "FinanceFlow-BATCH-")):
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(folder):
                    continue
                yield path

    def _scan(self, batch_id):
        batch = self.batch(batch_id)
        folder = Path(batch["folder"])
        roots = [("input", folder)] + ([("bi", Path(batch["bi_folder"]))] if batch["bi_folder"] else [])
        counts = {"input": 0, "bi": 0}
        snapshot_dir = self.store.root / "files" / f"batch-{batch_id}"
        snapshot_dir.mkdir(exist_ok=True)
        count = total_bytes = total_rows = tables = 0
        for group, origin_root, original in ((group, base, file) for group, base in roots for file in self._files(base)):
            self.cancelled()
            count += 1
            if count > MAX_FILES:
                raise ValueError("The folder contains more than 100 supported files. Choose a smaller folder.")
            counts[group] += 1
            origin_relative = original.relative_to(origin_root).as_posix()
            relative = (("Input/" if group == "input" else "BI system/") + origin_relative) if batch["bi_folder"] else origin_relative
            provenance = {"input_group": group, "origin_relative": origin_relative} if batch["bi_folder"] else {}
            snapshot = snapshot_dir / (secrets.token_hex(12) + original.suffix.lower())
            try:
                with original.open("rb") as handle:
                    content = handle.read(MAX_BYTES + 1)
                total_bytes += len(content)
                if total_bytes > MAX_BATCH_BYTES:
                    raise ValueError("The batch exceeds the 100 MB input budget. Choose a smaller folder.")
                if len(content) > MAX_BYTES:
                    self._add_entry(batch_id, relative, "", {"fatal": ["File exceeds 10 MB."], "row_count": 0, **provenance})
                    continue
                snapshot.write_bytes(content)
                sha = hashlib.sha256(content).hexdigest()
                if digest(original) != sha:
                    raise ValueError("The file changed while it was being captured. Scan it again.")
                for sheet, table, error in read_tables(snapshot):
                    self.cancelled()
                    tables += 1
                    if tables > MAX_TABLES:
                        raise ValueError("The batch exceeds 200 tables.")
                    state = {**provenance, "snapshot": str(snapshot.relative_to(self.store.root)), "file_sha256": sha,
                             "fatal": [error] if error else [], "row_count": 0, "processed": False}
                    if table:
                        total_rows += len(table["rows"])
                        if total_rows > MAX_BATCH_ROWS:
                            raise ValueError("The batch exceeds 50,000 records. Choose a smaller folder.")
                        raw = snapshot_dir / (secrets.token_hex(10) + ".json")
                        raw.write_text(encode(table), encoding="utf-8")
                        state.update(raw_table=str(raw.relative_to(self.store.root)), columns=table["columns"],
                                     raw_table_sha256=digest(raw),
                                     mapping=table["mapping"], origin_rows=table["origin_rows"],
                                     currencies=table["currencies"], row_count=len(table["rows"]))
                        self._canonical(state, table)
                    self._add_entry(batch_id, relative, sheet, state)
            except (OSError, ValueError) as exc:
                if "budget" in str(exc) or "exceeds 50,000" in str(exc) or "exceeds 200" in str(exc):
                    raise
                self._add_entry(batch_id, relative, "", {"fatal": [str(exc)], "row_count": 0, **provenance})
        if not count:
            raise ValueError("No .xlsx or .csv input files were found in the selected folder.")
        if batch["bi_folder"] and (not counts["input"] or not counts["bi"]):
            raise ValueError("Both the input folder and BI system folder must contain CSV or Excel files.")
        self.pair(batch_id)

    def _add_entry(self, batch_id, relative, sheet, state):
        with self.store.connect() as db:
            db.execute("INSERT INTO batch_entries(batch_id,relative_path,sheet,role,state_json) VALUES(?,?,?,?,?)",
                       (batch_id, relative, sheet, {"input": "source", "bi": "reference"}.get(state.get("input_group"), infer_role(relative, sheet)), encode(state)))

    def _canonical(self, state, table):
        mapping = state["mapping"]
        target = self.service.path(state["raw_table"]).with_suffix(".csv")
        target.write_bytes(canonical_bytes(table, mapping))
        state["canonical"] = str(target.relative_to(self.store.root))
        state["canonical_sha256"] = digest(target)
        records = result(read_data_file(str(target), settings=self.service.settings))["records"]
        state["row_keys"] = [[normalise_identifier(r["data"].get("supplier_id")), normalise_identifier(r["data"].get("order_id"))] for r in records]
        state["validation_issues"] = result(validate_data(str(target), settings=self.service.settings))["issues"]

    @staticmethod
    def base_problems(entry):
        state = entry["state"]
        if entry["role"] == "skip":
            return []
        problems = list(state.get("fatal", []))
        if entry["role"] == "unknown":
            problems.append("Choose Source, Reference or Ignore for this table.")
        missing = [field for field in FIELDS if field not in state.get("mapping", {})]
        if missing:
            problems.append("Column mapping required: " + ", ".join(missing))
        if len(state.get("currencies", [])) > 1:
            problems.append("Multiple currencies were detected. Split this table by currency before processing.")
        if entry["role"] == "reference" and state.get("validation_issues"):
            problems.append("Reference data is invalid or duplicated: " + state["validation_issues"][0]["message"])
        return problems

    def pair(self, batch_id):
        entries = self.entries(batch_id)
        existing_jobs = self._jobs(batch_id)
        executed = {job["entry_id"] for job in existing_jobs}
        executed_origins = defaultdict(set)
        for job in existing_jobs:
            executed_origins[job["entry_id"]].update(job["origins"])
        source_entries = {entry["id"]: entry for entry in entries}
        references = [entry for entry in entries if entry["role"] == "reference" and not self.base_problems(entry)]
        keys = {entry["id"]: {tuple(key) for key in entry["state"].get("row_keys", []) if all(key)} for entry in entries}
        occurrences = defaultdict(list)
        for entry in entries:
            if entry["role"] == "source":
                for index, key in enumerate(entry["state"].get("row_keys", [])):
                    if all(key):
                        occurrences[tuple(key)].append((entry["id"], index))
        duplicates = defaultdict(list)
        for key, rows in occurrences.items():
            if len({entry_id for entry_id, _ in rows}) > 1:
                for entry_id, index in rows:
                    origin = source_entries[entry_id]["state"]["origin_rows"][index]
                    if origin not in executed_origins[entry_id]:
                        duplicates[entry_id].append(index)
        by_id = {entry["id"]: entry for entry in entries}
        for entry in entries:
            state = entry["state"]
            state["cross_duplicate_indexes"] = sorted(set(duplicates[entry["id"]]))
            state["pair_problem"] = None
            state["candidates"] = [ref["id"] for ref in references]
            if entry["role"] != "source":
                entry["reference_id"] = None
                self.save_entry(entry)
                continue
            if not state.get("manual_reference") and entry["id"] not in executed:
                scores = [(len(keys[entry["id"]] & keys[ref["id"]]), ref["id"]) for ref in references]
                highest = max((score for score, _ in scores), default=0)
                best = [ref_id for score, ref_id in scores if score == highest and score > 0]
                entry["reference_id"] = best[0] if len(best) == 1 else references[0]["id"] if len(references) == 1 else None
            reference = by_id.get(entry["reference_id"])
            if not reference or reference not in references:
                state["pair_problem"] = "No unique valid reference was found. Select a reference explicitly."
                entry["reference_id"] = None
            elif state.get("currencies") and reference["state"].get("currencies") and state["currencies"] != reference["state"]["currencies"]:
                state["pair_problem"] = "Source and reference currencies differ. Currency conversion is not supported."
            self.save_entry(entry)

    def update(self, batch_id, entry_id, role, reference_id=None, mapping=None):
        with self.service.guard:
            self.idle()
            batch = self.batch(batch_id)
            if not batch["scan_complete"]:
                raise HTTPException(409, "This folder scan did not finish. Scan a new batch before configuring tables.")
            if batch["status"] == "cancelled":
                raise HTTPException(409, "Cancelled batches are read-only. Scan a new batch.")
            entry = next((e for e in self.entries(batch_id) if e["id"] == entry_id), None)
            if not entry:
                raise HTTPException(404, "Table was not found in this batch.")
            if self.store.one("SELECT batch_jobs.job_id FROM batch_jobs JOIN batch_entries source ON source.id=batch_jobs.entry_id "
                              "WHERE batch_jobs.batch_id=? AND (batch_jobs.entry_id=? OR source.reference_id=?) LIMIT 1",
                              (batch_id, entry_id, entry_id)):
                raise HTTPException(409, "This table already has execution evidence. Correct its input files and scan a new batch.")
            if role not in ("source", "reference", "skip", "unknown"):
                raise ValueError("Choose Source, Reference or Ignore.")
            if batch["bi_folder"]:
                expected = "reference" if entry["state"].get("input_group") == "bi" else "source"
                if role not in (expected, "skip"):
                    raise ValueError("Table roles are fixed by the selected input and BI folders. Choose the original role or Ignore.")
            entry["role"] = role
            if mapping is not None:
                columns = entry["state"].get("columns", [])
                if set(mapping) != set(FIELDS) or len(set(mapping.values())) != len(FIELDS) or any(c not in columns for c in mapping.values()):
                    raise ValueError("Map all seven fields to different existing columns.")
                if not entry["state"].get("raw_table"):
                    raise ValueError("This table could not be read. Correct the input file and scan again.")
                self._verify(batch, entry)
                if digest(self.service.path(entry["state"]["raw_table"])) != entry["state"]["raw_table_sha256"]:
                    raise ValueError("The captured raw table changed. Scan a new batch.")
                entry["state"]["mapping"] = mapping
                raw = json.loads(self.service.path(entry["state"]["raw_table"]).read_text(encoding="utf-8"))
                self._canonical(entry["state"], raw)
            entry["reference_id"] = reference_id
            entry["state"]["manual_reference"] = reference_id is not None
            self.save_entry(entry)
            self.pair(batch_id)
            return self.describe(batch_id)

    def _jobs(self, batch_id):
        return [dict(row, origins=json.loads(row["rows_json"])) for row in self.store.all(
            "SELECT batch_jobs.*,jobs.status AS job_status FROM batch_jobs JOIN jobs ON jobs.id=batch_jobs.job_id WHERE batch_id=? ORDER BY entry_id,kind", (batch_id,))]

    def _ready(self, entry):
        return entry["role"] == "source" and not self.base_problems(entry) and not entry["state"].get("pair_problem") and entry["reference_id"] is not None

    def start(self, batch_id, actor):
        with self.service.guard:
            self.idle()
            batch = self.batch(batch_id)
            if not batch["scan_complete"]:
                raise HTTPException(409, "This folder scan did not finish. Scan a new batch before execution.")
            if batch["status"] not in ("scanned", "needs_review", "failed"):
                raise HTTPException(409, "This batch cannot be started in its current state.")
            if not self.describe(batch_id)["runnable_tables"]:
                raise HTTPException(409, "No unprocessed ready tables remain. Resolve table setup or review the existing exception tasks.")
            self.service.batch_active = batch_id
            self.service.cancel_signal.clear()
            self.set_status(batch_id, "running")
            self.service.future = self.service.executor.submit(self._work, batch_id, "run", actor)
        return self.describe(batch_id)

    def cancel(self, batch_id):
        with self.service.guard:
            batch = self.batch(batch_id)
            if batch["status"] not in ("scanning", "running") or self.service.batch_active != batch_id:
                raise HTTPException(409, "Only an active batch can be cancelled.")
            self.service.cancel_signal.set()
        return self.describe(batch_id)

    def _verify(self, batch, entry):
        state = entry["state"]
        root = Path(batch["bi_folder"] if state.get("input_group") == "bi" else batch["folder"])
        original = root / state.get("origin_relative", entry["relative_path"])
        if not original.resolve().is_relative_to(root.resolve()) or original.is_symlink():
            raise ValueError("An input path is no longer inside the selected folder.")
        if digest(original) != state["file_sha256"] or digest(self.service.path(state["snapshot"])) != state["file_sha256"]:
            raise ValueError("An input changed after the scan. Scan a new batch before processing it.")
        if digest(self.service.path(state["canonical"])) != state["canonical_sha256"]:
            raise ValueError("The captured table changed. Scan a new batch.")

    def _run(self, batch_id, actor):
        batch = self.batch(batch_id)
        entries = self.entries(batch_id)
        by_id = {entry["id"]: entry for entry in entries}
        jobs = self._jobs(batch_id)
        for entry in entries:
            self.cancelled()
            if not self._ready(entry):
                continue
            own = [job for job in jobs if job["entry_id"] == entry["id"]]
            if entry["state"].get("processed") and not any(job["job_status"] == "failed" for job in own):
                continue
            state = entry["state"]
            try:
                reference = by_id[entry["reference_id"]]
                self._verify(batch, entry)
                self._verify(batch, reference)
                source_path = self.service.path(state["canonical"])
                reference_path = self.service.path(reference["state"]["canonical"])
                records = result(read_data_file(str(source_path), settings=self.service.settings))["records"]
                reference_records = result(read_data_file(str(reference_path), settings=self.service.settings))["records"]
                checked = result(validate_data(str(source_path), reference_records=[r["data"] for r in reference_records], settings=self.service.settings))
                if any(issue.get("row") is None for issue in checked["issues"]):
                    raise ValueError("File-level validation failed: " + checked["issues"][0]["message"])
                bad_indexes = {issue["row"] - 2 for issue in checked["issues"]}
                external = set(state.get("cross_duplicate_indexes", []))
                clean_indexes = [i for i in range(len(records)) if i not in bad_indexes and i not in external]
                review_indexes = [i for i in range(len(records)) if i in bad_indexes and i not in external]
                if not reference["state"].get("file_id"):
                    uploaded = self.service.upload(f"{reference['relative_path']} [{reference['sheet']}].csv", reference_path.read_bytes(), "reference")
                    reference["state"]["file_id"] = uploaded["id"]
                    self.save_entry(reference)
                for kind, indexes in (("matched", clean_indexes), ("exceptions", review_indexes)):
                    self.cancelled()
                    if indexes:
                        self._job(batch_id, entry, reference, records, indexes, kind, actor)
                state["processed"] = True
                state.pop("run_error", None)
            except Cancelled:
                raise
            except Exception as exc:
                state["run_error"] = str(exc)[:1500]
            self.save_entry(entry)

    def _job(self, batch_id, entry, reference, records, indexes, kind, actor):
        selected = {"rows": [records[i]["data"] for i in indexes], "mapping": {field: field for field in FIELDS}}
        content = canonical_bytes(selected)
        fingerprint = hashlib.sha256(b"folder-v1\0" + kind.encode() + b"\0" + reference["state"]["canonical_sha256"].encode()
                                     + encode([entry["state"].get("currencies", []), reference["state"].get("currencies", [])]).encode() + content).hexdigest()
        association = self.store.one("SELECT job_id FROM batch_jobs WHERE batch_id=? AND entry_id=? AND kind=?", (batch_id, entry["id"], kind))
        previous = association or self.store.one("SELECT job_id FROM batch_jobs WHERE fingerprint=? ORDER BY batch_id LIMIT 1", (fingerprint,))
        if previous:
            job_id = previous["job_id"]
        else:
            uploaded = self.service.upload(f"{entry['relative_path']} [{entry['sheet']}] - {kind}.csv", content, "source")
            task = self.service.create(f"{Path(entry['relative_path']).name} / {entry['sheet']} - {kind}",
                                       "Reconcile the captured folder table with its selected BI reference. Retain differences for human review.",
                                       uploaded["id"], reference["state"]["file_id"], False)
            job_id = task["id"]
        origins = [entry["state"]["origin_rows"][i] for i in indexes]
        with self.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO batch_jobs VALUES(?,?,?,?,?,?,?)",
                       (batch_id, entry["id"], job_id, kind, encode(origins), fingerprint, int(bool(previous and not association))))
        job, state = self.service.get_job(job_id)
        if job["status"] in ("completed", "waiting_confirmation", "cancelled"):
            return
        state.update(plan={"mode": "deterministic", "model": None,
                           "summary": "The user started this folder batch. Automatically reconcile valid records; retain every difference for human review.",
                           "steps": ["Read captured table", "Validate fields", "Compare imported reference", "Archive only clean records"]},
                     plan_status="ready", error=None, stage="Running folder batch")
        self.service.store.save_job(job, state, "running")
        self.service.store.event(job_id, "Folder batch execution authorized", "The batch start authorized this standard reconciliation workflow.",
                                 details={"batch_id": batch_id, "actor": actor, "kind": kind, "original_rows": origins})
        self.service.active = job_id
        try:
            self.service.execute(job_id, actor)
        except Cancelled:
            job, state = self.service.get_job(job_id)
            state.update(stage="Cancelled at a safe boundary")
            self.service.store.save_job(job, state, "cancelled")
            raise
        except Exception as exc:
            job, state = self.service.get_job(job_id)
            state.update(error=str(exc)[:1500], stage="Batch task failed")
            self.service.store.save_job(job, state, "failed")
            self.service.store.event(job_id, "Batch task failed", str(exc)[:1500], "failed")
        finally:
            self.service.active = None

    def describe(self, batch_id):
        batch = self.batch(batch_id)
        entries, associations = self.entries(batch_id), self._jobs(batch_id)
        tasks = {job["job_id"]: self.service.detail(job["job_id"]) for job in associations}
        by_id = {entry["id"]: entry for entry in entries}
        used_references = {by_id[job["entry_id"]]["reference_id"] for job in associations}
        views, attention, runnable, input_rows, matched_rows = [], [], 0, 0, 0
        for entry in entries:
            state = entry["state"]
            own = [job for job in associations if job["entry_id"] == entry["id"]]
            problems = self.base_problems(entry)
            if entry["role"] == "source" and state.get("pair_problem"):
                problems.append(state["pair_problem"])
            if state.get("run_error"):
                problems.append(state["run_error"])
            duplicates = len(state.get("cross_duplicate_indexes", []))
            if duplicates and entry["role"] == "source":
                problems.append(f"{duplicates} rows repeat business keys in another source table. Correct the source files and scan again.")
            eligible = self._ready(entry) and (state.get("row_count", 0) > duplicates) and (
                not state.get("processed") or any(job["job_status"] == "failed" for job in own))
            runnable += bool(eligible)
            if entry["role"] == "source":
                input_rows += state.get("row_count", 0)
            if entry["role"] != "skip" and problems:
                attention.append({"entry_id": entry["id"], "file": entry["relative_path"], "sheet": entry["sheet"], "messages": problems})
            views.append({"id": entry["id"], "file": entry["relative_path"], "sheet": entry["sheet"], "role": entry["role"], "input_group": state.get("input_group"),
                          "row_count": state.get("row_count", 0), "mapping": state.get("mapping", {}), "columns": state.get("columns", []),
                          "currencies": state.get("currencies", []), "reference_id": entry["reference_id"], "candidates": state.get("candidates", []),
                          "problems": problems, "has_jobs": bool(own) or entry["id"] in used_references,
                          "ready": self._ready(entry), "processed": state.get("processed", False)})
        review_tasks = []
        for association in associations:
            task = tasks[association["job_id"]]
            if task["status"] == "completed":
                matched_rows += len(association["origins"])
            elif not (task["status"] in ("running", "pending") and self.service.batch_active == batch_id):
                review_tasks.append({"job_id": task["id"], "entry_id": association["entry_id"], "code": task["code"], "title": task["title"],
                                     "status": task["status"], "row_count": task["row_count"], "issue_count": task["issue_count"],
                                     "error": task["error"], "reused": bool(association["reused"])})
        status = batch["status"]
        if status in ("needs_review", "completed"):
            status = "needs_review" if attention or review_tasks or runnable else "completed" if associations else "needs_review"
            if status != batch["status"] and self.service.batch_active != batch_id:
                self.set_status(batch_id, status, batch["error"])
        command = self.store.one("SELECT id,instruction,plan_json FROM commands WHERE batch_id=?", (batch_id,))
        return {"command": {"id": command["id"], "instruction": command["instruction"], "plan": json.loads(command["plan_json"])} if command else None,
                "id": batch_id, "code": f"BATCH-{batch_id:05d}", "folder": batch["folder"], "bi_folder": batch["bi_folder"], "status": status,
                "actor": batch["actor"], "created_at": batch["created_at"], "updated_at": batch["updated_at"], "error": batch["error"],
                "tables": views, "table_count": len(entries), "source_tables": sum(e["role"] == "source" for e in entries),
                "reference_tables": sum(e["role"] == "reference" for e in entries), "input_rows": input_rows, "matched_rows": matched_rows,
                "unresolved_rows": max(0, input_rows - matched_rows), "archive_receipts": sum(task["archive_count"] for task in tasks.values()),
                "runnable_tables": runnable if batch["scan_complete"] else 0, "scan_complete": bool(batch["scan_complete"]),
                "attention": attention, "review_tasks": review_tasks,
                "reused_tasks": len({job["job_id"] for job in associations if job["reused"]}),
                "busy": self.service.batch_active == batch_id,
                "report_available": status not in ("scanning", "running") and self.service.batch_active != batch_id,
                "cancel_requested": self.service.batch_active == batch_id and self.service.cancel_signal.is_set()}

    def list(self):
        # List rows stay compact; the selected batch loads its full exception queue.
        rows = self.store.all("SELECT * FROM batches ORDER BY id DESC LIMIT 100")
        for row in rows:
            if row["status"] == "needs_review":
                row["status"] = self.describe(row["id"])["status"]
        return rows

    def report(self, batch_id, *, internal=False):
        with self.service.guard:
            if not internal:
                self.idle()
            view = self.describe(batch_id)
            if view["status"] in ("running", "scanning"):
                raise HTTPException(409, "Wait for the batch to stop before downloading its report.")
            from product.excel_report import create_batch_report
            target = self.store.root / "exports" / f"FinanceFlow-{view['code']}-{secrets.token_hex(5)}.xlsx"
            create_batch_report(self, view, target)
            with self.store.connect() as db:
                db.execute("UPDATE batches SET report_path=? WHERE id=?", (str(target.relative_to(self.store.root)), batch_id))
            return target
