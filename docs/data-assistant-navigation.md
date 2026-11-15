# Data assistant: navigation recovery and asynchronous state protection

## Problem and scope

Previously, opening a conversation, visiting Settings and returning through the
Data assistant sidebar could show a blank task form. The sidebar omitted the
conversation ID and the frontend discarded its current selection. This could
make an accepted task appear lost even though its backend turn still existed.

This change fixes the frontend selection and asynchronous UI lifecycle. It does
not change backend task execution, financial rules, API contracts or database
schemas. Folder batches and independent financial task workflows are outside
this change.

## Resulting behavior

- Returning through the sidebar restores the explicitly selected conversation
  and reads its latest backend state, including progress, review, completion,
  failure or cancellation.
- New conversation preserves its blank selection and in-page draft when leaving
  and returning. Selecting another conversation remains an explicit choice.
- Delayed Submit/Retry responses cannot redirect a later navigation, clear a
  newer draft or overwrite another conversation. An accepted retry is refreshed
  when its conversation is viewed again, including an A-to-B-to-A selection.
- Logout and current-session authentication failures invalidate old request
  continuations. Old callbacks cannot repopulate cleared state or release a
  later operation's busy flag.
- Navigation reads, post-acceptance refreshes and polling share a detail-write
  gate. Only an eligible current-view read can acquire a sequence, and only the
  latest still-valid read can apply its result. Older responses cannot roll
  running progress back or revive an already completed turn.
- A current detail-refresh failure is reported. Its already accepted turn ID
  remains available for normal polling recovery; recovery does not submit the
  turn again. Errors belonging to an obsolete view are ignored.

The implementation separates navigation identity, login lifetime, selection
ownership, operation/busy ownership and detail-read ordering. Submit and Retry
share the corresponding guards and detail application code.

## Regression test

From the repository root, using an existing Node.js runtime:

```sh
node tests/assistant-navigation.cjs
```

The test uses only built-in Node modules. It executes the actual frontend in a
VM with synthetic DOM, API responses, explicit interval ticks and delayed
response gates. It runs 51 scenario executions, including overlapping coverage
of sidebar recovery, drafts, A/B switching, stale success/error responses,
logout/re-login, retry recovery and detail-read ordering. Each scenario has a
host-side timeout; the runner verifies that every registered scenario executes.

No browser, product server, model, real account or business data is used. Native
`hashchange` events are not automatically dispatched by this harness, so the
suite does not replace desktop/WebView testing.

## Validation and remaining work

Code review and the synthetic regression suite have passed locally. Real
desktop GUI verification of this candidate is still pending. Before merging,
check a running or completed task through Settings and back, a New conversation
draft through the same navigation, and switching between saved conversations.

Selection and draft memory are scoped to the current frontend page lifetime.
This change does not promise recovery after page refresh/application restart or
multi-window synchronization.

Only the two frontend sources, the regression test and this document are part of
the change. Local launchers, Python environments, Ollama/model files, data,
logs and local verification artifacts are excluded.
