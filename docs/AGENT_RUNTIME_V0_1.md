# Agent Runtime Skeleton V0.1

This is an in-process deterministic service, with no LLM, new HTTP route,
authentication layer, confirmation database or schema migration.

## Source review and integration boundary

- `prototypes/week2_agent_v1_1/README.md` explicitly says **PROTOTYPE / NOT
  PRODUCTION**. Its contracts/policy only classify already-returned results.
  The production modules migrate those semantics without importing prototypes.
- The existing `backend/app/routers/agent.py` parses description keywords,
  reads Excel using pandas, checks missing/negative/duplicate values itself,
  queries legacy `BIInventory`, and creates `OfficeApproval`. It does not
  implement the current four-tool runtime. Its inventory, duplicate-value and
  approval semantics differ from supplier/order reconciliation and simulated OA.
  It is preserved unchanged. Calling its existing endpoints does NOT call this
  new runtime.
- `backend/app/routers/tools.py` delegates to
  `backend.app.tools.dispatcher.execute_tool`. The runtime uses that same
  function with an explicit Backend database session and Settings.
- The four names remain exactly `read_data_file`, `validate_data`, `query_bi`,
  `submit_to_oa`. File loading, financial validation, BI queries, OA business
  rules and idempotency remain in their existing tool implementations.

## Modules and deterministic loop

- `agent_runtime_contracts.py`: whitelist, argument structure, mutually exclusive
  envelopes, consumed result fields, recursive rejection of authority claims.
- `agent_runtime_policy.py`: success/business issue/no-match/technical error/OA
  classification and at most one retry.
- `agent_runtime.py`: task context → validated next tool call → dispatcher →
  envelope/policy → next call / waiting / failed / completed. Each attempt is
  retained in `RuntimeResult.trace`, including errors and malformed receipts.

The normal plan is read → file validation → BI query for each row →
validation with all BI references → OA normal archive for each row. No write
occurs before both validations succeed. `record_status=matched` is the normal
OA archive outcome after the tool's clean comparison, as in the Week 2 contract
tests; input files and BI source statuses are not changed.
BI argument adaptation reuses the tools' existing `normalise_identifier` rule
for numeric Excel identifiers and preserves textual leading zeros.

Validation issues immediately enter `waiting_confirmation`. A successful BI
query with an empty records list becomes `business_no_match`; remaining
queries/final validation can collect the tool's findings, but no normal result
is archived. No-match is never converted to `BI_QUERY_FAILED`.

`BI_QUERY_FAILED`, `OA_SUBMISSION_FAILED` and `INTERNAL_ERROR` receive at most
one automatic retry per logical call. Non-retryable errors and invalid
contracts stop immediately. A second technical failure is returned as failed
with its code/message; a dispatcher exception is recorded as INTERNAL_ERROR,
not as a success.

## Backend call boundary

```python
from backend.app.services.agent_runtime import AgentRuntime

runtime = AgentRuntime(db=authorized_session, settings=tool_settings)
result = runtime.run({
    "task_id": existing_task.id,
    "file_path": backend_owned_upload_path,
    "operation_id": "task-42-revision-1",  # stable identifier for this revision
    # "sheet_name": "Sheet1",            # optional
})
```

Backend must resolve task/file access and provide an immutable upload revision
throughout a run. This service does not authenticate a task_id or user, acquire
file locks, persist task status, or accept an arbitrary caller-supplied plan.
The context accepts only task_id, file_path, operation_id and optional
sheet_name. Backend persists the returned outcome/trace as appropriate; traces
contain source data and should follow Backend's access and logging policy.

Normal OA operation IDs are `{operation_id}:result:{source_row}`. Exception IDs
are `{operation_id}:exception:{issue_index}`. Arguments are copied unchanged on
retry; returned OA operation_id and record_type must match the request.
Repeated execution of the same revision uses the tools' existing idempotency.
Changed data requires a new Backend revision/operation_id. A failed run may
already have earlier OA records committed; the trace preserves those receipts.
There is no claimed batch transaction or rollback of successful tool writes.

## Confirmation boundary

Without a trusted Backend `confirmation_provider`, issues/no-match remain
waiting and issue-related OA writes do not execute. Payload fields such as
approved, confirmed, their casing variants and nested verification claims
cannot supply permission. Serialized dictionaries/bools are also rejected as
provider results.

The optional constructor dependency receives a `ConfirmationRequest` containing
task_id, operation_id, an SHA-256 digest of current read/validation/BI evidence,
and purpose `archive_exceptions`. Backend must check its authenticated,
persisted human decision and return a matching `VerifiedConfirmationContext`
with a non-empty confirmation_id, or return None. The runtime checks exact
type, task, operation, evidence and purpose binding. The dataclass itself is
not proof of authentication: **never deserialize user JSON into it or implement
a provider that simply approves the request it receives**. This is a trusted
in-process Backend dependency, not an externally callable authorization API.

A matching confirmation permits only exception archiving as pending_review.
It never changes an issue into a reconciled normal record, performs payment or
grants final financial approval; the runtime remains waiting_confirmation.
Issues without usable business keys/file-level issues still require correction.
Every later run reads and validates the file again; stale evidence is rejected.
Backend confirmation storage and reviewer verification are integration
dependencies, intentionally outside this skeleton.

## Validation and limits

`tests/test_agent_runtime.py` uses real CSV files, temporary SQLite and the real
dispatcher for normal, issue, no-match, confirmation and replay paths. Fault
injection is restricted to technical failures/malformed receipts and records
actual calls; the OA lost-response test commits through the real tool first.

Run from the repository root, using a Python environment with requirements:

```text
python -B -m pytest tests/test_agent_runtime.py -ra -p no:cacheprovider
python -B -m pytest tests/test_agent_rpa_contract_v1_1.py -ra -p no:cacheprovider
python -B -m pytest tests/test_tools_dispatcher.py tests/test_tools_api.py tests/test_read_data_file.py tests/test_validate_data.py tests/test_query_bi.py tests/test_submit_to_oa.py -ra -p no:cacheprovider
python -B -m pytest -ra -p no:cacheprovider
python -B -m unittest discover -s rpa/tests -v
```

The existing conftest uses an isolated temporary database; full pytest selects
`tests/`, so RPA unittest counts must be reported separately. Exact commands,
exit codes and current-run results are in the return ZIP, not inferred here.

Development uses commit `979c559cb236106463a0b815fba469556ebf1ac6`, tree
`4dfd399c37b61a435f3efe609bb78f11297d4cfc`, under the user's content-equivalent
baseline authorization. Remote backend was checked as
`e4ac540d5e6807083edd754d813729a47749f1b5`; commit ancestry differs.
Before any later push/PR, recheck and synchronize the then-current backend,
and apply the reviewed runtime changes to that baseline. This task performs
no push, merge, PR or remote ref modification.
