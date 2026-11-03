# R3B-2 isolated combination candidate

This is a filesystem-only review candidate, not a merge, commit, or deployed release.
Base: R3A `2d3ebeffdb2eecc1f0ccc136a0b28d5f13e582de` plus the six independently reviewed R3B files.
Navigation source: PR #3 by **leng327**, exact commit `29392fa72b103f4cc6d82436a5d6617a6c85a1d3`, retrieved through the read-only GitHub connector on 2026-11-03 11:19:30 UTC.

## Source ownership and resolution

PR #3 contributes the original navigation/session ownership logic, complete assistant.js, navigation tests and navigation documentation. Those last three files remain byte-identical to the pinned upstream files. R3B contributes the unchanged advice component, stylesheet, HTML script loading, 58 frontend tests and R3B documentation.

Only app.js requires semantic integration. Its API helper retains PR #3 sessionEpoch handling and adds the R3B request ownership check before handling a 401 and after parsing JSON. A stale advice request cannot sign out a newer session. Current 401 responses still clear PR #3 conversation memory. Advice state invalidation covers navigation, logout, task selection and independent correction submission. Advice does not submit or approve a correction.

The initial patch check failed at the shared API hunk. Manual integration began with exact PR #3 app.js and transplanted the reviewed R3B additions; no automatic merge was claimed. The unmodified PR #3 harness intentionally loads only two scripts. The first run therefore exposed a missing optional advice component. app.js now fails closed with an explicit component-unavailable message while keeping navigation operational. A separate new suite loads all three real scripts, replays all 51 PR #3 scenarios, and adds 10 cross-feature cases. Original tests were not weakened or edited. Initial new-harness URL-global failure and corrected results are preserved.

## Executed verification

- Original PR #3 navigation suite: 51/51.
- Original reviewed R3B frontend suite: 58/58.
- All-component combination suite: 61/61 (51 upstream scenarios plus 10 new scenarios).
- Complete pytest: 721 passed, 5 warnings; RPA unittest: 16 passed.
- Original financial harness: 4-row and 100-row smoke cases passed within pytest, including JSON/CSV/Excel outputs.
- app.js, assistant.js and issue-advice.js syntax checks passed.
- Real Edge GUI used isolated synthetic tasks: A-B-A running task restoration, draft/settings round trip, on-demand advice, rule fallback, 409, 60-second page deadline, HTML text escaping, precise large amounts, logout while pending, and independent correction.
- Real pywebview 6.2.1 / EdgeChromium native desktop window used the original start_product.py entrypoint with a process-local synthetic provider fixture: session navigation, advice, fallback, 409, independent correction, and sign-out were observed.

All GUI model responses are synthetic; strings such as local_model and qwen3.5:4b in the response schema are fixture output, not live model execution. Real Ollama chat/generate requests: zero. Native and browser synthetic data stores are separate.

## Limits

Login uses the real local login API through a fixture session bootstrap. Manual credential entry in the native login form is NOT_VERIFIED. Native full application restart/session persistence and multiwindow use are NOT_VERIFIED. The first hidden native launch did not expose an operable window; its evidence is retained. The subsequent visible pythonw native launch succeeded. These results do not authorize changing the original worktree, committing the combination, merging PR #3, or starting R4.
