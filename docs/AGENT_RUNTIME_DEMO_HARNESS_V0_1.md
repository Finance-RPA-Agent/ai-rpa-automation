# Agent Runtime Demo Harness V0.1

This is an in-process, deterministic Runtime demonstration and regression
entry point. It calls `backend.app.services.agent_runtime.AgentRuntime`
directly. Runtime owns the workflow and dispatches the existing four tools.
There is no HTTP integration or real LLM, BI, OA, payment or financial approval.

From the repository root, with the existing project requirements installed:

```powershell
python -B -m scripts.run_agent_runtime_demo --scenario clean_success
python -B -m scripts.run_agent_runtime_demo --scenario validation_issue
python -B -m scripts.run_agent_runtime_demo --scenario bi_no_match
```

| Scenario | Synthetic input | Observed Runtime outcome | Simulated OA |
| --- | --- | --- | --- |
| `clean_success` | One valid CSV row and matching SQLite BI row | `completed` / `oa_result_archived` | One `reconciliation_result`, `archived`, `matched` |
| `validation_issue` | Negative amount `-1.00` | `waiting_confirmation` / `business_issue` | No writes |
| `bi_no_match` | Valid row with an order absent from seeded BI | `waiting_confirmation` / `business_no_match` | No writes |

Every run creates its own temporary CSV and SQLite database, creates the
existing schema in that new database, and seeds only synthetic data. Sessions,
engine and temporary files are closed/removed before returning. The project
default database, demo files and environment configuration are not used for
execution. No confirmation provider is injected and there is no approval flag.

Output is JSON containing `scenario`, `harness_status`, the actual Runtime
`task_status`, `classification`, `reason`, `error_code`, `confirmation_request`,
trace summary, actual OA rows and `demo_checks`. Trace attempts retain Runtime's
zero-based numbering: `0` is the initial call, `1` is the one permitted retry.
Expected outcomes only validate observations; they do not replace Runtime status.
An expected business wait is a passing demonstration, not a completed task.
Runtime status is not persisted into the seeded task row by this harness.

Exit codes: `0` means all scenario checks passed; `1` means Runtime failure,
unexpected observations, setup failure or trace write failure; `2` means invalid
CLI arguments. Always inspect both `harness_status` and `task_status`.

To explicitly keep full Runtime arguments/envelopes as JSON:

```powershell
python -B -m scripts.run_agent_runtime_demo --scenario clean_success --save-trace
```

The unique output path is printed as `trace_file`, under the repository's
already ignored `outputs/agent_runtime_demo/`. Nothing is saved by default.
Full trace may contain business data and local paths: keep it private, do not
treat it as a public log, and do not force-add it to Git. Temporary paths in a
saved trace refer to files already removed after the run.

Harness tests:

```powershell
python -B -m pytest tests/test_agent_runtime_demo.py -ra -p no:cacheprovider
```

Tests exercise the real CLI/dispatcher, temporary-file cleanup, output fidelity,
OA boundaries, optional trace saving and nonzero failures. Retry injection
exists only in tests, covering recovery and exhaustion after one retry.
There is no `technical_retry` CLI scenario or production fault switch.

This is an Agent-stage deliverable pending independent review. HTTP, login,
task/file ownership, status/trace/confirmation persistence and the trusted
confirmation provider remain Backend integration work. After interface alignment
and this review, implement that integration in a separately authorized stage;
then consider an LLM adapter. This harness does not complete the group's course
frontend/login/backend deliverables.
