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
- `dead_code_auditor`
- `dependency_mapper`
- `dependency_untangler`
- `leakage_auditor`
- `markup_validator`
- `overfitting_checker`
- `perf_budgeter`
- `reproducibility_checker`
- `responsive_checker`
- `salvage_verifier`
- `style_drift_auditor`
- `ui_builder`
- `visual_verifier`

Templates can add these roles when useful. The plan gate still requires the full core roster and enough `max_agents` headroom for required specialists.

## Task Types

The core pack knows `debugging`, `generic`, `ml`, `frontend`, `code`, `refactor`, and `salvage`. Template aliases map user-facing templates such as `ml-training-task`, `frontend-ui-task`, or `salvage-task` onto those task types.

Required specialist rules:

- `debugging`: `debugger`, `bug_hunter`, `dependency_mapper`
- `generic`: none beyond core roles
- `ml`: `leakage_auditor`, `baseline_enforcer`
- `frontend`: `a11y_auditor`, `change_verifier`
- `code`: `critic`, `dependency_mapper`
- `refactor`: none beyond core roles
- `salvage`: `dependency_mapper`, `dependency_untangler`, `dead_code_auditor`

## Deterministic Spine

Model roles produce plans, reviews, and implementation work. Deterministic tools produce the evidence used by gates:

- `plan_check.py` gates conductor plans before execution.
- `validate_handoffs.py` checks handoff completeness.
- `acceptance_check.py` checks final evidence and writes the canonical verdict artifact.
- `verdict_check.py` ensures the declared final verdict matches that artifact.
- Task-specific tools such as `ml_checks.py`, `web_checks.py`, `behavior_baseline.py`, `dependency_risk_audit.py`, and `salvage_check.py` provide required evidence for templates.

Specialized capabilities are normal MAW workflow features, selected by template or conductor plan when they fit the task.

Dependency boundary: `maw-tools/code_graph_py.py` uses stdlib `ast` and remains in the deterministic spine. `maw-tools/code_graph_html.py` uses `html.parser` and CSS extraction from `maw-tools/web_checks.py` for HTML/CSS graph evidence. `maw-tools/salvage_check.py` consumes only normalized JSON graph, static test evidence, and characterization artifacts, so the hard salvage decision remains language-agnostic and stdlib-only. `maw_cli/code_graph_js.py`, `maw_cli/vendor/code_graph_js.js`, and `maw_cli/capture_web.py` are optional adapters outside that spine; they may require Node, the TypeScript compiler API, or Playwright and must emit `NEEDS-HUMAN` rather than guessing when unavailable.

## Salvage Workflow

`salvage-task` is a system-level refactor workflow for removing legacy code from messy Python, HTML, CSS, JS, and TS projects while preserving a chosen surface. It detects topology into `artifacts/topology.json`, builds `artifacts/code-graph.json`, runs static-first test triage into `artifacts/test-triage.json` and `artifacts/test-provenance.md`, freezes `artifacts/preserved-surface.json` and `artifacts/preserved-surface.sha256` before iteration 0, captures golden behavior in `artifacts/characterization-baseline.json`, and aggregates hard gate results into `artifacts/salvage-result.json`.

The normalized code graph schema at `schemas/code-graph.json` represents modules, stable symbol ids, entrypoints, topology, language, and typed edges: `import`, `call`, `read_global`, `write_global`, `inherit`, `alias`, `dynamic`, `dom_ref`, `css_ref`, `route_ref`, `template_var`, and `asset_ref`. The characterization schema at `schemas/characterization.json` records replayable route/page/test evidence for the preserved surface.

Salvage has three evidence tiers:

- Within-language structural gates use concrete parsers where available: Python `ast`, HTML `html.parser`, CSS selector extraction, and the optional JS/TS parser adapter.
- Static-first test triage partitions tests into ACTIVE keep-bound tests, SCRAP cut-bound tests, MIXED/AMBIGUOUS items that block auto-ship, and LEGACY do-not-resurrect evidence. Only ACTIVE tests execute as the preserved test contract.
- Cross-language couplings are heuristic candidates from selectors, routes, template variables, form fields, API strings, assets, and globals. A candidate must be documented and tested, or dismissed with a recorded justification.
- Behavioral parity is the primary safety net. Characterization replay compares settled interaction evidence before and after the refactor with field-level diffs. It tolerates 1px single-object geometry noise and small perceptual color noise, but blocks viewport/scroll drift, missing interaction handlers, and real object movement.

The required hard gates are preserved-surface parity, static-first test triage, hidden dependency and cross-language coupling proof, dead-code proof from frozen entrypoints, duplicate collapse to a single rerouted survivor, smart-refactor evidence, stale-code evidence, and interdependency dossier coverage. The resistance gate plants representative defects and must prove each gate fails when its protected condition is violated.

Anti-gaming checks are duplicated in `salvage_check.py`, `acceptance_check.py`, and `verdict_check.py`: a run is `NO-SHIP` if the preserved-surface hash changes, the surface shrinks, parity lacks a pre-gut baseline, graph entrypoints differ from the frozen surface, dead-code proof uses a different entrypoint set, test triage is missing or fails, legacy symbols are resurrected, or a coupling dismissal lacks justification.
