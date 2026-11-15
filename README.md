# Finance Flow

Finance Flow is a Windows-first desktop application for reconciling supplier orders against an imported BI reference file. It matches rows by supplier and order ID, shows differences to a reviewer, and saves completed results as a CSV, an audit report and local archive receipts. **Delivery V1 RC1** packages the existing Finance Flow 1.0 product for review.

## Start on Windows

1. Extract the source ZIP to a writable folder. Open PowerShell in the folder containing `start_product.py`. Use 64-bit Python 3.12. The desktop window uses Microsoft Edge WebView2.
2. Create the environment and run the supplied setup. Setup installs the Python packages listed in the product lock file. The first installation requires access to those packages.

   ```powershell
   py -3.12 -m venv .venv
   & ".\Setup Finance Flow.cmd"
   ```

3. Run `Start Finance Flow.cmd` and click **Enter demo**. The launcher now uses a separate demo workspace with a fixed display account; no password is required. To use your default browser instead of the desktop window, run the following from the same folder.

   ```powershell
   .\.venv\Scripts\python.exe start_product.py --demo --browser
   ```

4. For the first demonstration, open **New reconciliation**, select the source and BI files, then click **Start reconciliation**. The default fixed workflow needs neither Ollama nor separate plan approval; differences still require human review. The walkthrough gives the two input files, expected differences and final receipt counts. [Run the four-order demonstration](docs/FINANCEFLOW_V1_DELIVERY.md#four-order-demonstration)

## What to try

| Workspace | Task | Result |
| --- | --- | --- |
| **Reconciliations** | Select two files, start reconciliation and review a held difference. Optional custom plans remain available. | A signed-in reviewer decides which values to use. Completed tasks expose a reconciled CSV, JSON report and local receipts. |
| **Folder batches** | Select separate input and BI folders, scan the tables, confirm mappings and run. | Clean rows can complete while exceptions remain open. The Excel report shows row-level outcomes. |
| **Data assistant** | Choose an editable task example or write a request; inspect live stages, saved operations and the workbook. | General natural-language analysis needs the optional local Ollama model `qwen3.5:4b`. |

The linked guides cover account setup, input limits, backups, optional AI, sample provenance and the scope of delivery testing. Node is needed only for the JavaScript regression suites. [Product guide](product/README.md) · [Delivery notes and test record](docs/FINANCEFLOW_V1_DELIVERY.md)

The demo stores its files in `%LOCALAPPDATA%\FinanceFlow\demo`. The username and masked password on its entry page are display fields only. Existing owner accounts and ordinary workspace data remain available by running `.\.venv\Scripts\python.exe start_product.py` without `--demo`.

The launcher automatically checks the local Ollama service and starts an installed copy in the background if needed. It reuses a running service and does not download models or run inference during startup. If the model is missing, install it once with `ollama pull qwen3.5:4b`. Use `--no-auto-ollama` to skip automatic startup.

## Project background and legacy development API

Finance Flow grew from the ENT207 team's AI-RPA finance automation MVP. The original FastAPI backend covers Excel ingestion, task orchestration, simulated BI lookup and local OA workflows. The desktop product reuses the Agent Runtime and financial tools. Its primary entry point is `start_product.py` with its own authenticated product API. Supplier references are local files and archive receipts are local records. Financial payments and enterprise approvals take place outside this product.

Developers working on the original MVP can start its separate API in a disposable development environment from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for that API. For the Finance Flow review and all sample steps, use the product launcher on port 8877. The delivery notes identify the original team contribution, the assistant navigation work from leng327's PR #3 and the subsequent review work.

## Test the downloaded source

The full automated suites and example folders are included. See [TESTING.md](TESTING.md) for dependencies, one-command tests and manual input/BI examples. After setup, double-click Run Tests.cmd or run the Python test runner.
