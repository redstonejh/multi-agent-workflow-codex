# Style Drift Auditor

## Mission
Prevent front-end edits from introducing values outside the declared design tokens.

## Inputs
- `design-tokens.json`.
- CSS files touched by the UI change.
- Change verifier output.

## Outputs
- Token drift audit artifact with raw `tokens` output.

## Required Artifacts
- `artifacts/style-drift-audit.json`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py tokens --token-file <design-tokens.json> <css...>`

## Pass / Fail Criteria
PASS when all scanned CSS values are in the token set or accepted built-in neutral values. FAIL when any off-token value is detected.
