# Hand-off: planner -> worker  (run 2026-06-01_expand-advanced-agent-roster-and_f940, step 02)

## Task context
Implement advanced-mode agents and checks without changing the parity benchmark roster.

## What I did
Mapped requested advanced agents to `.codex/agents`, advanced templates, deterministic ML and MAW tool checks, examples, README updates, and tests.

## Output / artifacts
- run.md  (implementation plan and quality bar)
- artifacts/architecture.md  (to be written by worker)
- artifacts/follow-ups.md  (to capture deferred scope)

## Open questions / risks
Calibration and dependency checks should be deterministic but lightweight enough for stdlib-only tests.

## Recommended next step
Worker should add advanced role prompts, implement deterministic commands, update templates/package data/docs, and add unit tests.
