# Hand-off: worker -> critic  (run 2026-06-01_expand-advanced-agent-roster-and_f940, step 03)

## Task context
Expand optional MAW advanced agents and deterministic checks while preserving parity mode.

## What I did
Added ten advanced role prompt files, updated four advanced templates, added ML baseline/calibration/reproducibility/data-quality checks, added dependency-map and aggregation checks, updated README/examples, synced package data, and added tests.

## Output / artifacts
- .codex/agents/*.md  (advanced role contracts)
- examples/ml_problems/ml_checks.py  (ML deterministic checks)
- maw-tools/checks.py  (dependency-map and aggregation checks)
- templates/workflows/*.json  (advanced template activation)
- tests/test_maw_tools.py  (unit coverage)
- artifacts/test-failure-20260601-01.md  (documented transient test failure)

## Open questions / risks
Dependency mapping validates supplied JSON maps but does not yet auto-extract Python imports; this is documented as follow-up.

## Recommended next step
Critic should verify parity roster remains unchanged, templates validate, new tests pass, and follow-up scope is documented.
