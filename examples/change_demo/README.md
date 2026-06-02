# Change Verification Demo

Request: make the primary button blue (`#1a73e8`) and larger.

Fixtures:

- `style.before.css`: old gray, smaller button.
- `style.after.css`: requested blue and larger button.
- `style.noop.css`: claimed edit was not applied; `changed` must fail and the workflow should be `NO-SHIP`.
- `style.drift.css`: changed to an off-palette blue (`#0057ff`); `tokens` must fail and the workflow should be `NO-SHIP`.
- `design-tokens.json`: allowed color, spacing, font size, font, and related style values.

Happy path:

```bash
uv run python maw-tools/web_checks.py style examples/change_demo/style.before.css --selector ".btn" --property background
uv run python maw-tools/web_checks.py style examples/change_demo/style.after.css --selector ".btn" --property background
uv run python maw-tools/web_checks.py changed --before examples/change_demo/style.before.css --after examples/change_demo/style.after.css --selector ".btn" --property background --expected "#1a73e8"
uv run python maw-tools/web_checks.py changed --before examples/change_demo/style.before.css --after examples/change_demo/style.after.css --selector ".btn" --property font-size --expected "1.125rem"
uv run python maw-tools/web_checks.py tokens --token-file examples/change_demo/design-tokens.json examples/change_demo/style.after.css
```

No-op failure:

```bash
uv run python maw-tools/web_checks.py changed --before examples/change_demo/style.before.css --after examples/change_demo/style.noop.css --selector ".btn" --property background --expected "#1a73e8"
```

Token drift failure:

```bash
uv run python maw-tools/web_checks.py tokens --token-file examples/change_demo/design-tokens.json examples/change_demo/style.drift.css
```

Pixel/visual comparison is advisory. Model judgment is advisory. Full automated screenshot diff inside MAW is `# MAW-TODO`. Real rendered viewport comparison is `# MAW-TODO`.
