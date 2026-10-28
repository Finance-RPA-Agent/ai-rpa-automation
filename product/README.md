# Finance Flow — Local Product 1.0

Finance Flow is an English-only Windows desktop application for reconciling supplier/order files
against user-imported BI exports. It uses the committed Agent Runtime and its four financial tools,
a real local Ollama model adapter, durable task revisions, authenticated review and a local archive.
It does not seed fake business records or represent a local archive as an enterprise OA connection.

## Quick start on this computer

### Folder batch workflow

Open **Folder batches** in the sidebar. Select **Input folder** and **BI system folder** independently
with **Browse** or absolute paths, then select **Scan folders**. Review any required column mappings
and choose **Run ready tables**.
That action authorizes the standard reconciliation workflow for the captured tables. Matching clean
rows are archived automatically; only exception subsets become human-review tasks.

Suggested input layout:

```text
Finance/
  pending_files/       # Select as Input folder
    orders_october.xlsx
    orders_november.csv
  bi_system/           # Select as BI system folder
    bi_export.xlsx
```

Every Excel worksheet is recognized separately. Common English headers such as `Vendor ID`,
`Vendor Name`, `PO Number`, `Total Amount`, `Invoice Date`, `Payment State` and `Record State` map
to the seven canonical fields. Headers can be located within the first 20 nonempty rows.
Unrecognized headers require explicit mapping. Folder selection fixes the source/reference role.
Legacy single-folder batches retain their earlier name-based role inference.

Reference matching uses supplier/order key overlap. The unique best reference is selected; ties require
an explicit choice. With only one valid reference, it is selected and missing business keys still become
findings. Invalid reference data, mixed currencies, differing explicit source/reference currencies and
cross-table duplicate source keys block the affected work. Cross-table duplicate rows require source-file
correction and another scan; other clean rows can still complete.

Use **Open review** for an exception task. Changes preserve the originals and remain revision-bound.
After saving corrections, explicitly resume that task to revalidate. Return through **Back to folder batch**
to see the updated totals and download the refreshed Excel report.

The report is generated automatically at batch completion and can also be downloaded from **Excel report**.
Desktop mode opens a native Save As dialog and writes the workbook directly to the location you choose;
browser mode uses an authenticated prepared-file download. Cancelling Save As leaves the batch unchanged.
It contains **Summary**, **Exceptions**, **Reconciliation**, **File log** and **Review history**. Original
and current values, selected reference values, original source rows, receipts and reviewer reasons are
retained. Exception source-row links jump to their detailed reconciliation records. Incomplete work is
labeled **INTERIM**; a **FINAL** report requires every included source row to complete without unresolved setup.
Report text is stored as text, preventing imported formula-like strings from becoming executable formulas.

Scans capture immutable local snapshots. Inputs changing before execution require another scan. Executed
source tables and used references cannot be reconfigured. An identical canonical subset and reference
snapshot reuses its earlier task/receipts; changed evidence may create new versioned reconciliation receipts.
This is a local result archive, not a payment ledger or payment execution system.

Batch limits: 100 files, 200 tables, 50,000 total captured rows and 100 MB combined input; 10 MB per file,
5,000 records per table, 200 columns and 20 worksheets per workbook. Subfolders are visited up to five levels;
hidden/build/runtime folders, symbolic links, junctions, temporary Excel files and generated batch reports
are excluded. Formula cells use the values saved in the workbook. Folder scans run when you choose
**Scan folders**; use another scan to pick up new or changed files. One local worker processes tasks sequentially.

### Individual file workflow

Project: `D:\Richard Xu\xjtlu\Finance-RPA-Agent`.

Validated with 64-bit Python 3.13 on Windows. `product/requirements-lock.txt` records the installed
dependency versions; the setup script uses this lock file. To install manually:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r product/requirements-lock.txt
```

1. Run **Setup Finance Flow.cmd** once if the isolated `.venv` environment is missing.
2. Start Ollama and install the model once: `ollama pull qwen3.5:4b`.
3. Double-click **Start Finance Flow.cmd**.
4. Create your local owner account with a password of at least 6 characters. Letters, numbers and symbols are optional; a numeric-only password is accepted.
5. Import source orders and a BI export, confirm both column mappings, create a task and generate its plan.
6. Review the plan and select **Approve plan & run**.
7. If findings occur, open **Review findings**, confirm specific replacement values, then resume.
8. Download the full JSON audit report and normalized reconciled CSV, or inspect the local archive.

The application uses Microsoft Edge WebView2. If the desktop window cannot open, install the
official WebView2 Runtime or use browser mode:

```powershell
.\.venv\Scripts\python.exe start_product.py --browser
```

Report, export, example-file and backup downloads open the native Save dialog in desktop mode.

Service-only mode is available for development:

```powershell
.\.venv\Scripts\python.exe start_product.py --no-open --port 8877
```

The service listens only on `127.0.0.1`. The default data folder is `%LOCALAPPDATA%\FinanceFlow`.
Use `--data-dir "D:\My Finance Data"` to select another local folder. Only one process may use a data
folder at a time. Close the desktop window, or press Ctrl+C in service/browser mode, to stop.

## Hardware and offline operation

- Target: RTX 4060 Laptop (8 GB VRAM), 16 GB RAM, Windows.
- Local model: `qwen3.5:4b`; 4,096-token context, at most 600 generated tokens per plan.
- One active plan/execution operation; bounded model timeout; model thinking output is disabled.
- The local model interprets instructions and produces strictly validated advice. It cannot grant
  approval, change a task/file identifier or alter Runtime-selected tool arguments.
- The Runtime and Python tools perform financial calculations and writes. No full worksheet is
  placed in the model prompt. Raw business rows are not sent to a remote service.
- Initial Python/model/data downloads need Internet access. Installed local operation does not.
- Model unavailability or invalid structured advice stops plan generation with an explicit error.
  There is no silent fake-model fallback. You may explicitly disable model assistance when creating
  a task to use the reviewed deterministic workflow.

## File contract and mapping

Both source orders and the reference export use these canonical fields:

| Field | Meaning |
| --- | --- |
| `supplier_id` | Counterparty identifier; text leading zeros are preserved |
| `supplier_name` | Counterparty display name |
| `order_id` | Order/invoice identifier; text leading zeros are preserved |
| `amount` | Nonnegative finite amount with at most two decimal places |
| `date` | Date in `YYYY-MM-DD` format; midnight Excel dates are supported |
| `payment_status` | Nonempty status, compared exactly after normalization |
| `record_status` | Nonempty source record status, compared to the reference |

Different input column names can be mapped in the import dialog. Each canonical field must map
to a separate original column. The original file is preserved and a normalized copy is produced.
Bound mappings cannot change after a file is attached to a task; import a new version instead.

- `.xlsx` and UTF-8/UTF-8-BOM `.csv`, maximum 10 MB and 5,000 records per file.
- Only the first Excel worksheet is read. Empty/duplicate headers and malformed CSV are rejected.
- Reference data must pass required-field, format and duplicate-key checks before use.
- Supplier ID + order ID is the match key. Amount, payment status and record status are compared.
  Supplier names and dates are validated but not cross-compared by the inherited financial rules.
- A task must contain one currency. Amounts keep their source currency; no FX conversion is performed.
- The current seven-field normalized output does not preserve extra columns or workbook formatting.
  The original upload remains separately available in application data.

## Review, recovery and archive behavior

- A job pins immutable source and reference versions, their hashes and a working revision.
- Each job has its own financial SQLite database. Another import cannot replace its BI evidence.
- Findings pause execution before normal archive writes. No-match is a business finding, not success.
- Reviews are bound to the task, revision and evidence digest, and use the authenticated local user.
- You may accept a shown reference value or enter a specific replacement for an allowed field.
  A new working copy is reread and revalidated; unresolved or newly introduced findings still block execution.
- Missing keys/columns, duplicate keys and unknown reference records require a corrected file and new task.
- Corrections never mutate source or reference imports. Reviewer identity, time and before/after values persist; no written review reason is required.
- The existing Runtime retries specified technical failures at most once, with stable operation IDs.
- Earlier successful archive writes survive a later failure. Retrying the same revision reuses idempotent
  receipts. A corrected revision receives a new operation namespace.
- Cancellation takes effect at the next safe tool boundary; an in-flight call can finish first.
- Interrupted work is marked failed on restart. Review the preserved trace before retrying.
- Completed/cancelled tasks cannot be restarted. Reports for non-completed tasks are labeled interim.
- The destination is a **local reconciliation archive**. No real enterprise BI/OA access, payment,
  bank transfer or final financial approval is performed or implied.

## Public example data

Optional benchmark CSVs are available under **Files & references** and `product/examples/`.
They are adapted from **Chen, D. (2015), Online Retail, UCI Machine Learning Repository**:
https://doi.org/10.24432/C5BW33, licensed **CC BY 4.0**.

The source is retail transaction data, not a supplier ledger. The preparation script aggregates
positive invoice lines, uses customer identifiers as illustrative counterparty surrogates, constructs
English names and status fields, and injects three labeled test differences. Amounts remain GBP.
The reference is derived from the same dataset, so it is **not independent enterprise BI evidence**.
No example records are automatically imported into a user's workspace.

The included files use the 15,000-line public CSV sample maintained by Elastic Eland:
https://github.com/elastic/eland/blob/main/docs/sphinx/examples/data/online-retail.csv.gz.
`product/examples/PROVENANCE.json` records attribution, the downloaded sample SHA-256, transformations
and injected differences. Rebuild with:

```powershell
.\.venv\Scripts\python.exe product/prepare_public_data.py
```

The script also accepts `--csv-gzip PATH`, `--workbook PATH` or `--archive PATH` for downloaded inputs.
To try the supplied files, use `public_orders_with_findings.csv` as source and `public_reference.csv`
as the BI reference. The first review fixes the missing counterparty name; revalidation then reveals
the amount and payment-status differences. Correct them, then explicitly resume to archive 100 records.

## Account and local security

- One local owner account; Argon2 password hashing, expiring HttpOnly/SameSite=Strict session cookies.
- Changing a password revokes other sessions. Setup cannot replace an existing account.
- State-changing HTTP requests require the application header and matching browser origin.
- Legacy unauthenticated backend routes are not mounted in this product.
- Local storage paths are application-owned. Uploads cannot choose an arbitrary filesystem destination.
- CSV downloads neutralize formula-bearing text. Business values in original files are not rewritten.
- No cloud analytics, CDN fonts or model endpoints. Ollama is fixed to loopback and the local model name.
- Local account authentication does not encrypt files against someone with access to your Windows account.
  Use Windows account security and disk encryption for protection at rest. Backups contain business data
  and password hashes. An account password reset is intentionally not provided as an unauthenticated API.

## Backup and restore

Use **Settings → Download backup** while no task is active. A backup contains a consistent metadata
snapshot, financial task databases, original files, revisions, exports and a SHA-256 manifest.
Restore only to a new empty data directory, with Finance Flow stopped:

```powershell
.\.venv\Scripts\python.exe start_product.py --restore "D:\Backups\finance-flow.zip" --data-dir "D:\FinanceFlow-Restored"
.\.venv\Scripts\python.exe start_product.py --data-dir "D:\FinanceFlow-Restored"
```

Restore verifies the manifest, rejects unsafe ZIP paths, preserves existing directories and revokes old sessions.
The original backup remains unchanged. Verify the restored workspace before changing your normal launch path.

## Source baseline and checks

See [installation verification](VERIFICATION.md) for completed checks and the public-data result.

Baseline: `Finance-RPA-Agent/ai-rpa-automation`, commit
`381cc05b84a474024b3540f7ec340821e6740099` from `feature/agent-runtime-skeleton-v0.1`.
Product work is in local branch `feature/local-product-v1`. The existing four tools and Runtime are reused
without modifying their financial policies. Product authentication, persistence, desktop UI and Ollama
transport are in the new `product/` package. No demo service is used by the launcher.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m unittest discover -s rpa/tests -v
```

`tests/test_local_product.py` checks authentication/CSRF, immutable imports, real Runtime execution,
revision-bound correction, no-match blocking, manual-invalid corrections, password rotation, adapter
contract validation, backup/restore and path safety. Inference-quality and user-acceptance testing
remain separate from these deterministic integration tests.

### Natural-language requests

Use the reconciliation request box on **Folder batches**. Write an English or Chinese request,
then select both **Input folder** and **BI system folder** with their own **Browse** controls. Example:
`Reconcile the orders in D:\Finance\Inbox against its reference files, keep exceptions for my review, and create an Excel report.`
Select **Prepare task**. The installed local Ollama model interprets the request; the application
validates the folder and shows the fixed execution plan. **Run task** authorizes one continuous
scan, matching, reconciliation, clean-row archiving and Excel report generation. Only unresolved
data differences or table setup need human input. Requests and their linked batches persist locally.
The report is generated in the local workspace; use **Excel report** to save a copy elsewhere.

This entry requires Ollama and `qwen3.5:4b`. If the model is unavailable, it shows an error;
the existing manual folder controls remain usable. Missing folders or unsupported requests ask
for clarification. It does not support arbitrary tools, payment, automatic approval of differences,
custom comparison rules, row filtering, currency conversion or changing/deleting source files.
The model receives only the request text, not financial rows, and cannot execute code or choose tools.
Every run uses the existing deterministic financial checks. Editing a prepared request requires a new plan.


### Local data assistant

**Overview** and **Data assistant** provide a general data task entry. Choose an input folder and,
when needed, a separate BI system folder;
write a request in English or Chinese, and select **Start task**. Example requests:

- `Combine the monthly order files, group by supplier, sum the amounts and export an Excel report.`
- `Find duplicate order IDs and show every duplicate occurrence.`
- `Show unpaid orders with amounts above 1000, sorted from highest to lowest.`
- `Calculate monthly spending and create a bar chart.`
- Follow up with `Now group that result by supplier` or `Export the current result`.

The assistant uses the installed local `qwen3.5:4b` model to select one typed tool at a time,
observe its real result and continue. Supported tools: file discovery, CSV/Excel worksheet reading,
data profiling, column selection/renaming, filters, numeric/date sorting, top-N row selection, duplicate detection/removal,
explicit missing-value replacement, whitespace/case cleanup, table append, validated key joins,
grouped sums/means/min/max/counts, arithmetic/date-derived columns, bar/line/pie charts and Excel reports.
Columns are discovered from actual file contents. Ambiguous tasks can ask for clarification.

Each conversation captures immutable copies of its input files and retains result tables, tool history,
charts, reports and follow-up context. **New conversation** captures fresh copies when inputs change.
Report files contain Summary, result sheets, charts when requested, Source evidence and Operations.
Use **Save Excel** for the native Windows save dialog; browser mode uses an authenticated download.
Original files are not modified. The existing financial reconciliation and human review remain available
under **Folder batches** and **Reconciliations**; analytical joins are not reconciliation approvals.

Execution uses the same single local worker. **Stop** cancels at a tool boundary, including after an
in-flight model response. Completed results stay available. Interrupted requests are marked failed at
restart, and the user can continue from retained results. Backups include conversations and their files.

The local model receives request text, column names and bounded row samples/tool results from the selected
folder. These stay on this computer via the fixed loopback Ollama endpoint. The data assistant uses an
8,192-token context; the original reconciliation planner keeps its 4,096-token context. No new Python
dependencies are required. The assistant cannot execute Python/SQL/shell commands, browse the internet,
make payments, approve differences, delete source files or read paths outside the captured folder.

Limits: UTF-8 CSV and `.xlsx`; 100 files/100 MB per conversation, 10 MB per input, 20 worksheets per workbook,
200 columns and 5,000 rows per input table, 50,000 rows/250,000 cells per derived table, 60 saved result tables
and 200,000 saved rows per conversation, 50 requests per conversation and a task-sized budget of 12–24 model actions. Recovery stops after three consecutive failures or eight failures in total; successful steps reset the consecutive-failure counter.
Charts require up to 30 distinct labels. Report exports are limited to 250,000 data cells. Numeric operations
use bounded decimal precision and reject malformed numbers. Group mixed currencies separately; dates must
be unambiguous ISO dates. Exported result cells retain exact text to preserve identifiers and decimal values;
embedded chart series use numeric values. Formula-like source text is stored as text, not executable formulas.

Local models may need a clearer request or a follow-up for ambiguous columns. The UI exposes executed steps,
computed previews and report files so results can be checked independently of the model's written response.


Completion is checked against successful tool calls and generated artifacts, including requested chart
contents and simple explicit first-N row limits. A model claiming that an unexecuted step succeeded cannot
mark the task complete. Tool argument errors are returned to the model for correction within the step/error
budget. Mixed-currency evidence follows derived tables even when columns are removed. Currency symbols
in the written response are kept only when supported by explicit source metadata or the request.


### Separate processing and BI folders

The UI now offers two independently selected directories:

- **Input folder**: the files to process.
- **BI system folder**: local BI export files used as reference data.

Both folders are required by the reconciliation forms. The data assistant can omit the BI folder for
analysis that does not need references. The directories must exist, be separate and not contain each other.
CSV/Excel limits apply to both directories combined. This is local file-based BI reference data, not a
direct connection to an enterprise BI service. The application keeps the original files unchanged.

The supplied data is available in two sibling directories:

```text
product/examples/pending_files/
    orders_part_1.csv
    orders_part_2.csv
product/examples/bi_system/
    bi_reference.csv
```

Select `pending_files` as **Input folder** and `bi_system` as **BI system folder**. These preserve the
existing attributed public benchmark rows: 100 orders, 97 clean and 3 deliberately changed examples.
Each directory includes provenance. Existing example paths remain available for old workflows.

Reconciliation roles come from these folder choices: input tables are source orders, BI tables are references,
regardless of filenames or worksheet names. Captured files, reports and task history retain both paths and
their origin group. BI files are not counted as processing rows. In the data assistant, models see input/BI
groups explicitly; appending input and BI tables together is rejected. Use key joins to compare them.

Existing workspaces receive an additive database migration. Accounts, jobs, review decisions, archives and
conversations stay intact. Old single-folder records remain readable; start a new scan/conversation to use
the new two-folder layout. Backup/restore preserves both choices and their immutable snapshots.


### Retrying a failed data request

After a failure or cancellation, **Retry request** starts a new attempt using the same instruction and
captured data. Completed tool results and result-table IDs are reused; the original failure remains in
history. The retry completes missing operations without requiring another folder import. Retry cannot
change the request or target another conversation. Send a new message to change the task.

Model output now uses separate JSON contracts for every tool. Aggregate input columns are bound to the
actual selected table; output aliases such as `order_count` are not accepted as nonexistent source columns.
Argument validation remains strict at execution. Requested amount-difference charts are constrained to
computed differences, and their final written summary uses the real computed table values.


### Human review from Data assistant

An explicit request to reconcile orders, archive matching/clean records and pause for human review now
uses the existing deterministic financial workflow directly from Data assistant. Select both folders and
submit the request. The conversation displays Reconciliation review with actual counts, Open review,
Open batch and Excel report controls. General analysis remains available through the normal model tools.

The financial workflow needs no model approval or external system permissions. It archives only validated
matching records in the local archive; corrections remain revision-bound authenticated human decisions.
Both root folders must still match the conversation's captured file set and hashes. Changes require a new
conversation. The same single worker and cancellation boundaries apply throughout the handoff.

Previously rejected review requests with both folders selected show Retry request after reopening the app.
Open review lands directly on the findings tab. Completing review updates the linked conversation's counts.
Stopped financial batches retain evidence and are not silently restarted. Sample inputs are available in
`product/examples/review_case/pending_files` and `product/examples/review_case/bi_system`.
