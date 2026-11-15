# Testing Finance Flow

The repository includes the complete `tests/` and `rpa/tests/` suites, plus the example folders below. Generated workbooks, local accounts, workspace databases, model weights and virtual environments are not distributed as test data.

## Install and run on Windows

Use Python 3.12 and Node.js (for the JavaScript suites). From the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r product/requirements-lock.txt
.\.venv\Scripts\python.exe run_tests.py
```

After setup, double-click **Run Tests.cmd** for the same test run. For Python suites only, use:

```powershell
.\.venv\Scripts\python.exe run_tests.py --python-only
```

The runner stops on a failing suite and returns a nonzero exit code. It runs pytest, the RPA unittest suite, the assistant navigation suite and all other JavaScript `.cjs` suites. JavaScript tests use Node built-ins; `npm install` is not needed. Tests use temporary synthetic workspaces and controlled model responses. They do not require an installed Ollama model or a GPU and do not modify your signed-in product workspace. They do not replace native GUI, live-model or real-user acceptance testing.

## Manual sample folders

Paths below are relative to the downloaded repository. Choose the actual absolute paths through the application's folder picker.

| Scenario | Input folder | BI system folder |
| --- | --- | --- |
| Larger reconciliation example | `product/examples/pending_files` | `product/examples/bi_system` |
| Four-order human review | `product/examples/review_case/pending_files` | `product/examples/review_case/bi_system` |
| Combine input tables | `product/examples/pending_files` | Leave empty |

The larger example has two input CSVs (100 rows in total) and one BI reference CSV. Its public-source attribution and deliberate changes are in the example `PROVENANCE.json` files. The four-order example is synthetic and includes an amount difference, payment-status difference and missing supplier name; see its README for the expected review sequence.

Launch **Start Finance Flow.cmd**, click **Enter demo**, then try **Data assistant** or **Folder batches**. Natural-language analysis requires the separately installed `qwen3.5:4b` model; the launcher starts an installed Ollama service automatically. **New reconciliation > Start reconciliation** uses fixed rules without a model.

Generated Excel reports go to the current workspace's `exports/Reports`, outside the sample folders. Use **Open reports folder** to find them. Start a new conversation after changing sample files because existing conversations retain immutable captures.

## Focused checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_usability.py tests/test_demo_login.py tests/test_model_startup.py tests/test_report_locations.py
node --test tests/usability.cjs tests/demo-login.cjs tests/report-folders.cjs
```
