# Finance Flow 1.0 · Product guide

The desktop application keeps a local workspace for source files, BI exports, reconciliation tasks, review decisions, reports and archive receipts. For a first run, follow the [Windows setup](../README.md#start-on-windows) and the [four-order walkthrough](../docs/FINANCEFLOW_V1_DELIVERY.md#four-order-demonstration).

## Launch and data location

Use 64-bit Python 3.12 for the reviewed Windows setup. From the extracted project root, `Setup Finance Flow.cmd` uses a project-local `.venv` and installs [the pinned Python dependencies](requirements-lock.txt). To select the interpreter and install manually:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r product/requirements-lock.txt
```

Double-click `Start Finance Flow.cmd` for the WebView2 desktop window. The default server listens at `http://127.0.0.1:8877`. The default workspace is `%LOCALAPPDATA%\FinanceFlow`. To isolate the demonstration, choose a fresh directory outside the source folder. From PowerShell:

```powershell
$demo = Join-Path $env:LOCALAPPDATA "FinanceFlow RC1 Demo"
.\.venv\Scripts\python.exe start_product.py --browser --port 8877 --data-dir "$demo"
```

Use `--no-open` instead of `--browser` to run the service without opening a window. Choose a different free port if 8877 is occupied. Each data directory supports one active instance. Close the desktop window, or press Ctrl+C in the service/browser terminal to stop. Restart with the same data directory to read saved records.

On first use, create the workspace's owner account with a password of at least six characters. Subsequent launches use that account. Store the workspace on a device you control. Backups include business files and authentication metadata and belong outside source distributions. **Settings → Download backup** creates a snapshot when the worker is idle. With Finance Flow stopped, restore a verified backup only into a new, empty directory:

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

Create a task with one source and one reference. For a deterministic plan, clear **Use local AI to prepare the execution plan**, choose **Generate plan**, inspect it, then choose **Approve plan & run**. If a finding is held, open **Review findings** and compare the displayed source and BI values. A signed-in review decision is bound to the task revision and evidence. Correcting a finding creates a new working revision. Resume the task explicitly after all findings are resolved. The task page offers a JSON report, and a completed task additionally offers a reconciled CSV.

## Folder batch workflow

Open **Folder batches**, choose separate **Input folder** and **BI system folder**, then **Scan folders**. Inspect discovered tables, reference choices and mappings before selecting **Run ready tables**. Clean rows can produce local receipts while exception rows are held for review. After review, download the Excel report to inspect the reconciliation, exceptions and review history. Use the two sibling folders in the [synthetic review example](examples/review_case/README.md).

## Data assistant and optional local AI

General natural-language analysis uses Ollama on the same machine and the model `qwen3.5:4b`. If that functionality is needed, the operator must install Ollama, prepare the model separately and start the local service. On a machine with Ollama installed, `ollama pull qwen3.5:4b` downloads the weights. The source package contains neither the model nor its runtime. The deterministic reconciliation demo can be completed without either.

In **Data assistant**, select the input folder (and a separate BI folder for comparisons), start a conversation and inspect computed previews, tool history and reports. It captures copies of the selected inputs. The optional assistant can send bounded local samples and tool results to the local model. Reconciliation advice does not approve a correction or execute a payment.

**Settings → Refresh connection** checks which models are installed. A first inference can take longer. In a finding, **Explain / suggest** requests advisory information on demand. While a manual retry is pending, the last verified rule result for that finding can remain visible. After the 60-second page deadline, use **Refresh task** and choose explicitly whether to retry. The backend may still be running.

The [delivery guide](../docs/FINANCEFLOW_V1_DELIVERY.md) distinguishes the current candidate, verified workflows and open checks. The optional 100-order benchmark carries its own [data attribution and transformations](examples/PROVENANCE.json).
