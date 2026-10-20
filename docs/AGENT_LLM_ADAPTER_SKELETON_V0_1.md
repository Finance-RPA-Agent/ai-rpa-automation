# LLM Adapter Skeleton V0.1

This provider-neutral layer returns structured advice only. It has no external
provider, SDK, API key, HTTP endpoint, network request, dispatcher call or database
write. The existing Runtime and Demo Harness are unchanged and run independently.

The single module `backend/app/services/agent_llm_adapter.py` provides:

- `AgentModelContext`: Backend-built task description, typed task status, task
  tool allowlist, redacted `ToolResultSummary` values, business summary and an
  informational confirmation state. Raw envelopes and database objects are not
  accepted as tool summaries. Caller-owned text must be redacted before use;
  this module does not automatically find secrets in free text.
- `AgentModelProposal`: exactly `action`, `tool`, `arguments`, `reason`. All four
  fields are required. Non-tool actions require `tool=None`, `arguments={}`.
- `LLMAdapter` Protocol and `DeterministicStubAdapter`: repeatable local advice,
  with defensive copies. The default stub abstains with `fail_safe`.
- `validate_model_proposal`: strict second validation of typed proposals,
  dictionaries or JSON text; rejects duplicate JSON keys, non-finite data,
  missing/extra fields, nested authority and executable fields, invalid actions,
  fifth tools and invalid arguments using existing Runtime contracts.
- `get_model_advice`: optional, standalone orchestration seam. It catches provider
  exceptions as `provider_error` / `MODEL_PROVIDER_FAILED`, and invalid output as
  `model_output_invalid` / `MODEL_OUTPUT_INVALID`. Both return `fail_safe`; raw
  provider diagnostics and untrusted payloads are not logged or echoed.

`RuntimeProposalBoundary` is a separate, trusted, in-process policy object. It is
never sent to the model and must never be deserialized from model/frontend JSON.
The Runtime/Backend caller supplies its already selected next tool and exact
arguments, unresolved-business-issue flag and any trusted confirmation context.
The model cannot select a different stage, file, business key, task or operation.
This module does not compute a parallel workflow or a new reconciliation policy.

Minimal local example (no tool is executed):

```python
from backend.app.services.agent_llm_adapter import (
    AgentModelContext, AgentModelProposal, DeterministicStubAdapter,
    ModelAction, RuntimeProposalBoundary, get_model_advice,
)
from backend.app.services.agent_runtime_contracts import TaskStatus

context = AgentModelContext("Synthetic reconciliation", TaskStatus.RUNNING)
# Trusted deterministic caller selects this candidate; never model/user input.
arguments = {"supplier_id": "SUP-001", "order_id": "PO-001"}
boundary = RuntimeProposalBoundary(ModelAction.CALL_TOOL, "query_bi", arguments)
stub = DeterministicStubAdapter(AgentModelProposal(
    ModelAction.CALL_TOOL, "query_bi", arguments, "Need the BI reference."
))
advice = get_model_advice(context, boundary, stub)
assert advice.classification == "model_proposal_valid"
```

Accepted actions are exactly `call_tool`, `request_confirmation`, `complete` and
`fail_safe`. Allowed names are exactly the existing four tools, optionally reduced
by the task allowlist. A valid proposal is not an execution or authorization grant.

- Failed/cancelled tasks may only abstain. Completed tasks cannot propose tool
  calls. `complete` can only acknowledge a Runtime already marked `completed`,
  with the trusted boundary also permitting it and no unresolved findings.
  A model cannot mark a running task complete or erase business no-match.
- `request_confirmation` is only a request; it neither changes task state nor
  creates `VerifiedConfirmationContext`. Even a `verified` informational label
  cannot authorize a write.
- Unresolved issues/no-match prevent ordinary tool calls and normal OA result
  proposals. Exception archive proposals require typed Backend confirmation
  bound to task, immutable operation, evidence digest and `archive_exceptions`
  purpose, plus the trusted exact exception candidate. No serialized dictionary
  or boolean is a grant. Valid exception advice still performs no write and
  grants no final financial approval.
- Normal reconciliation result candidates remain the deterministic caller's
  responsibility after successful reconciliation; they cannot be used to resolve
  outstanding issues. Runtime/tools retain financial validation and idempotency.

The caller remains responsible for authenticated task/file access, redaction,
freshness and deriving a correct boundary from current policy. The typed boundary
and confirmation dataclasses are not authentication credentials. At actual use,
Runtime must revalidate the proposal and its own trusted confirmation provider.
Do not add a generic “execute validated model arguments” shortcut.

This skeleton exposes an advisory seam without wiring a model into the Runtime
loop. Future step-level integration must expose deterministic candidates without
rewriting the reviewed Runtime. No automatic fallback execution happens here:
the caller can ignore advice and run the existing deterministic Runtime. A Python
adapter implementation is trusted code, not a sandbox; this validator contains
untrusted model data, not a malicious Python plugin.

Run `python -B -m pytest tests/test_agent_llm_adapter.py -ra -p no:cacheprovider`.
Tests cover malicious outputs, confirmation binding, task/step restrictions,
provider faults, deterministic stub behavior, no dispatch from advice and real
Runtime/Harness operation after provider failure. Existing test files are intact.

Current limits: no real provider selection, timeout/token budget, external secret
transport, HTTP/auth/persistence integration or benchmark. Do not start real
provider trials from this patch alone. After independent review, first agree the
step-level Runtime seam and Backend authority/redaction contract; then authorize
a separate bounded provider trial. No claims of a production LLM Agent are made.
