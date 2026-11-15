# Finance Flow 1.0 · Product guide

The desktop application keeps a local workspace for source files, BI exports, reconciliation tasks, review decisions, reports and archive receipts. For a first run, follow the [Windows setup](../README.md#start-on-windows) and the [four-order walkthrough](../docs/FINANCEFLOW_V1_DELIVERY.md#four-order-demonstration).

## Launch and data location

Use 64-bit Python 3.12 for the reviewed Windows setup. From the extracted project root, `Setup Finance Flow.cmd` uses a project-local `.venv` and installs [the pinned Python dependencies](requirements-lock.txt). To select the interpreter and install manually:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r product/requirements-lock.txt
```

Double-click `Start Finance Flow.cmd` for the WebView2 desktop window in **demo mode**. Click **Enter demo**; its username and masked password are display fields, and no credentials are submitted. The default server listens at `http://127.0.0.1:8877`. Demo data is stored separately in `%LOCALAPPDATA%\FinanceFlow\demo` and survives restart. The sidebar identifies it as **Demo workspace**. To choose another demo base directory, run `start_product.py --demo --data-dir <base>`; files are stored in its `demo` subdirectory.

For the original password-protected workspace, run `.\.venv\Scripts\python.exe start_product.py` without `--demo`. Its default directory remains `%LOCALAPPDATA%\FinanceFlow`, with its original owner and records. Close the running application before switching modes on the same port. To isolate an account-protected demonstration, choose a fresh directory outside the source folder. From PowerShell:

```powershell
$demo = Join-Path $env:LOCALAPPDATA "FinanceFlow RC1 Demo"
.\.venv\Scripts\python.exe start_product.py --browser --port 8877 --data-dir "$demo"
```

Use `--no-open` instead of `--browser` to run the service without opening a window. Choose a different free port if 8877 is occupied. Each data directory supports one active instance. Close the desktop window, or press Ctrl+C in the service/browser terminal to stop. Restart with the same data directory to read saved records.

In password-protected mode, first create the workspace's owner account with a password of at least six characters. Subsequent launches use that account. Demo mode instead uses a fixed local **Demo User** identity and hides password settings. Its entry is for presentation, not identity verification. Both modes still use local session cookies and the existing request boundaries. Store the workspace on a device you control. Backups include business files and authentication metadata and belong outside source distributions. **Settings → Download backup** creates a snapshot when the worker is idle. With Finance Flow stopped, restore a verified backup only into a new, empty directory (without `--demo`):

```powershell
.\.venv\Scripts\python.exe start_product.py --restore ".\finance-flow-backup.zip" --data-dir "$env:LOCALAPPDATA\FinanceFlow Restored"
```

## Individual file workflow

Import UTF-8 CSV or XLSX files as **Source orders** and **BI reference**. Individual uploads read the first Excel worksheet. Files are limited to 10 MB, 5,000 data rows and 200 columns. A mapping can be completed after import. The original upload is retained when a working copy changes.

| Field | Use |
| --- | --- |
| `supplier_id`, `order_id` | Composite match key. Keep identifiers as text when leading zeros matter. |
| `supplier_name`, `date` | Required identifying information and an ISO date in YYYY-MM-DD format. |
| `amount` | Nonnegative amount with at most two decimal places. Use one currency per task. |
| `payment_status`, `record_status` | Source values compared with the BI reference. |

Open **New reconciliation**, choose or upload source orders and a BI reference, complete any required column mappings, then click **Start reconciliation**. This explicitly starts the fixed local workflow, including archiving reconciled results; it does not need a model, a separate task-creation click or plan approval. Differences still pause for human review. To use custom instructions or inspect a model-assisted plan, select **Customize instructions and review a plan first**, create the task, generate its plan and approve it before execution.

If a finding is held, open **Review findings** and compare the displayed source and BI values. A signed-in review decision is bound to the task revision and evidence. Correcting a finding creates a new working revision. Resume the task explicitly after all findings are resolved. The task page offers a JSON report, and a completed task additionally offers a reconciled CSV.

## Folder batch workflow

Open **Folder batches**, choose separate **Input folder** and **BI system folder**, then **Scan folders**. Inspect discovered tables, reference choices and mappings before selecting **Run ready tables**. Clean rows can produce local receipts while exception rows are held for review. After review, download the Excel report to inspect the reconciliation, exceptions and review history. Use the two sibling folders in the [synthetic review example](examples/review_case/README.md).

## Data assistant and optional local AI

### Generated report location

Excel reports are saved automatically in the current workspace's `exports/Reports` folder. The default demo path is `%LOCALAPPDATA%\FinanceFlow\demo\exports\Reports`; the ordinary workspace uses `%LOCALAPPDATA%\FinanceFlow\exports\Reports`. **Open reports folder** opens this directory in Windows Explorer. **Show report** opens the same directory after ensuring that a legacy report has a copy there. Saving does not ask for a destination and cannot accidentally default to a recently used input or BI folder. Older download links and original artifact checksums are retained.

Folder scans skip `Reports` subdirectories and recognized generated Assistant/batch workbook names. Ordinary workbooks, including user files named `Assistant-data.xlsx`, remain eligible. Moving a report does not rewrite an existing conversation's captured files: start a new conversation to capture a cleaned folder.

General natural-language analysis uses Ollama on the same machine and the model `qwen3.5:4b`. Install Ollama and prepare the model once with `ollama pull qwen3.5:4b`. The Finance Flow launcher checks the local service on startup and reuses it or starts `ollama serve` in the background, listening only on `127.0.0.1:11434`. On Windows it also checks the standard installation folders when Explorer has an older PATH. It waits briefly for the service, then continues with a diagnostic if unavailable. Missing Ollama or model weights do not block fixed-rule reconciliation. Startup checks only installed tags, without inference, model downloads or an automatic model warm-up. The service remains running after the app closes, so other local applications can continue using it. Pass `--no-auto-ollama` to skip this behavior. The source package contains neither the model nor its runtime.

In **Data assistant**, select the input folder (and a separate BI folder for comparisons), start a conversation and inspect computed previews, tool history and reports. It captures copies of the selected inputs. The optional assistant can send bounded local samples and tool results to the local model. Reconciliation advice does not approve a correction or execute a payment.

Use **Check data quality**, **Combine tables**, **Count orders** or **Reconcile & review** to fill an editable request. These buttons do not execute anything or change folders. Review the request, adapt column names such as `order_id` to your files, select the required folders, then submit. The reconciliation example requires a BI folder. Follow-up requests offer the same starting points.

Running tasks display their current operation and elapsed time. The assistant distinguishes planning, waiting for the model and running a data tool, and counts only successful saved operations. A longer model wait shows an explicit notice; no estimated completion percentage is shown. **Stop** requests cancellation at a safe boundary and may wait for an in-flight model request. A progress refresh failure preserves the last saved result and offers **Refresh status**, which only reads status. Use **Retry request** on a stopped or failed assistant request when appropriate; refresh does not submit another task.

**Settings → Refresh connection** checks which models are installed. A first inference can take longer. In a finding, **Explain / suggest** requests advisory information on demand. While a manual retry is pending, the last verified rule result for that finding can remain visible. After the 60-second page deadline, use **Refresh task** and choose explicitly whether to retry. The backend may still be running.

The [delivery guide](../docs/FINANCEFLOW_V1_DELIVERY.md) distinguishes the current candidate, verified workflows and open checks. The optional 100-order benchmark carries its own [data attribution and transformations](examples/PROVENANCE.json).
