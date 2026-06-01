# Examples

`sample_app/` is a tiny Python target used by deterministic checks.

`sample_run/` is a complete MAW run folder that demonstrates:

- role note files
- shared memory
- markdown handoffs
- an artifact
- a final `SHIP` summary

Validate it from the repository root:

```bash
python maw-tools/validate_handoffs.py examples/sample_run
python maw-tools/acceptance_check.py --run examples/sample_run --test-cmd "python test_textutil.py" --test-cwd examples/sample_app
```
