# Run 2026-06-02_audit-and-fix-workflow-governor_9430

- Task: audit and fix workflow governor caps for specialist agents
- Created: 2026-06-02 10:45
- Status: SHIP

## Conductor plan
- Proposed plan: `artifacts/conductor-plan.json`
- Plan check result: `artifacts/plan-check.json`
- Plan review: `artifacts/plan-review.md`
- Final accepted plan: `artifacts/final-accepted-plan.json`
- Revision count: 0

Policy selected: default caps apply to generic core-agent runs; specialist
workflow templates declare explicit larger caps and `plan_check.py` rejects
specialist plans with insufficient headroom.

## Final result summary
Implemented cap policy, template caps, cap validation, docs, and tests. Final
acceptance verdict: SHIP.
