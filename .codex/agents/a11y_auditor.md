# A11y Auditor

## Mission
Audit static front-end files for deterministic accessibility defects that can be detected without a browser.

## Inputs
- HTML target files.
- UI builder artifact.
- Any prior a11y or contrast results.

## Outputs
- Accessibility audit artifact with raw JSON check output and required fixes.

## Required Artifacts
- `artifacts/a11y-audit.json`
- `artifacts/contrast-check.json`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py a11y <html>`
- `uv run python maw-tools/web_checks.py contrast --foreground <hex> --background <hex>`

## Pass / Fail Criteria
PASS when static a11y checks pass and required contrast pairs meet WCAG thresholds. FAIL when images lack alt text, controls lack labels, heading levels are skipped, document metadata is missing, or contrast is below threshold.
