# Change Demo Raw Output

## Style Before
Command: `uv run python maw-tools\web_checks.py style examples\change_demo\style.before.css --selector ".btn" --property background`

Exit code: 0

```json
{
  "check": "style",
  "passed": true,
  "property": "background",
  "reason": "value found",
  "selector": ".btn",
  "source_file": "examples\\change_demo\\style.before.css",
  "value": "#e0e0e0"
}
```

## Style After
Command: `uv run python maw-tools\web_checks.py style examples\change_demo\style.after.css --selector ".btn" --property background`

Exit code: 0

```json
{
  "check": "style",
  "passed": true,
  "property": "background",
  "reason": "value found",
  "selector": ".btn",
  "source_file": "examples\\change_demo\\style.after.css",
  "value": "#1a73e8"
}
```

## Real Change
Command: `uv run python maw-tools\web_checks.py changed --before examples\change_demo\style.before.css --after examples\change_demo\style.after.css --selector ".btn" --property background --expected "#1a73e8"`

Exit code: 0

```json
{
  "after": "#1a73e8",
  "before": "#e0e0e0",
  "check": "changed",
  "expected": "#1a73e8",
  "passed": true,
  "reason": "target changed to expected value"
}
```

## No-op Failure
Command: `uv run python maw-tools\web_checks.py changed --before examples\change_demo\style.before.css --after examples\change_demo\style.noop.css --selector ".btn" --property background --expected "#1a73e8"`

Exit code: 1

```json
{
  "after": "#e0e0e0",
  "before": "#e0e0e0",
  "check": "changed",
  "expected": "#1a73e8",
  "passed": false,
  "reason": "target did not change"
}
```

## Valid Tokens
Command: `uv run python maw-tools\web_checks.py tokens --token-file examples\change_demo\design-tokens.json examples\change_demo\style.after.css`

Exit code: 0

```json
{
  "check": "tokens",
  "drift_count": 0,
  "drift_items": [],
  "passed": true
}
```

## Token Drift
Command: `uv run python maw-tools\web_checks.py tokens --token-file examples\change_demo\design-tokens.json examples\change_demo\style.drift.css`

Exit code: 1

```json
{
  "check": "tokens",
  "drift_count": 1,
  "passed": false,
  "drift_items": [
    {
      "property": "background",
      "value": "#0057ff"
    }
  ]
}
```
