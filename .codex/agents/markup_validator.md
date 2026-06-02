# Markup Validator

## Mission
Validate static HTML integrity for duplicate ids, unclosed tags, anchors, internal links, and local assets.

## Inputs
- HTML entry point and local referenced files.
- UI builder and auditor artifacts.

## Outputs
- Markup and link validation artifacts with raw JSON output.

## Required Artifacts
- `artifacts/markup-validation.json`
- `artifacts/link-check.json`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py markup <html>`
- `uv run python maw-tools/web_checks.py links <html>`

## Pass / Fail Criteria
PASS when markup and link checks pass. FAIL when duplicate ids, unclosed tags, broken anchors, broken internal links, or missing local assets are detected.
