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
   - `change_verifier`: `changed` and `style`
   - `style_drift_auditor`: `tokens`
3. The refine loop continues until `a11y`, `contrast`, `budget`, `links`, `markup`, `changed`, `style`, and `tokens` pass.
4. `visual_verifier` documents before/after evidence. Pixel/visual comparison is advisory, model judgment is advisory, and full automated screenshot diff inside MAW is `# MAW-TODO`.
5. `ux_critic` gives advisory critique after deterministic checks are green. Aesthetic judgment is advisory; hard PASS/FAIL comes from deterministic checks.
6. `acceptance_gate` reruns deterministic checks against on-disk files last and records `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

A run may only SHIP if the requested source/style change is demonstrably present and no design-token drift was introduced.

## Deterministic Commands

```bash
uv run python maw-tools/web_checks.py contrast --foreground "#111827" --background "#ffffff"
uv run python maw-tools/web_checks.py a11y examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py budget examples/frontend_demo/index.html --max-bytes 4096 --max-elements 80 --max-assets 5
uv run python maw-tools/web_checks.py links examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py markup examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py style examples/change_demo/style.after.css --selector ".btn" --property background
uv run python maw-tools/web_checks.py changed --before examples/change_demo/style.before.css --after examples/change_demo/style.after.css --selector ".btn" --property background --expected "#1a73e8"
uv run python maw-tools/web_checks.py tokens --token-file examples/change_demo/design-tokens.json examples/change_demo/style.after.css
```

## Limits

Browser rendering checks are not part of this pack. Automated browser screenshot diff, hard-gated visual judgment, and real rendered viewport comparison are `# MAW-TODO`.
