# Hand-off: conductor -> plan_reviewer  (run 2026-06-02_audit-and-fix-workflow-governor_9430, step 01)

## Task context
Audit and fix workflow governor caps so specialist workflows have explicit, validated headroom.

## What I did
Inspected plan-check policy and workflow templates, then proposed a code-task implementation plan with explicit caps.

## Output / artifacts
- artifacts/conductor-plan.json  (structured proposed plan)
- artifacts/plan-check.json  (hard gate result)
- artifacts/template-cap-audit.md  (template cap inspection)

## Open questions / risks
Confirm the selected policy keeps default caps generic while requiring explicit template caps for specialist workflows.

## Recommended next step
Return APPROVE or REVISE with concrete cap-policy concerns.
