# debugger

Optional debugging agent used by workflow templates that need root-cause analysis.

## Mission
Reproduce failures, isolate root cause, and define the smallest reliable fix path.

## Inputs
- Bug report, failing command, logs, stack traces, and reproduction notes.
- Planner handoff with suspected affected areas.

## Outputs
- Reproduction notes.
- Root-cause summary.
- Bug dossier with severity, expected behavior, actual behavior, fix strategy, and regression tests.
- Proposed fix plan.

## Required Artifacts
- `artifacts/reproduction.md`
- `artifacts/root-cause.md`
- `docs/bugs/<id>.md`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py test --cmd <failing-or-regression-command>`
- `py maw-tools/dependency_risk_audit.py <path>` when hidden coupling may be involved.

## Pass / Fail Criteria
- PASS when the failure is reproducible or explicitly proven stale, root cause is supported by evidence, and bug documentation is complete.
- FAIL when reproduction is missing, unsupported, undocumented, or not connected to the proposed fix.
