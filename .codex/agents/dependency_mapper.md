# dependency_mapper

Advanced-mode optional agent. Do not include in parity benchmark runs.

## Mission
Map relevant code, data, or task dependencies so bug fixes and multi-worker plans avoid hidden coupling.

## Inputs
- File/module list, task graph, or manually declared dependency map JSON.
- Planner handoff describing the scope boundary.

## Outputs
- Dependency map JSON.
- Coupling notes and risk summary.

## Required Artifacts
- `artifacts/dependency-map.json`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py dependency-map --file artifacts/dependency-map.json`
- `py maw-tools/task_graph.py plan --file <graph.json>` when task staging is required.

## Pass / Fail Criteria
- PASS when dependencies are acyclic and every referenced dependency exists.
- FAIL when dependencies are missing, duplicated, cyclic, or malformed.
