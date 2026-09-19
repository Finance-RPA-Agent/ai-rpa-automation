"""Guard against drift between committed demo files and expected results."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.services.demo_data import DEMO_CASES, reference_records
from backend.app.tools import read_data_file, validate_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = PROJECT_ROOT / "demo_data"

CASE_IDS = [case.name for case in DEMO_CASES]


@pytest.fixture
def project_settings() -> Settings:
    return Settings(
        base_dir=PROJECT_ROOT,
        upload_dir=PROJECT_ROOT / "uploads",
        demo_data_dir=DEMO_DIR,
        output_dir=PROJECT_ROOT / "outputs",
    )


@pytest.mark.parametrize("case", DEMO_CASES, ids=CASE_IDS)
def test_committed_demo_file_exists(case, project_settings):
    assert (DEMO_DIR / case.filename).is_file()


@pytest.mark.parametrize("case", DEMO_CASES, ids=CASE_IDS)
def test_committed_demo_file_matches_expected_result(case, project_settings):
    path = DEMO_DIR / case.filename
    references = reference_records() if case.compare_with_bi else None

    response = validate_data(
        file_path=str(path),
        reference_records=references,
        settings=project_settings,
    )

    assert response["status"] == "success"
    result = response["result"]
    assert sorted(
        issue["type"] for issue in result["issues"]
    ) == sorted(case.expected_issue_types)
    assert result["total_rows"] == case.expected_total_rows
    assert result["valid_rows"] == case.expected_valid_rows
    assert result["invalid_rows"] == case.expected_invalid_rows


def test_committed_leading_zero_file_keeps_identifier(project_settings):
    response = read_data_file(
        file_path=str(DEMO_DIR / "leading_zero.csv"),
        settings=project_settings,
    )

    assert response["status"] == "success"
    record = response["result"]["records"][0]["data"]
    assert record["supplier_id"] == "00123"
    assert record["order_id"] == "ORD-0007"
