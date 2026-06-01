# Run 2026-06-01_expand-advanced-agent-roster-and_f940

- Task: expand advanced agent roster and validation checks
- Created: 2026-06-01 16:37
- Status: complete

## Conductor plan
Pattern: conductor -> planner -> worker -> critic -> acceptance_gate.

Role justifications:
- conductor: preserve parity roster boundaries and choose the advanced-mode MVP scope.
- planner: map requested advanced agents to templates, deterministic checks, and artifacts.
- worker: implement role prompts, checks, examples, docs, and tests.
- critic: verify parity mode remains unchanged and advanced checks are usable.
- acceptance_gate: validate handoffs, templates, tests, commit, and push status.

Quality bar:
- Parity roster remains conductor, planner, worker, critic, acceptance_gate.
- Advanced agents are optional and used only by advanced templates.
- Each requested advanced agent has mission, inputs, outputs, required artifacts, tools, and pass/fail criteria.
- Missing deterministic checks are implemented as working MVP commands with tests.
- Updated templates validate and tests pass.
- Gaps are documented in a follow-up artifact if full scope is not completed.

Deterministic checks:
- `py -m unittest discover -s tests`
- `py maw-tools/validate_workflow_template.py`
- `py maw-tools/validate_handoffs.py runs/2026-06-01_expand-advanced-agent-roster-and_f940`
- `py maw-tools/acceptance_check.py --run runs/2026-06-01_expand-advanced-agent-roster-and_f940 --test-cmd "py -m unittest discover -s tests"`

## Final result summary
Verdict: SHIP.

Implemented the advanced-mode MVP: optional specialized agents, advanced template activation, deterministic ML/debug/dependency/aggregation checks, examples, README updates, package-data sync, and tests.

Verification:
- `py maw-tools/validate_workflow_template.py`: PASS, 6 templates.
- `py -m unittest discover -s tests`: PASS, 40 tests.
- `uv run --with fastapi --with pytest --with httpx python -m pytest -q`: PASS, 67 tests, 1 external deprecation warning.
- `py maw-tools/validate_handoffs.py runs/2026-06-01_expand-advanced-agent-roster-and_f940`: PASS.
- `py maw-tools/acceptance_check.py --run runs/2026-06-01_expand-advanced-agent-roster-and_f940 --test-cmd "py -m unittest discover -s tests"`: SHIP.

## Conductor plan
Roles, pattern, quality bar, deterministic checks, and acceptance criteria.

## Final result summary
Pending acceptance gate.
