# Acceptance Summary

Final verdict: SHIP

## Checks Implemented
- `changed`: proves a file or selector/property target changed from a pre-change snapshot and optionally changed to an expected value.
- `style`: extracts the resolved static selector/property value from CSS source.
- `tokens`: checks CSS values against `design-tokens.json` and fails on design-token drift.

## Evidence
- `uv run python maw-tools/selftest_web_checks.py`: PASS, 17 assertions.
- `uv run python maw-tools/selftest_all.py`: PASS, 11 checks.
- `uv run python -m unittest tests.test_maw_tools`: PASS, 45 tests.
- `uv run python maw-tools/validate_workflow_template.py`: PASS, 7 templates.
- `uv run python -m compileall maw-tools maw_cli tests examples`: PASS.
- `uv run python maw-tools/validate_handoffs.py runs/2026-06-02_extend-frontend-pack-with-change_4e1a`: PASS.
- `uv run python maw-tools/acceptance_check.py --run runs/2026-06-02_extend-frontend-pack-with-change_4e1a --test-cmd "uv run python maw-tools\\selftest_all.py" --test-cwd .`: SHIP.

Raw required self-test output is recorded in `selftest_output.txt`.

## Demo
Demo path: `examples/change_demo/`

Happy path passes `style`, `changed`, and `tokens`. No-op and token-drift fixtures fail deterministically and should be treated as `NO-SHIP`.

## Limits
`# MAW-TODO`: automated browser screenshot diff, hard-gated visual judgment, and real rendered viewport comparison.
