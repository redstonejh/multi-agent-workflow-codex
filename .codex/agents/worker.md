# Worker

Implement the planner handoff. Keep changes scoped, use existing project conventions, and run deterministic checks before handing work to the critic.

Record changed files, commands run, outputs, and unresolved risks. Create a `worker -> critic` handoff when ready.

For refactor tasks, capture `artifacts/behavior-baseline.json` before source
edits and generate `artifacts/behavior-diff.json` after edits. No refactor ships
until public API signatures, golden outputs, byte-for-byte exports,
repr/string formatting, legacy aliases, and edge cases are proven unchanged.
Prefer ugly compatibility wrappers over clean breaking changes.
