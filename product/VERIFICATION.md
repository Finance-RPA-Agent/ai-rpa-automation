# Local installation verification

Verified on 2026-10-26, Windows, Python 3.13.12, RTX 4060 Laptop (8 GB VRAM).

- Full repository suite: **402 passed**, including 14 product integration tests.
- Original local-file-tool unittest command: **16 passed**. These overlap with pytest collection.
- Dependency consistency: `pip check` reported no broken requirements.
- Python compilation and JavaScript syntax checks passed.
- Windows EdgeChromium desktop bridge imported successfully.
- Native download handling is enabled so the desktop window can show Save dialogs.
- `qwen3.5:4b` downloaded successfully through Ollama, including digest verification.
  A genuine on-device planning request returned valid English structured advice in 10.27 seconds
  with a 4,096-token context. The existing Runtime proposal boundary accepted the response.
  This is one observed request, not a latency or inference-quality guarantee.
- Live launcher served health, session and English setup-page endpoints successfully.
- A second launcher against the same workspace detected the existing instance without modifying it.
- The supplied public source/reference files completed a real, isolated 100-order reconciliation.
  Two explicit test review decisions corrected the missing name, amount and payment status.
  The final result contained 100 durable local archive receipts.
- All check workspaces are under ignored `product/runtime/`; the owner's normal workspace was not seeded.

The suite reports dependency deprecation warnings for the inherited Pydantic configuration classes
and Starlette's HTTPX test-client adapter. They do not cause test failures. The product uses its
own authenticated API rather than mounting the legacy backend routes.

These checks do not replace user acceptance testing of the desktop interface or independent
validation of financial reference data. The public benchmark reference is derived from the same
retail dataset as the source, as described in `examples/PROVENANCE.json`.


## Folder batch verification — 2026-10-27

- Complete repository suite: **417 passed**, including 15 folder-batch integration tests.
- CSV and multi-worksheet Excel intake, alias mapping, preamble header detection and original row mapping passed.
- Unique reference selection, explicit ambiguity handling, cross-table duplicate quarantine and currency conflicts passed.
- Source/reference changes before execution, incomplete scans and reference immutability after execution passed.
- Identical rescans reuse receipts. Current-batch row provenance remains correct when a previous task is reused.
- Report checks cover exact identifiers, invalid amount text, large decimal amounts, formula-like text, audit history and prepared-file authentication.
- Cancellation, concurrent-worker exclusion and backup/restore of batches passed.
- Public example exercised through the browser UI: 97 of 100 orders archived automatically; the 3 exception rows were corrected in two explicit review decisions, then revalidated to produce 100 receipts.
- The final Excel HTTP response was opened and checked: Summary, Exceptions, Reconciliation, File log and Review history; 100 records and 3 field changes; FINAL status.
- Native Save As and cancellation were integration-tested with a controlled dialog result, including the actual workbook copy to the selected path. Interactive Windows dialog acceptance remains a user check.
- Windows headless Edge/Chrome automation cancelled browser transfers during verification. File responses and workbook bytes were verified independently; desktop export uses native Save As and the browser mode retains an authenticated prepared-file download.
- Folder scan, detected tables, exception review and minimum-window layouts were visually inspected. Accessibility audits of the new screens reported no violations.
- All example runs used isolated, ignored runtime workspaces. No example data was seeded into the owner's normal workspace.


## 2026-10-28: Natural-language requests and visual refresh

- Full suite: **426 passed**, including 9 new command interpretation/execution tests.
- Tested literal path extraction, selected-folder conflicts, missing paths, invalid model output,
  offline responses, authentication/CSRF, idempotent execution and cancellation during scanning.
- A single confirmed command automatically scans, reconciles, archives clean rows and generates
  the Excel report. Uncertain table setup and differences remain explicit human-review items.
- Actual Ollama `qwen3.5:4b` interpreted an English request through the browser UI. The resulting
  batch automatically archived 97 of 100 supplied example rows and held 3 for review. Its Excel report
  was generated automatically; the request is preserved in batch metadata and report Summary.
- Actual local-model checks also extracted a space-containing Windows path from a Chinese
  request and classified automatic payment as unsupported. Tests use controlled model output;
  these live checks were separate and did not send financial row contents to the model.
- Replaced the bright blue/yellow composition with warm neutral surfaces and muted slate controls.
  Compact statistics, navigation and table spacing were visually checked with populated data.
- Overview and batch page WCAG A/AA audits reported **0 violations** after sidebar contrast fixes.
  At 960 x 680 the overview document had no horizontal overflow.
- All UI actions used the isolated `product/runtime/natural-ui-20261028-01` workspace, not the owner's
  normal account or files. The disposable UI Review account is only a test fixture.


## 2026-10-28: Local data assistant

- Final complete suite: **455 passed**, with 29 new assistant checks. Existing 5 dependency deprecation
  warnings remain. `pip check` reports no broken requirements; both frontend scripts pass Node syntax checks.
- Typed tools cover CSV/Excel worksheets, immutable snapshots, profiling, selection/renaming, filters,
  numeric/date sort, top-N rows, duplicate detection/removal, blank replacement, text cleanup, append,
  validated joins, grouped decimal calculations, derived columns, charts and Excel reports.
- Persistent multi-turn state, artifact integrity, backup/restore, authentication/CSRF, worker exclusion,
  cancellation, bounded retries and action budgets passed integration checks.
- Tests explicitly reject fictitious completed exports, reports missing their requested charts, omitted
  explicit row limits, limiting before sorting, unsupported tools/arguments and mixed-currency aggregation
  after removing a currency column. Formula-bearing text and exact numeric identifiers remain inert text.
- Actual `qwen3.5:4b` browser run selected tools to read two supplied public-source CSVs, append 100 rows,
  group by payment status, compute exact totals, create a bar chart and write an Excel report. Two invalid
  argument calls were returned to the model and corrected. This was real model execution, separate from mocks.
- Generated report independently compared against captured CSVs using Decimal: pending 37125.11 and paid
  22.20; embedded Excel chart verified. These are test-source totals, not independent financial validation.
- An actual Chinese follow-up sorted the previous aggregate, selected one row and wrote a new report.
  The final exported worksheet was opened independently and confirmed to have exactly one data row,
  with the expected highest total 37125.11. Completion checks prompted the model to execute missing outputs.
- Earlier live attempts exposed unnecessary read confirmation, invented completion and omission of an
  explicit first-row request. The final implementation adds authorization instructions, independently checked
  tool/output completion, explicit row-bound checks, sort-before-top-N validation and grounded currency labels.
- Browser inspection: conversation, results, chart and report actions render correctly. WCAG A/AA audit
  reported 0 violations. SVG text contrast needed manual review; actual #51555a text on white is 7.51:1.
  At 960 x 680 the document had no horizontal overflow. Native Save As reuses the previously verified adapter;
  assistant export fallback and file integrity are also integration-tested.
- All live actions used isolated `product/runtime/data-ui-20261028-01`, with the disposable Data Review account.
  No owner's credentials, source files, archive records or normal workspace were changed. No new dependencies.


## 2026-10-28: Separate input and BI folders

- Complete repository suite: **467 passed**, including 12 new two-folder checks. Node syntax checks passed.
- Both Data assistant and Folder batches expose independent input/BI folder controls. Financial forms
  require both choices; the BI directory is optional for general analysis without reference data.
- Independent roots define immutable source/reference roles in reconciliation. Same-named files remain
  distinct. BI changes before execution are checked against the BI root. Role swapping is rejected.
- Assistant snapshots, file catalogs, model context, frame lineage, report evidence and backup/restore
  preserve input/BI origin. Appending BI reference rows to processing inputs is rejected; key joins remain available.
- Existing database migration preserves accounts and adds nullable BI-folder columns. Legacy single-folder
  tasks/conversations remain readable. Same, nested, missing and empty folder choices are covered.
- The sample rows were copied unchanged into `product/examples/pending_files` (two source files) and
  `product/examples/bi_system` (one reference file), each with original attribution and layout provenance.
- Real local-model browser run with both roots: inspected two 50-row input files, appended them to 100 rows,
  counted 100 orders and did not append the 100 BI reference rows. All saved task results had input provenance.
- Actual two-root reconciliation through the browser: 100 input rows, 97 completed/archive receipts and
  3 exception rows. The generated Excel report was opened and its BI-folder path checked independently.
- New UI audits reported 0 accessibility violations. At 960 x 680 the batch page showed both root paths
  with no horizontal document overflow. All actions used isolated `product/runtime/split-ui-20261028-01`;
  the owner's normal workspace/account was not seeded or reset. No new dependencies.


## 2026-10-28: Reported model-argument failure and retained-work recovery

- Inspected only the owner's failed request metadata, column names and tool arguments. No passwords or
  financial row contents were read from that workspace; its records were not changed by verification.
- Root causes reproduced: generic arguments permitted an unwanted `file_id` on list_files, nested
  `message` on aggregate, and a nonexistent `order_count` source field. Earlier recovered errors also
  consumed a global three-error budget, leaving too little room for a multi-stage request.
- Per-tool generation contracts now reject unknown parameter shapes and bind aggregate inputs to actual
  frame columns. Full column catalogs remain local and are excluded from the model's text prompt.
- Successful steps reset consecutive failure counts. Complex tasks receive bounded 12–24-action budgets;
  three consecutive or eight total failures still stop execution. Tests replay the screenshot's separated
  failures and complete the actual workbook rather than falsely declaring success.
- Retry request reuses actual successful steps and saved frames, preserves original history, validates
  the same chat/instruction, and reconstructs older saved difference lineage from successful tool evidence.
- Actual local-model replay of the exact user sentence: no tool errors; 100 detail rows, 2 summary rows,
  an embedded amount-difference chart and a generated XLSX. Chart values sum to 25.00, with 0.00 for the
  other payment group. Final narrative is grounded in those computed results. Verified workbook opened
  independently. The successful complete replay took 29.7 seconds in its isolated test workspace.
- An earlier real replay exposed a count chart and an unsupported narrative calculation. Both are covered
  by new chart-measure contracts/runtime checks and table-based result narration; a count chart cannot
  satisfy a requested amount-difference chart.
- Full repository suite: **475 passed**, including 8 new recovery/contract regressions; existing 5 dependency
  deprecation warnings remain. No new dependencies or changes to the financial approval Runtime.

- Browser Retry request check passed on an isolated seeded interruption derived from real successful replay steps: reused 7 saved steps, executed aggregation, the correct difference chart and export, and completed without rereading source files. All writes remained in product/runtime/recovery-live-20261028-01; the owners normal workspace was untouched.


## 2026-10-28: Route human-review requests from Data assistant

- Read only the owner's rejected instruction, status and selected paths to diagnose the generic-analysis
  refusal. The rejected request used the 100-row public example, not the separate four-row review fixture.
  No normal-workspace records or account credentials were changed by verification.
- Explicit reconciliation + clean-row archiving + human-review requests now route to the original financial
  Runtime on the reserved local worker. The generic model is not asked to grant permissions or approve changes.
- Both original folder contents and snapshot hashes are checked, including again at financial capture before
  execution. Changed/additional files cannot silently replace the originally captured request.
- The chat shows real batch progress/counts and Open review/Open batch/Excel report controls. Open review
  deep-links to the findings tab. Previously rejected matching requests expose Retry request.
- Tests verify clean-only archiving, zero automatic review decisions, unchanged CSVs, explicitly authenticated
  corrections/revalidation, missing BI folders, changed inputs, worker exclusion, cancellation and legacy retries.
- Actual browser replay of the exact reported sentence with review_case: 4 inputs, 1 archived, 3 held;
  Open review opened the missing-required-value findings screen directly. No review correction was clicked
  during UI verification. The integration test separately verifies explicit decisions lead to all 4 receipts.
- Full repository suite: **487 passed**, including 12 routing checks. Node syntax checks passed. New chat
  review card accessibility audit reported 0 violations. No new dependencies or changes to financial rules.
- UI actions used isolated `product/runtime/review-route-ui-20261028-01` and a disposable Review Route
  account; source data was the explicitly synthetic review fixture. The owner's workspace was untouched.


## 2026-10-28: Remove mandatory Review reason

- Removed the Review reason input, client payload and obsolete focus target from the correction dialog.
- API omission defaults to an empty note; written reasons are no longer required by the review service.
- Explicit confirmation, replacement values, reviewer identity, timestamp, before/after changes, revisions and evidence checks remain. Historical notes are preserved.
- Existing end-to-end tests now submit reason-free corrections and verify archive completion and audit metadata. Targeted suites: 41 passed; frontend syntax check passed. No account or financial source files changed.
