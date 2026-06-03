# MAW Architecture

MAW is one workflow system: templates select roles, handoffs, artifacts, and deterministic checks, but the run shape stays auditable and file-backed.

## Core Execution

The executing core roster from `packs/core/manifest.json` is:

- `conductor`
- `planner`
- `worker`
- `critic`
- `acceptance_gate`

The conductor proposes a structured plan before execution. The hard pre-execution gate is `maw-tools/plan_check.py`; it validates known roles, core-role presence, required roles by task type, caps, parallel count, duplicate roles, and optional-role justifications.

`plan_reviewer` is an advisory role for the same conductor plan. It can recommend `APPROVE` or `REVISE`, but it does not replace the deterministic plan gate.

## Role Catalog

Advisory reviewers:

- `plan_reviewer`: conductor-plan review before execution.
- `ux_critic`: UX judgment in front-end workflows.

Specialist roles available under `.codex/agents/`:

- `a11y_auditor`
- `aggregator`
- `baseline_enforcer`
- `bug_hunter`
- `calibration_checker`
- `change_verifier`
- `data_quality_auditor`
- `debugger`
- `dependency_mapper`
- `leakage_auditor`
- `markup_validator`
- `overfitting_checker`
- `perf_budgeter`
- `reproducibility_checker`
- `responsive_checker`
- `style_drift_auditor`
- `ui_builder`
- `visual_verifier`

Templates can add these roles when useful. The plan gate still requires the full core roster and enough `max_agents` headroom for required specialists.

## Task Types

The core pack knows `debugging`, `generic`, `ml`, `frontend`, `code`, and `refactor`. Template aliases map user-facing templates such as `ml-training-task` or `frontend-ui-task` onto those task types.

Required specialist rules:

- `debugging`: `debugger`, `bug_hunter`, `dependency_mapper`
- `generic`: none beyond core roles
- `ml`: `leakage_auditor`, `baseline_enforcer`
- `frontend`: `a11y_auditor`, `change_verifier`
- `code`: `critic`, `dependency_mapper`
- `refactor`: none beyond core roles

## Deterministic Spine

Model roles produce plans, reviews, and implementation work. Deterministic tools produce the evidence used by gates:

- `plan_check.py` gates conductor plans before execution.
- `validate_handoffs.py` checks handoff completeness.
- `acceptance_check.py` checks final evidence and writes the canonical verdict artifact.
- `verdict_check.py` ensures the declared final verdict matches that artifact.
- Task-specific tools such as `ml_checks.py`, `web_checks.py`, `behavior_baseline.py`, and `dependency_risk_audit.py` provide required evidence for templates.

Specialized capabilities are normal MAW workflow features, selected by template or conductor plan when they fit the task.
