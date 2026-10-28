"""Explicit financial review requests bypass generic analysis and retain human control."""
import csv
import io
import json
import threading

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import pytest

from product.api import create_app
from product.review_workflow import review_requested
from product.service import FIELDS
from product.storage import encode, timestamp

REQUEST = "Reconcile the input orders against the BI reference, automatically archive matching records, pause on discrepancies or missing required fields for human review, and generate an Excel report without automatically applying corrections."


class NoAnalysis:
    def data_plan(self, *args): raise AssertionError("The financial review workflow must not call the generic analysis planner.")
    def data_action(self, *args): raise AssertionError("The model must not approve financial changes.")


@pytest.fixture
def local(tmp_path):
    source, bi = tmp_path / 'pending_files', tmp_path / 'bi_system'
    rows = [[f"S{i}", f"Example Supplier {i}", f"O{i}", str(i * 100) + ".00", "2026-10-01", "pending", "active"] for i in range(1, 5)]
    changed = [list(row) for row in rows]
    changed[1][3] = "225.00"; changed[2][5] = "paid"; changed[3][1] = ""
    for path, data in ((source / 'orders.csv', changed), (bi / 'reference.csv', rows)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(FIELDS); writer.writerows(data)
    app = create_app(tmp_path / 'workspace', model=NoAnalysis())
    with TestClient(app, base_url='http://127.0.0.1', headers={'X-Requested-With': 'FinanceFlow'}) as client:
        client.post('/api/setup', json={'username': 'Review Owner', 'password': '123456'})
        chat = client.post('/api/assistant/chats', json={'folder': str(source), 'bi_folder': str(bi)}).json()
        yield client, app.state.service, chat, source, bi


def run(local, retry=None):
    client, service, chat, *_ = local
    body = {'instruction': REQUEST}
    if retry: body['retry_turn_id'] = retry
    response = client.post(f"/api/assistant/chats/{chat['id']}/turns", json=body)
    assert response.status_code == 202, response.text
    service.future.result(timeout=60)
    return client.get(f"/api/assistant/chats/{chat['id']}").json()['turns'][-1]


@pytest.mark.parametrize('instruction,expected', [
    (REQUEST, True),
    ('对账并自动归档匹配记录，异常交给人工复核，生成报告。', True),
    ('Combine the files and create a chart.', False),
    ('Reconcile the files for human review but do not automatically archive matching records.', False),
    ('Reconcile the files for human review; never archive matching records.', False),
])
def test_only_explicit_archive_and_review_requests_route(instruction, expected):
    assert review_requested(instruction) is expected


def test_request_runs_financial_pipeline_and_stops_before_human_decisions(local):
    client, service, _, source, bi = local
    before = [(path, path.read_bytes()) for path in (source / 'orders.csv', bi / 'reference.csv')]
    turn = run(local)
    assert turn['workflow'] == 'reconciliation_review' and turn['status'] == 'needs_review'
    view = turn['review_batch']
    assert view['input_rows'] == 4 and view['matched_rows'] == view['archive_receipts'] == 1
    assert view['unresolved_rows'] == 3 and len(view['review_tasks']) == 1
    assert service.store.all('SELECT * FROM decisions') == []
    assert service.assistant_active is None and service.batch_active is None and service.active is None
    for path, content in before: assert path.read_bytes() == content
    report = client.get(f"/api/batches/{view['id']}/report")
    book = load_workbook(io.BytesIO(report.content))
    assert book['Summary']['B4'].value.startswith('INTERIM')


def test_real_human_review_is_required_and_completion_updates_in_chat(local):
    client, service, chat, *_ = local
    turn = run(local); view = turn['review_batch']; job_id = view['review_tasks'][0]['job_id']
    for _ in range(3):
        task = client.get(f'/api/tasks/{job_id}').json()
        if not task['issues']: break
        response = client.post(f'/api/tasks/{job_id}/review', json={'revision': task['revision'], 'evidence_digest': task['evidence_digest'],
            'changes': [{'issue_id': issue['id'], 'mode': 'reference', 'value': None} for issue in task['issues']]})
        assert response.status_code == 200, response.text
    assert client.post(f'/api/tasks/{job_id}/run').status_code == 200
    service.future.result(timeout=60)
    updated = client.get(f"/api/assistant/chats/{chat['id']}").json()['turns'][-1]
    assert updated['status'] == 'completed' and updated['review_batch']['archive_receipts'] == 4
    assert updated['review_batch']['review_tasks'] == []
    decisions = service.store.all('SELECT * FROM decisions')
    assert len(decisions) == 2
    assert all(decision['reason'] == '' and decision['actor'] == 'Review Owner' and decision['created_at'] for decision in decisions)


def test_previously_rejected_request_can_retry_without_reentering_folders(local):
    client, service, chat, *_ = local
    with service.store.connect() as db:
        rejected = db.execute('INSERT INTO data_turns(chat_id,instruction,status,state_json,created_at,updated_at) VALUES(?,?,?,?,?,?)',
            (chat['id'], REQUEST, 'needs_input', encode({'steps': [], 'message': 'Previously unavailable in the generic tools.', 'error': None}), timestamp(), timestamp())).lastrowid
    old = client.get(f"/api/assistant/chats/{chat['id']}").json()['turns'][-1]
    assert old['can_retry'] is True
    retried = run(local, retry=rejected)
    assert retried['status'] == 'needs_review' and retried['retry_of'] == rejected
    assert retried['review_batch']['matched_rows'] == 1


def test_missing_bi_folder_requests_selection_instead_of_permissions(local):
    client, service, _, source, _ = local
    chat = client.post('/api/assistant/chats', json={'folder': str(source)}).json()
    client.post(f"/api/assistant/chats/{chat['id']}/turns", json={'instruction': REQUEST})
    service.future.result(timeout=60)
    turn = client.get(f"/api/assistant/chats/{chat['id']}").json()['turns'][-1]
    assert turn['status'] == 'needs_input' and 'BI system folder' in turn['message']
    assert service.batches.list() == []


@pytest.mark.parametrize('change', ['modified', 'added'])
def test_changed_inputs_never_silently_replace_captured_request(local, change):
    _, service, _, source, _ = local
    if change == 'modified':
        with (source / 'orders.csv').open('a') as stream: stream.write('\n')
    else: (source / 'new.csv').write_bytes((source / 'orders.csv').read_bytes())
    turn = run(local)
    assert turn['status'] == 'failed' and 'changed' in turn['error']
    assert service.store.all('SELECT * FROM archive') == [] and service.batches.list() == []


def test_cancellation_and_worker_ownership_remain_enforced(local, monkeypatch):
    client, service, chat, source, bi = local
    with pytest.raises(Exception):
        service.batches.run_for_assistant(str(source), str(bi), 'Review Owner', 999, expected={}, attached=lambda _: None)
    entered, release = threading.Event(), threading.Event()
    original = service.batches._scan
    def blocked(batch_id):
        entered.set(); assert release.wait(10); original(batch_id)
    monkeypatch.setattr(service.batches, '_scan', blocked)
    response = client.post(f"/api/assistant/chats/{chat['id']}/turns", json={'instruction': REQUEST})
    turn_id = response.json()['id']; assert entered.wait(10)
    try:
        assert client.post('/api/batches/scan', json={'folder': str(source), 'bi_folder': str(bi)}).status_code == 409
        assert client.post('/api/backup').status_code == 409
        assert client.post(f'/api/assistant/turns/{turn_id}/cancel').status_code == 200
    finally: release.set()
    service.future.result(timeout=60)
    turn = client.get(f"/api/assistant/chats/{chat['id']}").json()['turns'][-1]
    assert turn['status'] == 'cancelled' and turn['can_retry'] is False
    assert service.store.all('SELECT * FROM archive') == []
    assert service.assistant_active is None and service.batch_active is None
