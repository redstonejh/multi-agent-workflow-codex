# Front-End Demo

This demo is the planted red-to-green fixture for the MAW front-end/UI pack.

- `index.initial.html` intentionally includes a low-contrast button using `#9aa0a6` on `#ffffff`, an image without `alt`, a skipped heading level, missing viewport metadata, a broken internal anchor, and an over-budget inline blob.
- `index.html` is the fixed page used for green acceptance checks.
- `style.css` includes both the fixed styling and the initial low-contrast class so contrast checks can pin the bad pair.

Run checks:

```bash
uv run python maw-tools/web_checks.py contrast --foreground "#9aa0a6" --background "#ffffff"
uv run python maw-tools/web_checks.py a11y examples/frontend_demo/index.initial.html
uv run python maw-tools/web_checks.py budget examples/frontend_demo/index.initial.html --max-bytes 1200 --max-elements 80 --max-assets 5
uv run python maw-tools/web_checks.py links examples/frontend_demo/index.initial.html
uv run python maw-tools/web_checks.py a11y examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py budget examples/frontend_demo/index.html --max-bytes 4096 --max-elements 80 --max-assets 5
uv run python maw-tools/web_checks.py links examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py markup examples/frontend_demo/index.html
```

True visual regression requires a real browser. Aesthetic judgment is advisory. Browser visual regression is `# MAW-TODO`.
