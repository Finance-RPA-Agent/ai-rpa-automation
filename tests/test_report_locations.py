"""Reports remain separate from inputs, while original evidence stays intact."""
from pathlib import Path

from product.input_folders import input_files, generated_report
from product.native_reports import save_report
from product.storage import digest
from test_data_assistant import local, turn, action, final


def test_new_artifact_is_already_saved_in_reports_before_export_click(local):
    client, service, _, _, _ = local
    result = turn(local, [action("inspect_table", file_id="f1"), action("export_report", frame_ids=["t1"]), final()])
    artifact = result["artifacts"][0]
    path = service.assistant.artifact(artifact["id"])
    assert path.parent == service.store.root / "exports" / "Reports"
    before = digest(path)
    response = client.post(artifact["url"] + "/export")
    assert response.status_code == 200 and response.json()["saved"] is True
    assert Path(response.json()["path"]) == path
    assert digest(path) == before
    assert client.get(artifact["url"]).status_code == 200


def test_legacy_reports_are_copied_without_altering_old_links_or_overwriting(tmp_path):
    original = tmp_path / ("Assistant-" + "a" * 24 + ".xlsx")
    original.write_bytes(b"synthetic report bytes")
    folder = tmp_path / "Reports"
    folder.mkdir()
    existing = folder / original.name
    existing.write_bytes(b"existing report must survive")
    result = save_report(original, original.name)
    copied = Path(result["path"])
    assert copied.parent == folder and copied != existing
    assert copied.read_bytes() == original.read_bytes() == b"synthetic report bytes"
    assert existing.read_bytes() == b"existing report must survive"
    assert generated_report(copied)


def test_repeated_legacy_save_reuses_identical_report(tmp_path):
    original = tmp_path / ("Assistant-" + "b" * 24 + ".xlsx")
    original.write_bytes(b"synthetic report bytes")
    first = save_report(original, original.name)
    second = save_report(original, original.name)
    assert first["path"] == second["path"]
    assert len(list((tmp_path / "Reports").iterdir())) == 1


def test_scanners_skip_generated_reports_and_report_folders_not_ordinary_inputs(local):
    _, service, _, _, inbox = local
    (inbox / ("Assistant-" + "a" * 24 + ".xlsx")).write_bytes(b"report")
    (inbox / "FinanceFlow-BATCH-00001-1234567890.xlsx").write_bytes(b"report")
    reports = inbox / "Reports"
    reports.mkdir()
    (reports / "ordinary.xlsx").write_bytes(b"report")
    ordinary = inbox / "Assistant-data.xlsx"
    ordinary.write_bytes(b"ordinary user data")
    assert not generated_report(ordinary)
    assistant_files = {path.name for path in input_files(inbox, service.store.root)}
    batch_files = {path.name for path in service.batches._files(inbox)}
    assert assistant_files == batch_files == {"orders.csv", "vendors.xlsx", "Assistant-data.xlsx"}


def test_open_folder_route_is_authenticated_and_only_opens_current_report_directory(local, monkeypatch):
    client, service, _, _, _ = local
    calls = []
    def opened(folder):
        calls.append(folder)
        return {"opened": True, "path": str(folder)}
    monkeypatch.setattr("product.native_reports.open_report_folder", opened)
    response = client.post("/api/reports/open")
    assert response.status_code == 200 and response.json()["opened"] is True
    assert calls == [service.store.root / "exports" / "Reports"]
    assert client.post("/api/reports/open", headers={"Origin": "https://other.invalid"}).status_code == 403
    client.post("/api/logout")
    assert client.post("/api/reports/open").status_code == 401
    assert len(calls) == 1
