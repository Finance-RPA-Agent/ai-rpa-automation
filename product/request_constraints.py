"""Finite, application-owned constraints for explicit all-input nonblank counts.

This is deliberately not a general natural-language validator. DataTools remains
the executor; expected values are read separately from captured source tables.
"""
from collections import Counter
import hashlib
import json
import re

from openpyxl import load_workbook
import pandas as pd

from product.storage import digest, encode


class CountClarification(ValueError):
    pass


def parse_count_request(instruction):
    # Quoted prose is not an operative instruction. Backticks may wrap identifiers.
    active = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|\'[^\'\n]*\'', ' ', instruction)
    negative = r'\b(?:without\s+grouping|do\s+not\s+group|no\s+grouping)\b|(?:不要分组|不分组|不按字段分组)'
    if not re.search(negative, active, re.I): return None
    if not re.search(r'\bcount\b|非空(?:数量|个数|计数)|计数|统计', active, re.I): return None
    identifier = r'`?([A-Za-z_][A-Za-z_0-9]*)`?'
    gap = r'\s*[,，;；]?\s*'
    scope = r'(?:across|in)\s+all\s+(?:selected\s+)?input\s+(?:rows|records)'
    no_group = r'(?:without\s+grouping|do\s+not\s+group|no\s+grouping)'
    patterns = [
        r'(?:please\s+)?count\s+(?:non[- ]empty\s+)?' + identifier + r'\s+' + scope + gap + no_group + gap
        + r'(?:and\s+)?export\s+(?:the\s+)?' + identifier + r'\s+result\s+to\s+(?:an?\s+)?Excel\s+report',
        r'(?:please\s+)?count\s+(?:non[- ]empty\s+)?' + identifier + r'\s+' + scope + gap + no_group + gap
        + r'(?:and\s+)?export\s+(?:the\s+(?:total|result)\s+)?as\s+' + identifier + r'\s+to\s+Excel',
        r'统计(?:所有|全部)(?:选定的?)?输入(?:行|记录)中\s*' + identifier + r'\s*的非空(?:数量|个数)' + gap
        + r'(?:不要分组|不分组|不按字段分组)' + gap + r'(?:将|把)(?:总数|结果)(?:命名为|命名成)\s*' + identifier + r'\s*并导出\s*Excel',
        r'对(?:所有|全部)输入(?:行|记录)中的?\s*' + identifier + r'\s*(?:做|进行)非空计数' + gap
        + r'(?:不要分组|不分组|不按字段分组)' + gap + r'(?:以|使用)\s*' + identifier + r'\s*(?:为|作为)列名导出\s*Excel',
    ]
    text = instruction.strip().rstrip('.。!！').strip()
    for pattern in patterns:
        matched = re.fullmatch(pattern, text, re.I)
        if matched:
            column, output = matched.groups()
            return {'kind':'ungrouped_nonblank_count', 'version':1, 'column':column,
                    'op':'count', 'group_by':[], 'output':output,
                    'scope':'all_input_tables_header_1', 'export_required':True}
    raise CountClarification('Clarify one field, all input rows, no grouping, one output alias and Excel export. Filters, distinct counts, conflicting grouping and quoted instructions are not supported by this count contract.')


class CountGuard:
    def __init__(self, tools, turn, instruction, constraint):
        self.tools, self.turn, self.instruction = tools, turn, instruction
        self.constraint = constraint
        self.tables = {}
        sources = []
        for item in tools.assistant.catalog(tools.chat_id):
            if item.get('group', 'input') != 'input': continue
            path = tools.service.path(item['path'])
            if digest(path) != item['sha256']: raise CountClarification('Captured input integrity check failed.')
            for index, sheet in enumerate(item['sheets']):
                if path.suffix.lower() == '.csv':
                    raw = pd.read_csv(path, dtype=str, keep_default_na=False, header=None, nrows=5021, encoding='utf-8-sig')
                else:
                    raw = pd.read_excel(path, sheet_name=sheet, dtype=str, keep_default_na=False, header=None, nrows=5021, engine='openpyxl')
                if not len(raw): raise CountClarification('An input table has no header. Supply a table with a named count field.')
                columns = [str(value).strip() for value in raw.iloc[0]]
                if any(not c for c in columns) or len(set(columns)) != len(columns) or constraint['column'] not in columns:
                    raise CountClarification('Every input table must have unique nonblank headers including the exact count field: ' + constraint['column'])
                if len(raw)-1 > 5000 or len(columns)>200: raise CountClarification('An input table exceeds existing input limits.')
                values = raw.iloc[1:, columns.index(constraint['column'])].astype(str).tolist()
                key = (item['file_id'], index)
                self.tables[key] = {'values':values, 'sheet':sheet, 'sha256':item['sha256'], 'path':item['path']}
                sources.append({'file_id':key[0], 'sheet_index':index, 'sheet':sheet, 'sha256':item['sha256'],
                                'rows':len(values), 'nonblank_count':sum(bool(v.strip()) for v in values)})
        if not sources: raise CountClarification('No input tables are available for this count.')
        self.expected = sum(row['nonblank_count'] for row in sources)
        self.binding = {**constraint, 'chat_id':tools.chat_id, 'turn_id':tools.turn_id,
                        'request_sha256':hashlib.sha256(instruction.encode('utf-8')).hexdigest(),
                        'sources':sources, 'expected_count':self.expected, 'verified_results':{}, 'verified_export':None}
        # Never import prior tool successes or a historical completed artifact as proof.
        turn['request_constraint'] = self.binding

    def fail(self, message):
        raise ValueError('Ungrouped count: ' + message)

    def source_key(self, file_id, sheet=0, header_row=1):
        if header_row != 1: self.fail('Use header_row=1 for the captured all-input scope.')
        for key, table in self.tables.items():
            if key[0] == file_id and (sheet == key[1] or sheet == table['sheet']): return key
        self.fail('Use a selected input file and sheet, never a BI reference table.')

    def lineage(self, frame_id, visiting=()):
        if frame_id in visiting: self.fail('Cyclic frame lineage is invalid.')
        info = self.tools.state['frames'].get(frame_id, {})
        frame = self.tools.frame(frame_id)
        if 'source' in info:
            file_id, sheet, header = info['source'].split(':', 2)
            # DataTools stores either sheet name or index in this legacy cache key.
            matches = [key for key, table in self.tables.items() if key[0] == file_id and sheet in (str(key[1]),table['sheet'])]
            if header != '1' or len(matches) != 1: self.fail('Source frame does not match the captured scope.')
            key = matches[0]; table = self.tables[key]
            if digest(self.tools.service.path(table['path'])) != table['sha256']: self.fail('The input snapshot changed.')
            if self.constraint['column'] not in frame or frame[self.constraint['column']].tolist() != table['values']:
                self.fail('Source frame values differ from the captured input records.')
            return [key]
        if info.get('operation') != 'Append tables' or not info.get('parents'):
            self.fail('Count the original input tables or their append-only combination; no filters, joins or derived rows.')
        keys = [key for parent in info['parents'] for key in self.lineage(parent, (*visiting,frame_id))]
        if len(keys) != len(set(keys)): self.fail('Each input table must occur exactly once.')
        values = [v for key in keys for v in self.tables[key]['values']]
        if self.constraint['column'] not in frame or frame[self.constraint['column']].tolist() != values:
            self.fail('Appended records differ from the independently captured input records.')
        return keys

    def full_scope(self, frame_id):
        keys = self.lineage(frame_id)
        if Counter(keys) != Counter(self.tables.keys()): self.fail('Include every input table exactly once before aggregate; inspect the missing inputs and concatenate them.')

    def before(self, tool, args):
        if tool == 'inspect_table': self.source_key(args.get('file_id'),args.get('sheet',0),args.get('header_row',1))
        elif tool == 'concatenate':
            keys = [key for frame_id in args.get('frame_ids',[]) for key in self.lineage(frame_id)]
            if len(keys) != len(set(keys)): self.fail('Do not append overlapping input tables.')
        elif tool == 'aggregate':
            wanted = [{'column':self.constraint['column'],'op':'count','output':self.constraint['output']}]
            if args.get('group_by',[]) != [] or args.get('metrics') != wanted:
                self.fail('Use group_by=[] and exactly metrics=' + encode(wanted) + '. Count nonblank values; do not use nunique or another field.')
            self.full_scope(args.get('frame_id'))
        elif tool == 'export_report':
            ids = args.get('frame_ids',[])
            if len(ids) != 1: self.fail('Export only the verified single total frame.')
            self.validate_result(ids[0])
        elif tool not in ('list_files','profile_table'):
            self.fail('This request only needs inspect_table, concatenate when needed, aggregate and export_report. Do not change the input records.')

    def after(self, tool, args, result):
        if tool == 'aggregate':
            frame_id = result['frame_id']
            self.check_value(frame_id)
            self.binding['verified_results'][frame_id] = {'arguments':args, 'sha256':self.tools.state['frames'][frame_id]['sha256']}
        elif tool == 'export_report':
            self.validate_artifact(result)
            self.binding['verified_export'] = result

    def check_value(self, frame_id):
        frame = self.tools.frame(frame_id)
        if list(frame.columns) != [self.constraint['output']] or frame.shape != (1,1) or str(frame.iloc[0,0]) != str(self.expected):
            self.fail('The result must be one column named ' + self.constraint['output'] + ' and one row with independent nonblank count ' + str(self.expected) + '.')

    def validate_result(self, frame_id):
        proof = self.binding['verified_results'].get(frame_id)
        if not proof: self.fail('Aggregate a fresh total for this turn; a retained result is not verified.')
        self.before('aggregate',proof['arguments'])
        if self.tools.state['frames'][frame_id]['sha256'] != proof['sha256']: self.fail('The verified result changed.')
        self.check_value(frame_id)

    def validate_artifact(self, artifact):
        row = self.tools.store.one('SELECT * FROM data_artifacts WHERE id=?',(artifact.get('id'),))
        if not row or row['chat_id'] != self.tools.chat_id or row['turn_id'] != self.tools.turn_id:
            self.fail('The report must belong to this conversation and current turn.')
        saved = json.loads(row['info_json'])
        if saved != artifact or len(saved.get('frame_ids',[])) != 1: self.fail('Report metadata does not identify one verified result.')
        self.validate_result(saved['frame_ids'][0])
        path = self.tools.service.path(row['path'])
        if digest(path) != row['sha256']: self.fail('The exported report failed its integrity check.')
        book = load_workbook(path,read_only=True,data_only=False,keep_links=False)
        try:
            if [s for s in book.sheetnames if s.startswith('Result ')] != ['Result 1']: self.fail('Report has unexpected result sheets.')
            sheet = book['Result 1']
            if sheet.max_row != 2 or sheet.max_column != 1 or sheet['A1'].value != self.constraint['output']:
                self.fail('The actual Excel has incorrect headers or result shape.')
            cell = sheet['A2']
            if cell.data_type not in ('s','n') or isinstance(cell.value,bool) or str(cell.value) != str(self.expected) or cell.number_format not in ('General','@','0'):
                self.fail('The actual Excel value, formula or format is not the verified count.')
            if book['Summary']['B3'].value != self.instruction or book['Summary']['A8'].value != saved['frame_ids'][0]:
                self.fail('The workbook is not bound to the current request and verified frame.')
        finally: book.close()

    def completion_error(self):
        try:
            artifact = self.binding['verified_export']
            if not artifact: self.fail('No verified Excel report was exported during this turn.')
            self.validate_artifact(artifact)
            if self.tools.state['latest_frame'] != artifact['frame_ids'][0]: self.fail('Export the current verified total, not an earlier frame.')
        except (ValueError,KeyError,TypeError,OSError) as exc: return str(exc)
        return None

    def context(self):
        eligible = []
        for frame_id in self.tools.state['frames']:
            try: self.full_scope(frame_id)
            except (ValueError,KeyError,TypeError): continue
            eligible.append(frame_id)
        return {**self.constraint, 'input_files':list(dict.fromkeys(key[0] for key in self.tables)),
                'aggregate_frame_ids':eligible, 'verified_result_ids':list(self.binding['verified_results'])}

    def message(self):
        return f"Completed: {self.constraint['output']} = {self.expected} (nonblank {self.constraint['column']} values across all {len(self.tables)} input tables, without grouping). The verified Excel report is available below."
