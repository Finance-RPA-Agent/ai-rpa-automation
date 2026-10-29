# FF-ASSISTANT-001: explicit all-input counts

The baseline accepted a grouped order count and reported completion despite the
request explicitly requiring no grouping. This candidate adds application-owned
constraints to the existing bounded assistant loop. DataTools and the finance
runtime are unchanged. It is an uncommitted review candidate, not a release.

Supported grammar uses explicit ASCII column identifiers (optionally backticked),
all input rows/records, an explicit no-group clause, one output alias and Excel
export. Examples (identifiers and aliases are variable, not fixture IDs):

- `Count order_id across all input rows, without grouping, and export the order_count result to an Excel report.`
- `Count non-empty invoice_id in all input records, do not group, and export as invoice_total to Excel.`
- `统计所有输入行中 order_id 的非空数量，不要分组，将总数命名为 order_count 并导出 Excel。`
- `对全部输入记录中的 supplier_id 进行非空计数，不按字段分组，以 supplier_total 作为列名导出 Excel。`

Case-insensitive English keywords, selected/all synonyms, simple separators,
Chinese quantity/count synonyms and final punctuation are accepted. Exact column
case is retained. Unknown fields, additional filtering/distinct requirements,
conflicting instructions and unmatched no-group count grammar ask for
clarification. Quoted prose alone does not activate the contract. Other requests,
including explicit grouped counts, keep the existing workflow. This does not
promise arbitrary language understanding.

Scope is every captured input CSV and every worksheet of input XLSX files using
header row 1. BI reference files are excluded from computation. A missing field
or malformed/ambiguous header is rejected, never guessed. A header-only table
produces zero under existing tool behavior. The expected count is independently
computed from snapshot cells with `str(value).strip()` nonempty semantics;
duplicates count separately, unlike nunique. Existing input/result and action
budgets still apply. Many files or unsupported worksheet cache names may require
a smaller/clearer request; no limits were increased.

Every aggregate must use the exact field/count/alias and an empty group_by. Its
input must be original inspected records or an append-only lineage covering all
input tables exactly once. Source digests and actual frame values are rechecked.
The result must contain exactly one column and one correct value. Export verifies
the result proof, artifact chat/turn identity, saved metadata, file digest and
actual workbook cells, shape, formula type, basic number format and request/frame
binding. Completion reopens and checks the workbook again. Final user-facing
wording is built from verified values; model wording is retained as model_message
for audit, not accepted as evidence.

The existing turn JSON holds instruction hash, chat/turn ID, source fingerprints,
semantics, independent expected count and verification evidence. Retry reparses
the original instruction and requires a new aggregate/export; old successful
tool lists cannot authorize completion. Source frames can be reused only after
revalidation. Historical completed turns remain unchanged. A new grouped request
has no inherited no-group constraint. No database migration is required.

`python -m pytest -q tests/test_ungrouped_count.py` exercises T01–T13 with the
actual ProductService/DataAssistant/DataTools workflow, saved JSON/SQLite state
and actual XLSX files. Scripted model choices and intentional faulty tool/export
injections are deterministic tests, not live model evidence. Assertions use
independent literal/source expectations. T14 is covered by unchanged assistant,
review routing, command, top-N, difference-chart and multi-turn regression tests.
The external review package contains pristine-baseline failure, all intermediate
failures, full regression logs/JUnit, isolated HTTP finance smoke and the frozen
six-case real local model set. These layers must be reported separately.

Protected: PR #3 navigation files, financial rules/tools, database schema, routes,
permissions, fixtures, dependencies, model identity/endpoint/options/budgets,
original preview/Agent source, user data and launchers. No cloud provider, second
model, commit, push, PR or merge is part of R1. Stop using this independent clone
to roll back; nothing has been deployed over the existing preview.
