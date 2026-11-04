# Finance Flow

Finance Flow is a Windows-first desktop application for reconciling supplier orders against an imported BI reference file. It matches rows by supplier and order ID, shows differences to a reviewer, and saves completed results as a CSV, an audit report and local archive receipts. **Delivery V1 RC1** packages the existing Finance Flow 1.0 product for review.

## Start on Windows

1. Extract the source ZIP to a writable folder. Open PowerShell in the folder containing `start_product.py`. Use 64-bit Python 3.12. The desktop window uses Microsoft Edge WebView2.
2. Create the environment and run the supplied setup. Setup installs the Python packages listed in the product lock file. The first installation requires access to those packages.

   ```powershell
   py -3.12 -m venv .venv
   & ".\Setup Finance Flow.cmd"
   ```

3. Run `Start Finance Flow.cmd` and create a local owner account on first use. To use your default browser instead of the desktop window, run the following from the same folder.

   ```powershell
   .\.venv\Scripts\python.exe start_product.py --browser
   ```

4. For the first demonstration, use **Reconciliations** and clear **Use local AI to prepare the execution plan** when creating each task. This route needs neither Ollama nor a model download. The walkthrough gives the two input files, expected differences and final receipt counts. [Run the four-order demonstration](docs/FINANCEFLOW_V1_DELIVERY.md#four-order-demonstration)

## What to try

| Workspace | Task | Result |
| --- | --- | --- |
| **Reconciliations** | Import two files, inspect the plan and review a held difference. | A signed-in reviewer decides which values to use. Completed tasks expose a reconciled CSV, JSON report and local receipts. |
| **Folder batches** | Select separate input and BI folders, scan the tables, confirm mappings and run. | Clean rows can complete while exceptions remain open. The Excel report shows row-level outcomes. |
| **Data assistant** | Ask a question about a captured folder and inspect the operations, evidence and workbook. | General natural-language analysis needs the optional local Ollama model `qwen3.5:4b`. |

The linked guides cover account setup, input limits, backups, optional AI, sample provenance and the scope of delivery testing. Node is needed only for the JavaScript regression suites. [Product guide](product/README.md) · [Delivery notes and test record](docs/FINANCEFLOW_V1_DELIVERY.md)

## Project background and legacy development API

Finance Flow grew from the ENT207 team's AI-RPA finance automation MVP. The original FastAPI backend covers Excel ingestion, task orchestration, simulated BI lookup and local OA workflows. The desktop product reuses the Agent Runtime and financial tools. Its primary entry point is `start_product.py` with its own authenticated product API. Supplier references are local files and archive receipts are local records. Financial payments and enterprise approvals take place outside this product.

Developers working on the original MVP can start its separate API in a disposable development environment from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for that API. For the Finance Flow review and all sample steps, use the product launcher on port 8877. The delivery notes identify the original team contribution, the assistant navigation work from leng327's PR #3 and the subsequent review work.
