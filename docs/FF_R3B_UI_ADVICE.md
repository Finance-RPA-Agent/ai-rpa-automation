# R3B: on-demand issue advice (local candidate)

In a task's Findings tab, each existing issue on a task awaiting confirmation has an **Explain / suggest** button. Opening the page, refreshing or polling never requests an explanation. This feature uses the reviewed R3A endpoint with only the current revision and full evidence digest. Financial values are displayed as exact strings; the browser performs no financial calculations for advice.

Successful `local_model/advice_ready` responses show **Local AI · validated evidence selection**. `rules_only` responses show **Rule-based only · deterministic fallback**, with their explicit reason. Both retain the unknown-cause and human-decision warnings. HTTP 200 alone does not establish AI success. The model selects approved evidence; the backend produces deterministic explanatory text. No action in the advice panel approves a correction or executes a task.

`issue-advice.js` owns validation, escaped rendering and request lifetime. It requires the reviewed response shape, exact task/issue/revision/digest, known fact sources and suggestions, `advisory_only=true` and human decisions. Missing, unknown or inconsistent fields fail closed. All response strings are escaped, including amounts, labels and suggested text; no URLs or HTML are activated.

An in-flight request is tied to the task object, revision, digest, issue, route/view/hash, session object, username and navigation token. Navigation, logout, refresh, changing selection, review and cancellation invalidate advice. Duplicate clicks while pending produce no additional request. A stale 401 is discarded before the shared API helper can sign out a newer session. Only advice callers supply this optional guard; existing callers retain their behavior.

The browser waits at most 60 seconds, then aborts its request and reports a page timeout. This does not change the backend's 45-second provider limit and does not guarantee cancellation of work already accepted by the backend. There are no retries, preloads or automatic warmups. Users must independently verify the sources and use the separate, unchanged Review correction flow. The pending state is accessible and leaves navigation available.

## Validation and integration boundary

Run the synthetic frontend checks with `node --test tests/test_finance_r3b_frontend.cjs`. They exercise exact requests, validation, decimal strings, fallbacks, injection, duplicates/multiple issues, error statuses, timeout, selection and stale navigation/session responses, including the actual shared API helper. No network or model is used by these Node tests.

The delivery evidence records the actual Windows pytest, RPA unittest, static asset and desktop Edge results, including failed development attempts. GUI tests use the real app and R3A service with an isolated synthetic provider/data directory; they are not a new real-model acceptance. Native WebView-specific behavior is NOT_VERIFIED.

PR #3 owns separate app.js/assistant.js navigation work. No unmerged PR implementation has been copied. The existing navigation and human-review function bodies are preserved; localized advice hooks and the API guard are integration points. Review must retain both PR #3 session/navigation guards and the advice ownership check before 401 handling and after response parsing. The exact PR head was absent from local repositories, so `PR3_COMBINATION_NOT_RUN` remains an explicit release gate: compose the independently accepted changes in a future authorized isolated copy, then run the PR navigation tests and all R3B tests/GUI scenarios before publication.

This candidate is uncommitted and awaits independent GPT review. No backend/rules/R3A tests, model files, other worktrees, stable preview or project logs are changed. The audit ZIP contains the evidence and a proposed log event only.
