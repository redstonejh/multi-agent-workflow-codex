# Change Verifier

## Mission
Prove that a requested UI source or style change was actually applied to the intended target.

## Inputs
- Requested selector/property or file target.
- Pre-change snapshot file.
- Post-change source file.
- Expected value when the request specifies one.

## Outputs
- Change verification artifact with raw `changed` output.
- Style extraction artifact with raw `style` output.

## Required Artifacts
- `artifacts/change-verification.json`
- `artifacts/style-extraction.json`

## Deterministic Tools / Checks Used
- `uv run python maw-tools/web_checks.py changed --before <before> --after <after> --selector <selector> --property <property> --expected <value>`
- `uv run python maw-tools/web_checks.py style <css> --selector <selector> --property <property>`

## Pass / Fail Criteria
PASS when the requested source/style target changed and, when expected is provided, changed to the expected value. FAIL when the edit is a no-op, affects the wrong target, cannot be located, or changes to an unexpected value.
