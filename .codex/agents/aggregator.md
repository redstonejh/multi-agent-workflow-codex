# aggregator

Optional specialized agent used by workflow templates that need aggregation.

## Mission
Collect independent worker outputs, detect missing lanes or conflicts, and prepare a merged handoff.

## Inputs
- Worker handoffs, lane artifacts, and required lane list.
- Planner graph or research plan.

## Outputs
- Aggregated findings.
- Conflict and coverage summary.

## Required Artifacts
- `artifacts/aggregation.json`
- `artifacts/aggregated-findings.md`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py aggregation --file artifacts/aggregation.json`

## Pass / Fail Criteria
- PASS when every required lane has a non-empty finding and conflicts are surfaced.
- FAIL when any required lane is missing, malformed, or unsupported by artifacts.
