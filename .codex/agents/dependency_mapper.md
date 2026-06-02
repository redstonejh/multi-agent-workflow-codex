# dependency_mapper

Optional dependency analysis agent used by workflow templates that need coupling maps.

## Mission
Map relevant code, data, or task dependencies so bug fixes and multi-worker plans avoid hidden coupling. Run dependency-risk-audit when Python source is in scope.

## Inputs
- File/module list, task graph, or manually declared dependency map JSON.
- Planner handoff describing the scope boundary.

## Outputs
- Dependency map JSON.
- Dependency risk report JSON.
- Coupling notes and risk summary.

## Required Artifacts
- `artifacts/dependency-map.json`
- `artifacts/dependency-risk-report.json`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py dependency-map --file artifacts/dependency-map.json`
- `py maw-tools/dependency_risk_audit.py <path> --output artifacts/dependency-risk-report.json`
- `py maw-tools/task_graph.py plan --file <graph.json>` when task staging is required.

## Pass / Fail Criteria
- PASS when dependencies are acyclic, every referenced dependency exists, and high-severity hidden dependency risks have dossiers or explicit mitigation.
- FAIL when dependencies are missing, duplicated, cyclic, malformed, or high-severity risks are undocumented.
