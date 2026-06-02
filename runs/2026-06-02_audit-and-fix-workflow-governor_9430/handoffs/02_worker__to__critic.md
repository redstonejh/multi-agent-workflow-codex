# Hand-off: worker -> critic  (run 2026-06-02_audit-and-fix-workflow-governor_9430, step 02)

## Task context
Review the implemented workflow cap policy.

## What I did
Updated plan-check rules, template caps, template validation, docs, tests, and package-data mirrors.

## Output / artifacts
- artifacts/worker-output.md  (implementation summary)
- artifacts/template-cap-audit.md  (template cap audit)

## Open questions / risks
Check that tests do not pass by omitting core roles and that the cap error is specific.

## Recommended next step
Review correctness, maintainability, and scope before acceptance.
