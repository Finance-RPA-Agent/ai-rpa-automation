# Finance Flow R2B reliability candidate

Base: `94cc43c4c93c379bf6443c7cf3aadfb011dbf4f0`; branch `feature/financeflow-improvements-20261030`. Candidate only, independent GPT review pending; no commit/publication.

## Scope and behavior

- G01: product review credentials bind server task/revision, immutable source/reference identities and hashes, working revision and the complete issue set. POST validates the physical files and recomputes the credential. A legacy waiting task can refresh its credential through a read-only GET; old credentials do not approve anything.
- G03: finite Decimal fractions and integers outside the browser safe integer range serialize as exact decimal text. Safe integral Decimal values retain integer compatibility. Nonfinancial existing JSON types remain unchanged. All shared consumers (BI query, validation, file reader and OA submission) are covered.
- G02: startup inspects only the existing controlled per-task SQLite database in read-only/query-only mode. Receipt task/revision/operation/row/content identities are validated before a central BEGIN IMMEDIATE transaction checks all conflicts and inserts missing mirrors. No OA operation or Agent run is performed by recovery. Missing databases are not created. Repeated recovery retains existing records and interrupted/cancelled states. A conflict blocks affected detail/report and global archive reads with 409; no silent overwrite.
- G04: idle cancellation saves Cancelled stage and clears cancellation-pending text. Existing running cancellation, audit history, receipts and terminal run boundaries remain.

The user explicitly extended the file scope for `product/excel_report.py:numeric_decimal` after a real stored-XLSX counterexample. Numeric cells are retained only when their openpyxl 16-significant-digit serialization equals the original Decimal exactly; otherwise the existing exact text fallback is used. Values such as 9007199254740993.01 and 9999999999999.12 are preserved. Text amounts may not participate in Excel numeric formulas such as SUM; this format limitation is intentional and documented. Tests inspect actual saved OOXML and exact Decimal arithmetic; no GUI/native Excel formula recalculation is claimed.

No amount tolerance, limit, two-decimal validation, financial rule, authentication policy, runtime permission, schema, frontend, model or dependency change. Existing tests remain unchanged.

## Reproduction and evidence

Use an isolated data/TMP/default-backend directory and the repository's existing dependencies. Run `python -m pytest -q`, `python -m unittest discover -s rpa/tests -v`, Python compile and `git diff --check`. Targeted new files are `tests/test_finance_r2b_{review,money,recovery,cancel,smoke}.py`. The Node executable is used only to evaluate the unchanged frontend amount formatter, not a browser/model call. R2B_ARTIFACTS optionally preserves synthetic evidence; R2B_EXPECT_SOURCE checks import identity.

The delivery ZIP contains all commands, stdout/stderr/JUnit, identities, before/after patch, old failures, real API/SQLite/receipt/CSV/JSON/XLSX results and a SHA256 manifest. Baseline failures: G01 9/11; G03 24/25, plus 8/31 after newly discovered report boundaries; G02 18/21; G04 3/5. Initial source-import guard and NumPy test-harness errors are separately retained, not counted as business failures. The pre-Excel-fix full run preserved 8 failures/604 passes. Final results are in TEST_RESULTS.json and README_执行报告.md of the delivery.

Real local model, Windows GUI and enterprise OA were NOT_RUN and are not claimed accepted. R1 and protected worktrees remain separate. Do not automatically commit, publish, merge or start another improvement stage from this candidate.
