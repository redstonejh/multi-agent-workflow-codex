# Acceptance Summary

Final verdict: SHIP

## Checks Implemented
- `contrast`: WCAG contrast ratio for two hex colors, threshold 4.5 or 3.0 with `--large`.
- `a11y`: missing image alt, unlabeled controls, skipped heading levels, missing html lang, missing title, missing viewport meta.
- `budget`: local HTML/CSS/JS/assets byte budget and element/asset counts.
- `links`: internal links, anchors, and local assets resolve.
- `markup`: unclosed tags and duplicate ids using `html.parser`.

## Final Evidence
- `uv run python maw-tools/selftest_web_checks.py`: PASS, raw output recorded in `selftest_output.txt`.
- `uv run python maw-tools/selftest_all.py`: PASS, raw output recorded in `selftest_output.txt`.
- `uv run python -m unittest tests.test_maw_tools`: PASS, 45 tests.
- `uv run python maw-tools/validate_workflow_template.py`: PASS, 7 templates.
- `uv run python -m compileall maw-tools maw_cli tests examples`: PASS.
- `uv run python maw-tools/validate_handoffs.py runs/2026-06-02_add-front-end-ui-workflow_a8d3`: PASS.
- `uv run python maw-tools/acceptance_check.py --run runs/2026-06-02_add-front-end-ui-workflow_a8d3 --test-cmd "uv run python maw-tools\\selftest_all.py" --test-cwd .`: SHIP.

## Demo
Demo path: `examples/frontend_demo/`

The initial fixture is red for planted defects. The fixed `index.html` passes contrast, a11y, budget, links, and markup.

## Limits
`# MAW-TODO`: true visual regression, browser rendering checks, hard-gated aesthetic judgment, and real viewport screenshot testing.
