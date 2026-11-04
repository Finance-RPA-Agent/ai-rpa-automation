# R3A local issue advice (backend candidate)

Base: `e1323637e456980eaf3fffdb0bf3804a92b9dc2b` (reviewed R2B).
This adds a read-only, on-demand backend endpoint. It does not implement R3B UI,
change review permissions, add a financial tool, approve anything or alter a task.

## Request and response

`POST /api/tasks/{job_id}/issues/{issue_id}/explanation`

Use the existing local session cookie and `X-Requested-With: FinanceFlow` header.
Origin/Host protections and authentication are inherited unchanged. The strict
body contains only a positive integer `revision` and the current 64-character
lowercase hexadecimal `evidence_digest`. Obtain both and the issue ID from the
current task view. Never use a runtime digest as a review credential.

The task must be `waiting_confirmation`, with exactly one matching current issue.
Task, revision, full issue-set evidence, archive quarantine and the hashes of the
stored source/reference/working files are checked before inference. These reads
use existing metadata and the immutable copies inside the workspace, not arbitrary
external paths. `detail`, `sync_archive`, `job_database`, business execution and
write methods are not called. Authentication reads do not create a new session.

The service releases its guard before invoking the provider. After inference it
rechecks the complete job/file identity and current evidence under the guard.
Review, cancellation, file changes, a changed issue set or detected quarantine
cause HTTP 409 and discard the result. Unknown task/issue is 404; stale evidence
is 409; invalid request shape is 422. Unauthenticated requests are 401 and rejected
local request boundaries are 403. Rejected requests do not invoke the model.

Successful HTTP responses have server-owned `task_id`, `revision`, `issue_id`,
`evidence_digest`, `facts`, `explanation`, `suggestions`, `selected_fact_ids` and
`advisory_only: true`. Each suggestion has `requires_human_decision: true`.

- `mode=local_model`, `status=advice_ready`, `model=qwen3.5:4b`: a model proposal
  passed validation and selected evidence focus and next steps.
- `mode=rules_only`, `model=null`: no accepted model proposal. `status_message`
  explicitly describes deterministic fallback. Reasons are `model_unavailable`,
  `model_timeout`, `model_busy`, `model_rejected`, `model_error`, `unsupported`,
  or `insufficient_evidence`. HTTP 200 does not imply successful AI inference.

No explanation is persisted or cached. GET/detail/report, review, run and recovery
do not automatically call the new provider method. Callers must treat the entire
response as advice, and must continue using existing human review independently.

## Trusted facts and model contract

`product/issue_explanation.py` contains fixed templates and suggestion text.
Supported row findings are amount/status mismatches, missing value, invalid amount
or date, no reference match, ambiguous reference and duplicate business key.
Unsupported/file-level findings produce explicit rules-only information without
an inference call. No-match is not a technical BI failure and does not imply zero.

Existing `parse_amount` rules are reused. Display-only bounds reject overly long
or nonfinite values without changing financial rules. Values and signed
source-minus-reference differences are rendered from Decimal strings with enough
local precision, including `9007199254740993.01` and negative differences. Neither
source nor reference is presumed correct. Unknown raw status strings are not
echoed. No raw cell messages, supplier/order identifiers, filenames, paths,
instructions, account credentials or review tokens enter the model context.

Only four model fields are allowed:

```json
{
  "summary_code": "SOURCE_REFERENCE_DISAGREE",
  "fact_ids": ["F_AMOUNT_SOURCE", "F_AMOUNT_BI", "F_AMOUNT_DIFF"],
  "suggestion_ids": ["REVIEW_BOTH_SOURCES"],
  "uncertainty": "ROOT_CAUSE_UNKNOWN"
}
```

All choices must belong to the server's per-issue enums. Additional/missing keys,
duplicate JSON keys, nonfinite numbers, unknown/duplicate IDs, false cause claims,
free text and oversized output are rejected. The model never supplies displayed
amounts or prose. The complete trusted explanation is rendered by the server;
the model selects evidence focus and safe recommendations only. Correction-related
options exist only for a true existing `can_correct`, an allowed field and an
available reference value. Options never grant execution authority.

## Local provider bounds

The new `OllamaProvider.explain_issue` uses the existing fixed
`http://127.0.0.1:11434` and `qwen3.5:4b`, checks the installed local tag, disables
environment proxies and redirects, and performs at most one `/api/chat` request.
It does not download models, change settings or retry. It acquires the existing
provider lock nonblocking; a busy provider produces rules-only fallback.

Generation uses `think=false`, `num_ctx=2048`, `num_predict=240`, temperature zero,
JSON schema and a maximum 16 KiB HTTP envelope / 4 KiB proposal. HTTP inactivity
timeouts are capped at 45 seconds (connect at 3), with an elapsed-budget check
between body chunks. This is not a hard 45-second wall-clock guarantee: a pending
network read can consume its own bounded timeout. No database transaction or
financial service guard is held while waiting. Existing provider methods are
unchanged. Loopback-only application calls do not establish system-wide zero egress.

## Validation and open gate (2026-10-30)

The initial two HTTP tests genuinely failed against the R2B baseline (404 missing
endpoint), then passed with the additive implementation. Dedicated tests cover
the protocol, actual validator findings, mocked transport failures, authentication,
multi-issue binding, injection, exact arithmetic, no-match, concurrent review /
cancel / evidence changes and actual SQLite/file preservation. They do not stand
in for live model inference. Original R1/R2B tests remain unchanged.

The real local availability probe found no listener on port 11434 and could not
confirm the installed model. Real inference is **NOT_RUN (0 chat calls)**. No
service was started and no settings/weights were changed. The R3A live-model gate
remains open; no full R3A acceptance is claimed. The return ZIP contains fresh
baseline and candidate regression logs and exact counts, rather than historical
results relabeled as new runs.

Further gates: GPT independent review; authorized live local inference when the
existing service is accessible; later R3B presentation and PR #3 combination
testing; real Windows GUI/model workflow and broader user/release acceptance.
No commit, publication, R3B or R4 is part of this candidate.
