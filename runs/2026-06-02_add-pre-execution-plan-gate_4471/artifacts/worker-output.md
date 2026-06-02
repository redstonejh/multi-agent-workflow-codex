# Worker Output

Implemented:
- `maw-tools/plan_check.py` and package-data mirror.
- `maw-tools/selftest_plan_check.py` and aggregate `selftest_all.py` assertions.
- `.codex/agents/plan_reviewer.md`.
- Conductor, MAW skill, and acceptance-gate guidance for pre-execution plan gating.
- README section documenting commands, required-role rules, and planted demo path.
- Planted demo run showing a missing ML validator fails, then passes after replanning.

The implementation uses only the Python standard library and keeps the role rule table centralized in `plan_check.py`.
