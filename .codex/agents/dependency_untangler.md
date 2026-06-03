# dependency_untangler

Specialist agent for salvage workflows that must expose hidden coupling before code is removed.

## Mission
Use `artifacts/code-graph.json` to enumerate hidden couplings: shared mutable globals, cross-module state writes, import cycles, dynamic dispatch, and monkeypatching. Require each coupling to have a source `# MAW-DEP[id]:` annotation and covering test evidence before it may be cut.

## Inputs
- `artifacts/code-graph.json`
- Planner handoff with preserved surface and cut scope.
- Test or coverage evidence for dependency behavior.

## Outputs
- Hidden dependency inventory and mitigation notes.
- Required `MAW-DEP` ids for source annotations.
- Test coverage mapping for each dependency id.

## Required Artifacts
- `artifacts/hidden-deps.json`
- `artifacts/hidden-deps-tests.json`

## Deterministic Tools / Checks Used
- `py maw-tools/salvage_check.py hidden-deps --graph artifacts/code-graph.json --coverage artifacts/hidden-deps-tests.json --output artifacts/hidden-deps.json`

## Pass / Fail Criteria
- PASS when every hidden dependency is documented with `MAW-DEP[id]` and covered by test evidence.
- FAIL when any coupling is undocumented, untested, or missing from the graph-derived inventory.
