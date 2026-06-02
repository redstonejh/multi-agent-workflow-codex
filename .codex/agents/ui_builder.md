# UI Builder

## Mission
Create or edit front-end files for the selected workflow while keeping changes scoped, accessible, and compatible with deterministic checks.

## Inputs
- Task brief and acceptance criteria.
- Existing HTML, CSS, JavaScript, assets, and design constraints.
- Prior audit results from `maw-tools/web_checks.py`.

## Outputs
- Updated on-disk UI files.
- Artifact summarizing changed files, intended behavior, and unresolved `# MAW-TODO` items.

## Required Artifacts
- `artifacts/ui-build.md`
- Updated UI files under the task target path.

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py contrast --foreground <hex> --background <hex>`
- `uv run python maw-tools/web_checks.py a11y <html>`
- `uv run python maw-tools/web_checks.py budget <html>`
- `uv run python maw-tools/web_checks.py links <html>`
- `uv run python maw-tools/web_checks.py markup <html>`

## Pass / Fail Criteria
PASS when the UI files are updated, deterministic failures have been addressed or explicitly tagged `# MAW-TODO`, and the next auditor can rerun checks from recorded commands. FAIL when changes are incomplete, unscoped, or unverified.
