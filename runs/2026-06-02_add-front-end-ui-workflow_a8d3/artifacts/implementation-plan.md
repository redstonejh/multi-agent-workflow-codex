# Implementation Plan

1. Implement `maw-tools/web_checks.py` with stdlib-only subcommands: `contrast`, `a11y`, `budget`, `links`, and `markup`.
2. Add `maw-tools/selftest_web_checks.py` with known-good and known-bad fixtures for every check.
3. Add `maw-tools/selftest_all.py` to aggregate existing checks and front-end pinned metrics.
4. Add front-end agent definitions, `.codex/skills/frontend/SKILL.md`, and a `frontend-ui-task` workflow template.
5. Create `examples/frontend_demo/` with an initial broken fixture, fixed final files, README, and run artifacts showing red-to-green outputs.
6. Update README with only verified front-end capabilities and explicit `# MAW-TODO` items.
7. Run required checks, write raw output to `selftest_output.txt`, commit, and push.
