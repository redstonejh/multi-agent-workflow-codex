# Demo Red-To-Green Raw Output

## Initial Contrast
Command: `uv run python maw-tools\web_checks.py contrast --foreground "#9aa0a6" --background "#ffffff"`

Exit code: 1

```json
{
  "background": "#ffffff",
  "check": "contrast",
  "foreground": "#9aa0a6",
  "large": false,
  "passed": false,
  "ratio": 2.640526,
  "threshold": 4.5
}
```

## Initial A11y
Command: `uv run python maw-tools\web_checks.py a11y examples\frontend_demo\index.initial.html`

Exit code: 1

```json
{
  "check": "a11y",
  "file": "examples\\frontend_demo\\index.initial.html",
  "passed": false,
  "violation_count": 4,
  "violations": [
    {"message": "html element is missing lang", "type": "missing_html_lang"},
    {"message": "document is missing viewport meta", "type": "missing_viewport"},
    {"line": 17, "message": "img missing alt", "type": "img_missing_alt"},
    {"line": 14, "message": "heading jumps from h1 to h3", "type": "skipped_heading_level"}
  ]
}
```

## Initial Budget
Command: `uv run python maw-tools\web_checks.py budget examples\frontend_demo\index.initial.html --max-bytes 1200 --max-elements 80 --max-assets 5`

Exit code: 1

```json
{
  "asset_count": 2,
  "check": "budget",
  "element_count": 17,
  "file": "examples\\frontend_demo\\index.initial.html",
  "passed": false,
  "total_bytes": 3116,
  "violations": [
    {"actual": 3116, "limit": 1200, "type": "byte_budget_exceeded"}
  ]
}
```

## Initial Links
Command: `uv run python maw-tools\web_checks.py links examples\frontend_demo\index.initial.html`

Exit code: 1

```json
{
  "check": "links",
  "file": "examples\\frontend_demo\\index.initial.html",
  "passed": false,
  "reference_count": 3,
  "violations": [
    {"line": 11, "target": "#missing-panel", "type": "missing_anchor"}
  ]
}
```

## Fixed Contrast
Command: `uv run python maw-tools\web_checks.py contrast --foreground "#ffffff" --background "#0f766e"`

Exit code: 0

```json
{
  "background": "#0f766e",
  "check": "contrast",
  "foreground": "#ffffff",
  "large": false,
  "passed": true,
  "ratio": 5.47325,
  "threshold": 4.5
}
```

## Fixed A11y
Command: `uv run python maw-tools\web_checks.py a11y examples\frontend_demo\index.html`

Exit code: 0

```json
{
  "check": "a11y",
  "file": "examples\\frontend_demo\\index.html",
  "passed": true,
  "violation_count": 0,
  "violations": []
}
```

## Fixed Budget
Command: `uv run python maw-tools\web_checks.py budget examples\frontend_demo\index.html --max-bytes 4096 --max-elements 80 --max-assets 5`

Exit code: 0

```json
{
  "asset_count": 2,
  "check": "budget",
  "element_count": 17,
  "file": "examples\\frontend_demo\\index.html",
  "passed": true,
  "total_bytes": 1973,
  "violations": []
}
```

## Fixed Links
Command: `uv run python maw-tools\web_checks.py links examples\frontend_demo\index.html`

Exit code: 0

```json
{
  "check": "links",
  "file": "examples\\frontend_demo\\index.html",
  "passed": true,
  "reference_count": 3,
  "violations": []
}
```

## Fixed Markup
Command: `uv run python maw-tools\web_checks.py markup examples\frontend_demo\index.html`

Exit code: 0

```json
{
  "check": "markup",
  "file": "examples\\frontend_demo\\index.html",
  "passed": true,
  "violation_count": 0,
  "violations": []
}
```
