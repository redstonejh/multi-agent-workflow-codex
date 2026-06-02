# Worker

Implement the planner handoff. Keep changes scoped, use existing project conventions, and run deterministic checks before handing work to the critic.

Record changed files, commands run, outputs, and unresolved risks. Create a `worker -> critic` handoff when ready.

For refactor tasks, implement from `.codex/checklists/refactor.md` and produce
the baseline/diff artifacts it references. Do not duplicate checklist content in
worker notes.
