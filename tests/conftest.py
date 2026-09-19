"""Shared fixtures for RPA tool tests.

The environment variables are set before any test module imports
``backend.app.main`` so the FastAPI application, its engine and the tools
use an isolated temporary database and directories.  The default project
database is never touched by the test suite.
"""

from __future__ import annotations

import csv
import os
import shutil
import tempfile
from pathlib import Path

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="rpa-tests-"))

os.environ["RPA_BASE_DIR"] = str(_SESSION_TMP)
os.environ["RPA_DATABASE_URL"] = (
    f"sqlite:///{(_SESSION_TMP / 'test.db').as_posix()}"
)
os.environ["RPA_UPLOAD_DIR"] = str(_SESSION_TMP / "uploads")
os.environ["RPA_DEMO_DATA_DIR"] = str(_SESSION_TMP / "demo_data")
os.environ["RPA_OUTPUT_DIR"] = str(_SESSION_TMP / "outputs")

import pytest  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.database import Base  # noqa: E402


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_SESSION_TMP, ignore_errors=True)


CORE_FIELDS = [
    "supplier_id",
    "supplier_name",
    "order_id",
    "amount",
    "date",
    "payment_status",
    "record_status",
]


@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    return Settings(
        base_dir=tmp_path,
        upload_dir=tmp_path / "uploads",
        demo_data_dir=tmp_path / "demo_data",
        output_dir=tmp_path / "outputs",
    )


@pytest.fixture
def db_session(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'unit.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def make_csv(temp_settings):
    def _make(
        rows,
        name: str = "input.csv",
        encoding: str = "utf-8",
        directory: Path | None = None,
    ) -> Path:
        path = (directory or temp_settings.upload_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding=encoding, newline="") as handle:
            writer = csv.writer(handle)
            for row in rows:
                writer.writerow(row)
        return path

    return _make


@pytest.fixture
def make_xlsx(temp_settings):
    def _make(
        rows,
        name: str = "input.xlsx",
        sheet_name: str = "Sheet1",
        directory: Path | None = None,
    ) -> Path:
        path = (directory or temp_settings.upload_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = sheet_name
        for row in rows:
            worksheet.append(row)
        workbook.save(path)
        workbook.close()
        return path

    return _make
