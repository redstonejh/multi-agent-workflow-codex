# Responsive Checker

## Mission
Check static responsive-readiness signals that can be validated without rendering in a browser.

## Inputs
- HTML and CSS files.
- A11y audit results.
- Task-specific responsive requirements.

## Outputs
- Responsive check artifact that records viewport-meta status, local asset/link resolution, and any `# MAW-TODO` browser-only rendering gaps.

## Required Artifacts
- `artifacts/responsive-check.md`
- Raw `web_checks.py a11y` output when viewport metadata is being verified.

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py a11y <html>`
- `uv run python maw-tools/web_checks.py links <html>`

## Pass / Fail Criteria
PASS when viewport metadata is present, local links/assets resolve, and browser-only visual assertions are tagged `# MAW-TODO`. FAIL when deterministic responsive-readiness checks fail or rendering claims are made without browser evidence.
