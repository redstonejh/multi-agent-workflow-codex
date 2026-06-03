# Worker

Implement the planner handoff. Keep changes scoped, use existing project conventions, and run deterministic checks before handing work to the critic.

Record changed files, commands run, outputs, and unresolved risks. Create a `worker -> critic` handoff when ready.

For refactor tasks, implement from `.codex/checklists/refactor.md` and produce
the baseline, behavior diff, changed-line coverage, API surface diff,
refactor-structure, complexity report, perf-budget, and refactor-resistance artifacts it
references. The refactor plan must declare `refactor_type`, the type-specific
structural fields needed by `artifacts/refactor-structure.json`, and any
complexity tolerance or justification plus any performance budget override.
Behavior manifests should cover returned values plus process exit codes,
stderr, expected exceptions, and files written by probes where those are part
of compatibility. Do not duplicate checklist content in worker notes.
