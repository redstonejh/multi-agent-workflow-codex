# Run 2026-06-02_extend-frontend-pack-with-change_4e1a

- Task: extend frontend pack with change verification and style drift
- Created: 2026-06-02 10:08
- Status: SHIP

## Conductor plan
Roles:
- conductor: scope the extension and enforce stdlib/no-browser/no-npm constraints.
- planner: define focused implementation and verification steps.
- worker: extend `web_checks.py`, agents, skill, template, demos, tests, and README.
- critic: review source-change and token-drift gates for correctness and scope.
- acceptance_gate: rerun deterministic checks last and decide SHIP or NO-SHIP.

New workflow-specific agents:
- change_verifier
- style_drift_auditor
- visual_verifier

Quality bar:
- Use `uv run python` for every Python command.
- Use stdlib-only deterministic checks.
- No browser dependency or npm for hard gates.
- Mark browser visual comparison and hard-gated visual judgment as `# MAW-TODO`.

Deterministic checks:
- `uv run python maw-tools/selftest_web_checks.py`
- `uv run python maw-tools/selftest_all.py`
- relevant existing tests via `uv run python`
- MAW handoff and acceptance checks via `uv run python`

Acceptance criteria:
- `changed`, `style`, and `tokens` commands exist, emit JSON, and exit 0/1.
- Change demo proves happy path, no-op failure, and token-drift failure.
- Front-end workflow docs state source/style checks and token checks are hard gates.
- Required self-tests pass and raw output is written to `selftest_output.txt`.

## Final result summary
SHIP: Added deterministic `changed`, `style`, and `tokens` checks to the front-end/UI pack, wired change verification and style-drift agents into the front-end workflow, added a red/green change demo, extended self-tests, and recorded raw verification output.
