# Run 2026-06-02_add-front-end-ui-workflow_a8d3

- Task: add front-end UI workflow pack
- Created: 2026-06-02 09:46
- Status: SHIP

## Conductor plan
Roles:
- conductor: scope the front-end/UI domain pack and enforce stdlib-only implementation.
- planner: create a concrete implementation and verification plan.
- worker: implement web checks, front-end agents, skill, demo, tests, and docs.
- critic: review correctness, scope, and raw command evidence.
- acceptance_gate: rerun deterministic checks last and record SHIP or NO-SHIP.

Workflow-specific agents added by this pack:
- ui_builder
- a11y_auditor
- responsive_checker
- perf_budgeter
- markup_validator
- ux_critic

Orchestration pattern: core MAW run with a front-end workflow pack added to the repository.

Quality bar:
- Python implementation uses only the standard library.
- Every Python command uses `uv run python`.
- No browser, npm, or external services.
- Claims must be backed by raw command output in artifacts or `selftest_output.txt`.
- Incomplete browser/rendering capabilities are tagged `# MAW-TODO`.

Deterministic checks:
- `uv run python maw-tools/selftest_web_checks.py`
- `uv run python maw-tools/selftest_all.py`
- relevant existing tests via `uv run python`
- template and handoff validation via `uv run python`

Acceptance criteria:
- `web_checks.py` implements contrast, a11y, budget, links, and markup checks with JSON output and exit 0/1.
- Front-end agents and skill exist with required contract sections.
- Demo contains a broken initial fixture and fixed final files, with red-to-green artifacts.
- README describes only checks that actually run and marks browser/aesthetic hard gates as `# MAW-TODO`.
- Required self-tests pass before the final commit message uses the PASS wording.

## Final result summary
SHIP: Added the front-end/UI workflow pack with stdlib deterministic checks, front-end agents, skill, workflow template, red-to-green demo, self-tests, README documentation, and raw output evidence. Required self-tests and relevant existing checks passed.
