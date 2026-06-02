---
name: frontend
description: Build and audit front-end/UI work with stdlib deterministic checks for contrast, static a11y, byte budgets, links, and markup.
---

# Front-End / UI Workflow Pack

Use this skill for front-end or UI work that should run through MAW with deterministic, browser-free checks.

## Workflow

1. `ui_builder` creates or edits the UI files and records changed files in `artifacts/ui-build.md`.
2. Auditors run deterministic checks:
   - `a11y_auditor`: `a11y` and `contrast`
   - `responsive_checker`: viewport metadata and local link/asset readiness
   - `perf_budgeter`: byte, element, and asset budgets
   - `markup_validator`: duplicate ids, unclosed tags, anchors, links, and local assets
3. The refine loop continues until `a11y`, `contrast`, `budget`, `links`, and `markup` pass.
4. `ux_critic` gives advisory critique after deterministic checks are green. Aesthetic judgment is advisory; hard PASS/FAIL comes from deterministic checks.
5. `acceptance_gate` reruns deterministic checks against on-disk files last and records `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

## Deterministic Commands

```bash
uv run python maw-tools/web_checks.py contrast --foreground "#111827" --background "#ffffff"
uv run python maw-tools/web_checks.py a11y examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py budget examples/frontend_demo/index.html --max-bytes 4096 --max-elements 80 --max-assets 5
uv run python maw-tools/web_checks.py links examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py markup examples/frontend_demo/index.html
```

## Limits

Browser rendering checks are not part of this pack. True visual regression, screenshot testing, and hard-gated aesthetic judgment are `# MAW-TODO`.
