# Perf Budgeter

## Mission
Enforce local byte, element, and asset budgets for front-end work using deterministic filesystem checks.

## Inputs
- HTML entry point.
- Budget limits from the task or workflow template.
- Local CSS, JavaScript, and asset references.

## Outputs
- Budget report with raw JSON output and any required reductions.

## Required Artifacts
- `artifacts/perf-budget.json`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py budget <html> --max-bytes <n> --max-elements <n> --max-assets <n>`

## Pass / Fail Criteria
PASS when total local bytes, element count, and asset count are within configured limits. FAIL when any budget is exceeded or unresolved assets prevent reliable measurement.
