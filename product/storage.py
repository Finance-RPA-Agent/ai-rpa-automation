"""Durable local metadata. Financial execution uses the reviewed Runtime separately."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS files (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
 raw_path TEXT NOT NULL, canonical_path TEXT NOT NULL, sha256 TEXT NOT NULL,
 canonical_sha256 TEXT NOT NULL, columns_json TEXT NOT NULL, mapping_json TEXT NOT NULL,
 row_count INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, instruction TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES files(id), reference_id TEXT NOT NULL REFERENCES files(id),
 status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, state_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER REFERENCES jobs(id),
 action TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
 details_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES jobs(id),
 revision INTEGER NOT NULL, evidence_digest TEXT NOT NULL, actor TEXT NOT NULL,
 changes_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS archive (
 id TEXT PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 operation_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO settings VALUES ('schema_version', '1');
CREATE TABLE IF NOT EXISTS batches (
 id INTEGER PRIMARY KEY AUTOINCREMENT, folder TEXT NOT NULL, status TEXT NOT NULL,
 actor TEXT NOT NULL, error TEXT, report_path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 scan_complete INTEGER NOT NULL DEFAULT 0, bi_folder TEXT);
CREATE TABLE IF NOT EXISTS batch_entries (
 id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES batches(id),
 relative_path TEXT NOT NULL, sheet TEXT NOT NULL, role TEXT NOT NULL,
 reference_id INTEGER REFERENCES batch_entries(id), state_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batch_jobs (
 batch_id INTEGER NOT NULL REFERENCES batches(id), entry_id INTEGER NOT NULL REFERENCES batch_entries(id),
 job_id INTEGER NOT NULL REFERENCES jobs(id), kind TEXT NOT NULL, rows_json TEXT NOT NULL,
 fingerprint TEXT NOT NULL, reused INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(batch_id, entry_id, kind));
CREATE TABLE IF NOT EXISTS commands (
 id TEXT PRIMARY KEY, instruction TEXT NOT NULL, folder TEXT NOT NULL, plan_json TEXT NOT NULL,
 actor TEXT NOT NULL, created_at TEXT NOT NULL, batch_id INTEGER UNIQUE REFERENCES batches(id), bi_folder TEXT);
CREATE INDEX IF NOT EXISTS ix_batch_job_fingerprint ON batch_jobs(fingerprint);
CREATE TABLE IF NOT EXISTS data_chats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, folder TEXT NOT NULL,
 bi_folder TEXT, catalog_json TEXT NOT NULL, state_json TEXT NOT NULL, actor TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_turns (
 id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL REFERENCES data_chats(id),
 instruction TEXT NOT NULL, status TEXT NOT NULL, state_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS data_artifacts (
 id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES data_chats(id),
 turn_id INTEGER NOT NULL REFERENCES data_turns(id), path TEXT NOT NULL, sha256 TEXT NOT NULL,
 info_json TEXT NOT NULL, created_at TEXT NOT NULL);
UPDATE settings SET value='4' WHERE key='schema_version' AND value IN ('1','2','3');
"""


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        for folder in ("files", "jobs", "exports", "backups"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.path = self.root / "finance-flow.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            for table in ("batches", "commands", "data_chats"):
                if "bi_folder" not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN bi_folder TEXT")
            if "scan_complete" not in {row[1] for row in db.execute("PRAGMA table_info(batches)")}:
                db.execute("ALTER TABLE batches ADD COLUMN scan_complete INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def one(self, sql, args=()):
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def event(self, job_id, action, message, status="success", details=None):
        with self.connect() as db:
            db.execute("INSERT INTO events(job_id,action,status,message,details_json,created_at) VALUES(?,?,?,?,?,?)",
                       (job_id, action, status, message, encode(details or {}), timestamp()))

    def save_job(self, job, state, status=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state_json=?,status=?,revision=?,updated_at=? WHERE id=?",
                       (encode(state), status or job["status"], job["revision"], timestamp(), job["id"]))

    def backup(self, target):
        with self.connect() as db:
            snapshot = sqlite3.connect(target)
            try:
                db.backup(snapshot)
            finally:
                snapshot.close()
