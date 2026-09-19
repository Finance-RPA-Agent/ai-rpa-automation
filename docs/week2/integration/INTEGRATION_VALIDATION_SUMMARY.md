# Week 2 Integration Validation Summary

- Backend baseline: `6be9dc0d20a18d44d7f4f4343e4260dd00eb7b99`
- RPA baseline: `c1d21e166a38bc163e5e1296f1d60abe39f43838`
- Python: `3.12.14`

## Verified results

- Backend original tests: `5 passed`
- RPA pytest tests: `165 passed`
- Agent contract tests: `12 passed`
- Full pytest: `182 passed, 6 warnings`
- RPA local file tool unittest: `16 passed`
- HTTP TestClient smoke: `PASS`

The split Backend, RPA, and Agent results were obtained in the validated Week 2 integration worktree. The full pytest suite, RPA local-file unittest, and isolated temporary-SQLite HTTP smoke were run again successfully on the formal integration branch before commit.

This file records Week 2 local integration validation only. It does not represent production-environment validation.
