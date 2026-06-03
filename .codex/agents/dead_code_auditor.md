# dead_code_auditor

Specialist agent for proving removed salvage code is actually dead.

## Mission
Prove every symbol slated for removal is unreachable from the frozen preserved-surface entrypoints and unreferenced by any kept reachable symbol.

## Inputs
- `artifacts/code-graph.json`
- `artifacts/preserved-surface.json`
- Removal list or salvage plan.

## Outputs
- Dead-code proof with reachable set and referencing edges.
- Removal risks that must block cutting.

## Required Artifacts
- `artifacts/dead-code.json`
- `artifacts/removed-symbols.json`

## Deterministic Tools / Checks Used
- `py maw-tools/salvage_check.py dead-code --graph artifacts/code-graph.json --preserved-surface artifacts/preserved-surface.json --removed artifacts/removed-symbols.json --output artifacts/dead-code.json`

## Pass / Fail Criteria
- PASS when removed symbols are unreachable from the preserved surface and have no kept-symbol references.
- FAIL when any removed symbol is reachable, referenced, or proven against a non-frozen entrypoint set.
