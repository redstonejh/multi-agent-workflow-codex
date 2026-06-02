# Implementation Plan

1. Add CSS parsing helpers to `maw-tools/web_checks.py`.
2. Implement `style`, `changed`, and `tokens` subcommands with JSON output and 0/1 exit behavior.
3. Mirror source tool changes into `maw_cli/data/maw-tools/web_checks.py`.
4. Add `change_verifier`, `style_drift_auditor`, and `visual_verifier` agent definitions and wire them into the front-end skill/template.
5. Add `examples/change_demo/` with before/after, no-op, and drift fixtures plus tokens.
6. Extend `selftest_web_checks.py` and `selftest_all.py` with pinned change/style/token assertions.
7. Update README honestly with commands and `# MAW-TODO` browser visual limits.
8. Run required verification, write raw output to `selftest_output.txt`, commit, and push.
