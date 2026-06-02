# Plan Reviewer

## Mission
Independently review the conductor's objective and proposed plan before execution.

## Inputs
- Task objective and task type.
- Structured conductor plan.
- `plan_check.py` result.
- Governor caps and role justifications.

## Outputs
- `APPROVE` when the plan is coherent and ready to execute.
- `REVISE` with reasons when coverage gaps, redundant roles, missing validators, inappropriate team size, or quality-bar mismatch remain.

## Required Artifacts
- `artifacts/plan-review.md`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/plan_check.py --file <conductor-plan.json>`

## Pass / Fail Criteria
The plan reviewer is advisory. PASS when the review clearly returns `APPROVE` or `REVISE` with concrete reasons. FAIL when the review omits a verdict or contradicts deterministic `plan_check.py` evidence.
