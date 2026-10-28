"""Harness acceptance: real tools, isolated state, CLI exits and failure evidence."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from backend.app.services.agent_runtime_contracts import TaskStatus
from backend.app.tools import dispatcher
from scripts import run_agent_runtime_demo as demo


@pytest.mark.parametrize(
    ("scenario", "status", "classification", "tools"),
    [
        ("clean_success", "completed", "oa_result_archived", [
            "read_data_file", "validate_data", "query_bi", "validate_data", "submit_to_oa",
        ]),
        ("validation_issue", "waiting_confirmation", "business_issue", [
            "read_data_file", "validate_data",
        ]),
        ("bi_no_match", "waiting_confirmation", "business_no_match", [
            "read_data_file", "validate_data", "query_bi", "validate_data",
        ]),
    ],
)
def test_scenario_uses_real_dispatcher_and_observed_runtime(scenario, status, classification, tools):
    report = demo.run_demo(scenario)
    assert report["harness_status"] == "passed"
    assert all(report["demo_checks"].values())
    assert report["task_status"] == status
    assert report["classification"] == classification
    assert report["error_code"] is None
    assert [item["tool"] for item in report["trace"]] == tools
    assert all(item["attempt"] == 0 and not item["retry_allowed"] for item in report["trace"])
    observed = report["runtime_result"]
    for field in ("task_status", "classification", "reason", "error_code", "confirmation_request"):
        assert report[field] == observed[field]
    if scenario == "clean_success":
        record, = report["oa_records"]
        assert record["record_type"] == "reconciliation_result"
        assert record["review_status"] == "archived"
        assert record["data"]["record_status"] == "matched"
        assert record["data"]["amount"] == "5000.00"
        assert report["confirmation_request"] is None
    else:
        assert report["oa_records"] == []
        request = report["confirmation_request"]
        assert request["operation_id"] == f"runtime-demo:{scenario}:v1"
        assert request["task_id"] > 0
        assert request["purpose"] == "archive_exceptions"
        assert len(request["evidence_digest"]) == 64
        assert all(item["tool"] != "submit_to_oa" for item in observed["trace"])
    if scenario == "bi_no_match":
        query, = [item for item in observed["trace"] if item["tool"] == "query_bi"]
        assert query["envelope"]["status"] == "success"
        assert query["envelope"]["result"]["records"] == []
        assert query["classification"] == "business_no_match"
        assert "BI_QUERY_FAILED" not in json.dumps(report)
    elif scenario == "validation_issue":
        validation = observed["trace"][-1]["envelope"]["result"]
        assert any(item["type"] == "invalid_amount" for item in validation["issues"])


@pytest.mark.parametrize("scenario", demo.SCENARIOS)
def test_cli_subprocess_isolated_from_default_database_and_file_roots(scenario, tmp_path):
    sentinel = tmp_path / "unused-default"
    env = {
        **os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "RPA_DATABASE_URL": f"sqlite:///{(tmp_path / 'unused.sqlite3').as_posix()}",
        "RPA_BASE_DIR": str(sentinel), "RPA_UPLOAD_DIR": str(sentinel / "uploads"),
        "RPA_DEMO_DATA_DIR": str(sentinel / "demo_data"),
        "RPA_OUTPUT_DIR": str(sentinel / "outputs"),
    }
    process = subprocess.run(
        [sys.executable, "-B", "-m", "scripts.run_agent_runtime_demo", "--scenario", scenario],
        cwd=demo.PROJECT_ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    assert process.returncode == 0, process.stdout + process.stderr
    report = json.loads(process.stdout)
    assert report["scenario"] == scenario
    assert report["harness_status"] == "passed"
    assert "runtime_result" not in report  # CLI displays the concise trace.
    assert "trace_file" not in report  # Saving is opt-in.
    assert not sentinel.exists()
    assert not (tmp_path / "unused.sqlite3").exists()


@pytest.mark.parametrize("scenario", demo.SCENARIOS)
def test_each_run_cleans_temp_files_and_preserves_process_environment(scenario, tmp_path, monkeypatch):
    monkeypatch.setattr(demo.tempfile, "tempdir", str(tmp_path))
    before = dict(os.environ)
    first = demo.run_demo(scenario)
    second = demo.run_demo(scenario)
    assert first["harness_status"] == second["harness_status"] == "passed"
    assert dict(os.environ) == before
    assert list(tmp_path.iterdir()) == []


def test_save_trace_contains_real_envelopes_and_uses_unique_private_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    paths = []
    for _ in range(2):
        assert demo.main(["--scenario", "clean_success", "--save-trace"]) == 0
        printed = json.loads(capsys.readouterr().out)
        path = Path(printed["trace_file"])
        assert path.parent == tmp_path / "outputs" / "agent_runtime_demo"
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["task_status"] == printed["task_status"] == "completed"
        assert saved["runtime_result"]["trace"][-1]["envelope"]["result"]["submitted"] is True
        assert saved["oa_records"] == printed["oa_records"]
        assert "business data" in saved["trace_notice"]
        paths.append(path)
    assert paths[0] != paths[1]
    assert all(path.is_file() for path in paths)


def test_save_failure_returns_nonzero_without_losing_runtime_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    (tmp_path / "outputs").write_text("blocks directory creation", encoding="utf-8")
    assert demo.main(["--scenario", "clean_success", "--save-trace"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["harness_status"] == "failed"
    assert report["task_status"] == "completed"
    assert report["classification"] == "oa_result_archived"
    assert report["harness_error"]


@pytest.mark.parametrize("scenario", demo.SCENARIOS)
def test_runtime_failure_is_never_overwritten_with_expected_success(scenario, monkeypatch, capsys):
    real_run = demo.AgentRuntime.run

    def failed(runtime, context):
        observed = real_run(runtime, context)
        return replace(observed, task_status=TaskStatus.FAILED, classification="technical_error",
                       reason="Injected Runtime failure for harness test", error_code="INTERNAL_ERROR")

    monkeypatch.setattr(demo.AgentRuntime, "run", failed)
    assert demo.main(["--scenario", scenario]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["task_status"] == "failed"
    assert report["classification"] == "technical_error"
    assert report["error_code"] == "INTERNAL_ERROR"
    assert report["reason"] == "Injected Runtime failure for harness test"
    assert report["harness_status"] == "failed"


def test_wrong_business_outcome_also_returns_nonzero(monkeypatch, capsys):
    real_run = demo.AgentRuntime.run

    def wrong_classification(runtime, context):
        return replace(real_run(runtime, context), classification="business_issue")

    monkeypatch.setattr(demo.AgentRuntime, "run", wrong_classification)
    assert demo.main(["--scenario", "bi_no_match"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["task_status"] == "waiting_confirmation"
    assert report["classification"] == "business_issue"  # Actual, unexpected value.
    assert report["demo_checks"]["business_classification"] is False


@pytest.mark.parametrize("failures", [1, 2])
def test_test_only_technical_injection_exposes_runtime_retry_bound(failures, monkeypatch, capsys):
    real_dispatch = dispatcher.execute_tool
    query_calls = []

    def inject(tool, arguments, **kwargs):
        if tool == "query_bi":
            query_calls.append(dict(arguments))
            if len(query_calls) <= failures:
                return {"status": "error", "error_code": "BI_QUERY_FAILED", "message": "Test-only outage"}
        return real_dispatch(tool, arguments, **kwargs)

    monkeypatch.setattr(dispatcher, "execute_tool", inject)
    # Even a recovered retry is unexpected in this clean demo and is flagged.
    assert demo.main(["--scenario", "clean_success"]) == 1
    report = json.loads(capsys.readouterr().out)
    queries = [item for item in report["trace"] if item["tool"] == "query_bi"]
    assert len(query_calls) == len(queries) == 2
    assert query_calls[0] == query_calls[1]
    assert [item["attempt"] for item in queries] == [0, 1]
    assert [item["retry_allowed"] for item in queries] == [True, False]
    if failures == 2:
        assert report["task_status"] == "failed"
        assert report["error_code"] == "BI_QUERY_FAILED"
        assert report["oa_records"] == []
    else:
        assert report["task_status"] == "completed"
        assert len(report["oa_records"]) == 1


def test_setup_exception_is_explicit_failure_and_cleans_sandbox(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(demo.tempfile, "tempdir", str(tmp_path))

    def broken(*args, **kwargs):
        raise OSError("Test-only setup failure")

    monkeypatch.setattr(demo, "create_engine", broken)
    assert demo.main(["--scenario", "clean_success"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["harness_status"] == "failed"
    assert report["harness_error"]["type"] == "OSError"
    assert "task_status" not in report  # No fabricated Runtime result.
    assert list(tmp_path.iterdir()) == []


def test_invalid_scenario_is_rejected_before_execution():
    with pytest.raises(ValueError, match="Unknown demo scenario"):
        demo.run_demo("unknown")
    with pytest.raises(SystemExit) as error:
        demo.main(["--scenario", "unknown"])
    assert error.value.code == 2
