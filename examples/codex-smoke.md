# Codex Smoke Workflow

Task: verify that `examples/sample_app/textutil.py` normalizes whitespace.

Expected deterministic check:

```bash
python maw-tools/checks.py test --cmd "python test_textutil.py" --cwd examples/sample_app
```

Expected result: JSON with `"passed": true` and exit code `0`.
