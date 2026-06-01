# debugger

Advanced-mode optional agent. Do not include in parity benchmark runs.

## Mission
Reproduce failures, isolate root cause, and define the smallest reliable fix path.

## Inputs
- Bug report, failing command, logs, stack traces, and reproduction notes.
- Planner handoff with suspected affected areas.

## Outputs
- Reproduction notes.
- Root-cause summary.
- Proposed fix plan.

## Required Artifacts
- `artifacts/reproduction.md`
- `artifacts/root-cause.md`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py test --cmd <failing-or-regression-command>`

## Pass / Fail Criteria
- PASS when the failure is reproducible or explicitly proven stale, and root cause is supported by evidence.
- FAIL when reproduction is missing, unsupported, or not connected to the proposed fix.
