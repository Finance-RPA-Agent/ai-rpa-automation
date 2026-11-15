"""R1 application workflow regressions; scripted model decisions are NOT live inference."""
import csv
import json
import os
from pathlib import Path
import shutil
import threading

from openpyxl import Workbook, load_workbook
import pytest

from product.service import ProductService
from product.data_tools import DataTools
from product.storage import digest, encode

EN = 'Count order_id across all input rows, without grouping, and export the order_count result to an Excel report.'
ZH = '统计所有输入行中 order_id 的非空数量，不要分组，将总数命名为 order_count 并导出 Excel。'

def action(tool, **arguments):
    return {'action':'tool','tool':tool,'arguments':arguments,'message':''}

def final(message='Completed count 999.'):
    return {'action':'final','tool':None,'arguments':{},'message':message}

class ScriptedModel:
    def __init__(self, actions=()): self.actions=list(actions);self.contexts=[]
    def data_plan(self, context, schema):
        return {'supported':True,'required_tools':['inspect_table','aggregate','export_report'],'message':'Compute and export.'}
    def data_action(self, context, schema):
        self.contexts.append(context)
        item=self.actions.pop(0) if self.actions else final()
        if isinstance(item,Exception): raise item
        return item(context) if callable(item) else item

def write_csv(path, values, field='order_id'):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow([field,'supplier_id'])
        writer.writerows([[v,'A' if i<2 else 'B'] for i,v in enumerate(values)])

@pytest.fixture
def workspace(tmp_path):
    write_csv(tmp_path/'input/orders.csv',['A','B','C','D'])
    service=ProductService(tmp_path/'workspace',model=ScriptedModel())
    chat=service.assistant.create(tmp_path/'input','R1 synthetic test')
    yield service,chat['id'],tmp_path
    service.executor.shutdown(wait=True)

def run(workspace, actions, request=EN, retry=None):
    service,chat_id,_=workspace
    service.model=ScriptedModel(actions)
    service.assistant.start(chat_id,request,'R1 synthetic test',retry_turn_id=retry)
    service.future.result(timeout=30)
    return service.assistant.describe(chat_id)

def aggregate(frame='t1',group=(),column='order_id',output='order_count',op='count'):
    return action('aggregate',frame_id=frame,group_by=list(group),metrics=[{'column':column,'op':op,'output':output}])

def valid_actions(column='order_id',output='order_count'):
    return [action('inspect_table',file_id='f1'),aggregate(column=column,output=output),action('export_report',frame_ids=['t2']),final()]

def preserve(service,result,name):
    if not os.getenv('FF_R1_EVIDENCE'): return
    directory=Path(os.environ['FF_R1_EVIDENCE'])/name;directory.mkdir(parents=True,exist_ok=True)
    (directory/'state.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for artifact in result['artifacts']:
        shutil.copy2(service.assistant.artifact(artifact['id']),directory/artifact['name'])

def read_result(service,artifact):
    with service.assistant.artifact(artifact['id']).open('rb') as stream:
        book=load_workbook(stream,data_only=False)
        try:
            sheets=[s for s in book.sheetnames if s.startswith('Result ')]
            assert sheets==['Result 1']
            sheet=book['Result 1']
            assert all(c.data_type!='f' for row in sheet for c in row)
            return list(sheet.values)
        finally:book.close()

def test_T01_original_wrong_grouping_cannot_complete(workspace):
    result=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['order_id']),action('export_report',frame_ids=['t2']),final('Each order has count 1.')])
    preserve(workspace[0],result,'T01')
    assert result['turns'][-1]['status']!='completed', 'FF-ASSISTANT-001: wrong grouped workbook accepted as completed'

def test_T02_valid_count_exports_actual_total(workspace):
    result=run(workspace,valid_actions())
    preserve(workspace[0],result,'T02')
    assert result['turns'][-1]['status']=='completed',result['turns'][-1]
    assert read_result(workspace[0],result['artifacts'][-1])==[('order_count',),('4',)]
    assert 'order_count = 4' in result['turns'][-1]['message']
    assert '999' not in result['turns'][-1]['message']

def other_input(workspace,values,field='order_id',name='other'):
    service,_,root=workspace
    write_csv(root/name/'orders.csv',values,field)
    chat=service.assistant.create(root/name,'R1 synthetic test')
    return service,chat['id'],root

@pytest.mark.parametrize('instruction,column,alias',[
    (ZH,'order_id','order_count'),
    ('Count non-empty invoice_id in all input records, do not group, and export as invoice_total to Excel.','invoice_id','invoice_total'),
    ('对全部输入记录中的 supplier_id 进行非空计数，不按字段分组，以 supplier_total 作为列名导出 Excel。','supplier_id','supplier_total'),
    ('Please count customer_code across all selected input rows; no grouping; export the customers result to an Excel report.','customer_code','customers'),
])
def test_T03_language_fields_aliases(workspace,instruction,column,alias):
    # Avoid duplicate fixture headers when counting supplier_id.
    if column=='supplier_id':
        current=other_input(workspace,['Z','Z','','Y'],'order_id')
    else: current=other_input(workspace,['Z','Z','','Y'],column)
    result=run(current,valid_actions(column,alias),instruction)
    assert result['turns'][-1]['status']=='completed',result['turns'][-1]
    expected='4' if column=='supplier_id' else '3'
    assert read_result(current[0],result['artifacts'][-1])==[(alias,),(expected,)]

def test_T04_nonblank_count_differs_from_unique_and_rows(workspace):
    current=other_input(workspace,['A','A','','B',' '])
    result=run(current,valid_actions())
    assert result['turns'][-1]['status']=='completed'
    assert read_result(current[0],result['artifacts'][-1])==[('order_count',),('3',)]
    service,chat_id,_=current
    state=json.loads(service.assistant.chat(chat_id)['state_json'])
    engine=DataTools(service.assistant,chat_id,result['turns'][-1]['id'],state)
    unique=engine.call('aggregate',{'frame_id':'t1','group_by':[],'metrics':[{'column':'order_id','op':'nunique','output':'unique_count'}]})
    assert unique['preview']==[['2']]
    assert engine.frame('t1').shape[0]==5

def test_T05_grouped_count_preserved(workspace):
    result=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['supplier_id']),action('export_report',frame_ids=['t2']),final('Two groups.')],
               'Count order_id grouped by supplier_id and export order_count to Excel.')
    assert result['turns'][-1]['status']=='completed'
    assert read_result(workspace[0],result['artifacts'][-1])==[('supplier_id','order_count'),('A','2'),('B','2')]
    assert 'request_constraint' not in result['turns'][-1]

@pytest.mark.parametrize('wrong',[
    aggregate(group=['order_id']),aggregate(column='supplier_id'),aggregate(op='nunique'),aggregate(output='wrong_alias'),
    action('filter_rows',frame_id='t1',conditions=[{'column':'order_id','op':'not_empty'}]),
    action('limit_rows',frame_id='t1',limit=1), action('deduplicate',frame_id='t1',keys=['order_id']),
])
def test_T01_parameter_and_scope_violations_rejected(workspace,wrong):
    result=run(workspace,[action('inspect_table',file_id='f1'),wrong,final()])
    turn=result['turns'][-1]
    assert turn['status']!='completed'
    assert turn['steps'][1]['status']=='error'
    assert 'Ungrouped count:' in turn['steps'][1]['error']

def test_T01_wrong_group_can_recover_within_original_budget(workspace):
    result=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['order_id']),aggregate(),action('export_report',frame_ids=['t2']),final()])
    assert result['turns'][-1]['status']=='completed'
    assert result['turns'][-1]['steps'][1]['status']=='error'
    assert read_result(workspace[0],result['artifacts'][-1])==[('order_count',),('4',)]

def test_T06_valid_result_cannot_export_source_or_grouped_frame(workspace):
    old=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['order_id']),action('export_report',frame_ids=['t2']),final()], 'Group orders and export.')
    assert old['turns'][-1]['status']=='completed'
    result=run(workspace,[aggregate(),action('export_report',frame_ids=['t2']),final()])
    assert result['turns'][-1]['status']!='completed'
    assert result['turns'][-1]['steps'][1]['status']=='error'
    assert len(result['artifacts'])==1

@pytest.mark.parametrize('foreign',[False,True])
def test_T06_old_or_other_chat_artifact_cannot_complete(workspace,monkeypatch,foreign):
    prior=other_input(workspace,['X','Y','Z','W']) if foreign else workspace
    old=run(prior,valid_actions())['artifacts'][-1]
    monkeypatch.setattr(DataTools,'export_report',lambda self,**kwargs:old)
    frame='t2' if foreign else 't3'
    result=run(workspace,[action('inspect_table',file_id='f1'),aggregate(),action('export_report',frame_ids=[frame]),final()])
    assert result['turns'][-1]['status']!='completed'
    assert 'current turn' in result['turns'][-1]['steps'][2]['error']

@pytest.mark.parametrize('actions',[[final()],[action('inspect_table',file_id='f1'),aggregate(),final()]])
def test_T07_omitted_export_and_fictional_completion(workspace,actions,monkeypatch):
    monkeypatch.setattr(ScriptedModel,'data_plan',lambda *args:{'supported':True,'required_tools':[],'message':'No tools.'})
    result=run(workspace,actions)
    assert result['turns'][-1]['status']=='failed'
    assert not result['artifacts']
    assert any(s['tool']=='completion_check' and s['status']=='error' for s in result['turns'][-1]['steps'])

@pytest.mark.parametrize('bad_rows',[[['1']],[['4'],['4']], [['=4']]])
def test_T07_wrong_tool_result_rejected_independently(workspace,monkeypatch,bad_rows):
    original=DataTools.aggregate
    def faulty(self,**kwargs):
        result=original(self,**kwargs);info=self.state['frames'][result['frame_id']]
        path=self.service.path(info['path']);path.write_text(encode({'columns':['order_count'],'rows':bad_rows}),encoding='utf-8')
        info['sha256']=digest(path)
        return result
    monkeypatch.setattr(DataTools,'aggregate',faulty)
    result=run(workspace,valid_actions())
    assert result['turns'][-1]['status']!='completed'
    assert result['turns'][-1]['steps'][1]['status']=='error'
    assert 'independent nonblank count 4' in result['turns'][-1]['steps'][1]['error']

@pytest.mark.parametrize('damage',['value','formula','format','shape'])
def test_T07_actual_excel_checked_even_if_digest_updated(workspace,monkeypatch,damage):
    original=DataTools.export_report
    def faulty(self,**kwargs):
        artifact=original(self,**kwargs)
        row=self.store.one('SELECT * FROM data_artifacts WHERE id=?',(artifact['id'],))
        path=self.service.path(row['path']);book=load_workbook(path);sheet=book['Result 1']
        if damage=='value':sheet['A2']='1'
        elif damage=='formula':sheet['A2']='=4'
        elif damage=='format':sheet['A2'].number_format=';;;'
        else:sheet['B1']='unexpected'
        book.save(path);book.close()
        with self.store.connect() as db:db.execute('UPDATE data_artifacts SET sha256=? WHERE id=?',(digest(path),artifact['id']))
        return artifact
    monkeypatch.setattr(DataTools,'export_report',faulty)
    result=run(workspace,valid_actions())
    preserve(workspace[0],result,'T07_excel_'+damage)
    assert result['turns'][-1]['status']!='completed'
    assert result['turns'][-1]['steps'][2]['status']=='error'

def multi(workspace,xlsx=False):
    service,_,root=workspace
    write_csv(root/'multi/first.csv',['A','A',''])
    if xlsx:
        book=Workbook();book.active.title='First';book.active.append(['order_id','supplier_id']);book.active.append(['B','X'])
        sheet=book.create_sheet('Second');sheet.append(['order_id','supplier_id']);sheet.append(['C','Y']);book.save(root/'multi/second.xlsx');book.close()
    else:write_csv(root/'multi/second.csv',['B','C',' '])
    write_csv(root/'bi/reference.csv',['REF']*9)
    chat=service.assistant.create(root/'multi','R1 synthetic test',bi_folder=root/'bi')
    return service,chat['id'],root

@pytest.mark.parametrize('xlsx',[False,True])
def test_T08_all_input_files_sheets_once_excluding_BI(workspace,xlsx):
    current=multi(workspace,xlsx)
    actions=[action('inspect_table',file_id='f1'),action('inspect_table',file_id='f2')]
    if xlsx:actions.append(action('inspect_table',file_id='f2',sheet='Second'))
    frames=['t1','t2','t3'] if xlsx else ['t1','t2']
    combined='t4' if xlsx else 't3';total='t5' if xlsx else 't4'
    actions += [action('concatenate',frame_ids=frames),aggregate(frame=combined),action('export_report',frame_ids=[total]),final()]
    result=run(current,actions)
    preserve(current[0],result,'T08_'+str(xlsx))
    assert result['turns'][-1]['status']=='completed',result['turns'][-1]
    assert read_result(current[0],result['artifacts'][-1])==[('order_count',),('4',)]
    assert {s['file_id'] for s in result['turns'][-1]['request_constraint']['sources']}=={'f1','f2'}

@pytest.mark.parametrize('mode',['partial','bi','duplicate','filtered','alternate_header'])
def test_T08_incomplete_duplicate_or_changed_scope_rejected(workspace,mode):
    current=multi(workspace)
    actions=[action('inspect_table',file_id='f1'),action('inspect_table',file_id='f2')]
    if mode=='partial':actions += [aggregate()]
    elif mode=='bi':actions += [action('inspect_table',file_id='f3')]
    elif mode=='duplicate':actions += [action('concatenate',frame_ids=['t1','t2']),action('concatenate',frame_ids=['t3','t1'])]
    elif mode=='alternate_header':actions += [action('inspect_table',file_id='f1',header_row=2)]
    else:actions += [action('filter_rows',frame_id='t1',conditions=[{'column':'order_id','op':'not_empty'}])]
    result=run(current,actions+[final()])
    assert result['turns'][-1]['status']!='completed'
    assert result['turns'][-1]['steps'][len(actions)-1]['status']=='error'

def test_T09_legacy_retry_rechecks_old_successes_and_can_recover(workspace):
    old=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['order_id']),action('export_report',frame_ids=['t2']),final()], 'Group orders and export.')
    service,chat_id,_=workspace;old_id=old['turns'][-1]['id']
    # A legacy failed request retained successful but semantically wrong steps.
    with service.store.connect() as db:db.execute("UPDATE data_turns SET instruction=?,status='failed' WHERE id=?",(EN,old_id))
    retry=run(workspace,[final()],retry=old_id)
    preserve(service,retry,'T09_rejected_legacy_retry')
    assert retry['turns'][-1]['status']=='failed'
    assert len(retry['artifacts'])==1
    assert retry['turns'][0]['status']=='failed'
    recovered=run(workspace,[aggregate(),action('export_report',frame_ids=['t3']),final()],retry=retry['turns'][-1]['id'])
    assert recovered['turns'][-1]['status']=='completed'
    assert read_result(service,recovered['artifacts'][-1])==[('order_count',),('4',)]

def test_T10_grouped_followup_and_separate_chat_do_not_inherit(workspace):
    first=run(workspace,valid_actions());first_id=first['turns'][-1]['id']
    grouped=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['supplier_id']),action('export_report',frame_ids=['t3']),final()], 'Now group the original orders by supplier_id and export the counts.')
    assert grouped['turns'][-1]['status']=='completed'
    assert 'request_constraint' not in grouped['turns'][-1]
    assert read_result(workspace[0],grouped['artifacts'][-1])==[('supplier_id','order_count'),('A','2'),('B','2')]
    other=other_input(workspace,['X']*7)
    separate=run(other,valid_actions())
    assert read_result(other[0],separate['artifacts'][-1])==[('order_count',),('7',)]
    assert grouped['turns'][0]['id']==first_id and grouped['turns'][0]['status']=='completed'

@pytest.mark.parametrize('actions',[
    [action('inspect_table',file_id='f1')]+[aggregate(group=['order_id'])]*20,
    [RuntimeError('Synthetic provider interruption')],
    [{'action':'tool','tool':'aggregate','arguments':[], 'message':''}],
    [action('list_files')]*40,
])
def test_T11_failures_invalid_structure_and_budget_are_bounded(workspace,actions):
    result=run(workspace,actions)
    assert result['turns'][-1]['status']=='failed'
    assert len(workspace[0].model.contexts)<=24
    assert result['turns'][-1]['error']
    assert not result['artifacts']

def test_T11_cancel_at_existing_tool_boundary(workspace):
    service,chat_id,_=workspace;entered=threading.Event();release=threading.Event()
    def blocked(context):
        entered.set();assert release.wait(10);return action('inspect_table',file_id='f1')
    service.model=ScriptedModel([blocked])
    response=service.assistant.start(chat_id,EN,'R1 synthetic test')
    try:
        assert entered.wait(10);service.assistant.cancel(response['id'])
    finally:release.set()
    service.future.result(timeout=10)
    result=service.assistant.describe(chat_id)
    assert result['turns'][-1]['status']=='cancelled'
    assert not result['artifacts']

@pytest.mark.parametrize('values',[[],['',' ','\t'],['A']*11])
def test_T12_empty_all_blank_and_variable_size(workspace,values):
    current=other_input(workspace,values)
    result=run(current,valid_actions())
    assert result['turns'][-1]['status']=='completed',result['turns'][-1]
    assert read_result(current[0],result['artifacts'][-1])==[('order_count',),(str(sum(bool(v.strip()) for v in values)),)]

@pytest.mark.parametrize('instruction',[
    EN+' Also group by supplier_id.',
    EN.replace('order_id','unknown_field'),
    'Count unique order_id across all input rows without grouping and export as n to Excel.',
    '统计所有输入行中 order_id 的非空数量，不分组，但又按供应商分组，将总数命名为 order_count 并导出 Excel。',
    EN.replace('all input rows','the paid input rows'),
])
def test_T13_unknown_or_conflicting_request_clarifies(workspace,instruction):
    result=run(workspace,valid_actions(),instruction)
    assert result['turns'][-1]['status']=='needs_input'
    assert not result['turns'][-1]['steps']
    assert not result['artifacts']

def test_T13_quoted_negation_does_not_override_actual_grouping(workspace):
    request='Explain the phrase "count without grouping" later; now count order_id grouped by supplier_id and export.'
    result=run(workspace,[action('inspect_table',file_id='f1'),aggregate(group=['supplier_id']),action('export_report',frame_ids=['t2']),final()],request)
    assert result['turns'][-1]['status']=='completed'
    assert 'request_constraint' not in result['turns'][-1]

def test_T09_restart_preserves_constraint_and_does_not_rewrite_completed(workspace):
    result=run(workspace,valid_actions());service,chat_id,root=workspace
    before=service.store.one('SELECT state_json FROM data_turns WHERE id=?',(result['turns'][-1]['id'],))['state_json']
    service.executor.shutdown(wait=True)
    reopened=ProductService(root/'workspace',model=ScriptedModel())
    try:
        after=reopened.assistant.describe(chat_id)
        assert after['turns'][-1]['status']=='completed'
        assert reopened.store.one('SELECT state_json FROM data_turns WHERE id=?',(result['turns'][-1]['id'],))['state_json']==before
        assert read_result(reopened,after['artifacts'][-1])==[('order_count',),('4',)]
    finally:reopened.executor.shutdown(wait=True)

def test_T07_final_gate_reopens_actual_workbook(workspace):
    service=workspace[0]
    def corrupt_after_export(context):
        artifact=context['recent_steps'][-1]['result']
        row=service.store.one('SELECT * FROM data_artifacts WHERE id=?',(artifact['id'],))
        path=service.path(row['path']);book=load_workbook(path);book['Result 1']['A2']='0';book.save(path);book.close()
        with service.store.connect() as db:db.execute('UPDATE data_artifacts SET sha256=? WHERE id=?',(digest(path),artifact['id']))
        return final()
    result=run(workspace,valid_actions()[:-1]+[corrupt_after_export])
    preserve(service,result,'T07_final_recheck')
    assert result['turns'][-1]['status']=='failed'
    assert any('actual Excel' in s.get('error','') for s in result['turns'][-1]['steps'] if s['tool']=='completion_check')

def test_T08_input_snapshot_mutation_does_not_use_cached_count(workspace):
    service,chat_id,_=workspace
    def change_snapshot(context):
        item=service.assistant.catalog(chat_id)[0]
        service.path(item['path']).write_text('order_id,supplier_id\nOTHER,A\n',encoding='utf-8')
        return aggregate()
    result=run(workspace,[action('inspect_table',file_id='f1'),change_snapshot,final()])
    assert result['turns'][-1]['status']=='failed'
    assert 'snapshot changed' in result['turns'][-1]['steps'][1]['error']

def test_T01_schema_guides_but_does_not_replace_runtime_gate(workspace):
    from product.data_contracts import action_schema
    run(workspace,valid_actions())
    context=workspace[0].model.contexts[1]
    variants=action_schema(context)['anyOf']
    aggregates=[v['properties']['arguments'] for v in variants if v['properties']['tool'].get('enum')==['aggregate']]
    assert len(aggregates)==1
    props=aggregates[0]['properties']
    assert props['group_by']['maxItems']==0
    metric=props['metrics']['items']['properties']
    assert metric['op']['enum']==['count'] and metric['column']['enum']==['order_id'] and metric['output']['enum']==['order_count']
    assert not any(v['properties']['tool'].get('enum')==['export_report'] for v in variants)
