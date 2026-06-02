# Codex Multi-Agent Workflow (MAW)

Run one task through a small team of roles — conductor, planner, worker, critic, acceptance gate — with every step written to disk and checked by deterministic Python. Each run produces an auditable folder of markdown handoffs, shared memory, role notes, and check output. Nothing is hidden in a model's head.

MAW is Codex-native and dependency-free: it uses `AGENTS.md`, a Codex skill, role prompts in `.codex/agents/`, and stdlib-only helper scripts in `maw-tools/` (Python 3.11+).

## Quickstart

The primary way to use MAW is from Codex CLI. Point it at the skill and describe the task:

```text
Use $maw to fix the failing test in this repo.
```

Codex selects the smallest useful team, runs the roles, and leaves a `runs/<id>/` folder behind.

To drive the same workflow manually with the `maw` command:

```bash
python -m pip install -e .                          # one-time, stdlib only
maw start standard-software-task "add a --verbose flag to the CLI"
maw validate-handoffs runs/<run_id>
maw acceptance runs/<run_id> --test-cmd "python -m unittest discover -s tests"
```

That's the whole loop: start a run from a template, fill in the handoffs as each role works, then run the acceptance gate. No install is required — `python maw.py ...` works from a checkout, and on Windows use `py` or `uv run python` if `python` isn't on `PATH`.

To use MAW in another workspace, copy `AGENTS.md`, `.codex/skills/maw/SKILL.md`, `.codex/agents/`, and `maw-tools/` into it.

## How a run works

The normal loop is:

```text
conductor -> planner -> worker -> critic -> (worker if needed) -> acceptance_gate
```

The **conductor** picks the smallest useful team and records the plan. The **planner** breaks the task into steps and acceptance criteria. The **worker** implements them. The **critic** reviews the worker's output inside a refine loop and sends it back when it isn't ready. The **acceptance_gate** does a final independent check and returns exactly one verdict: `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

Every run folder has the same shape:

```text
runs/<date>_<slug>_<id>/
├── run.md            # plan, roles, verdict
├── memory.md         # one short entry per role turn
├── agents/<role>.md  # per-role scratch notes
├── handoffs/         # NN_<from>__to__<to>.md
└── artifacts/        # plans, check output, reports
```

## The two gates

MAW trusts deterministic checks over model judgment wherever it can.

**Plan gate (before execution).** The conductor proposes a structured plan; `maw-tools/plan_check.py` validates it and exits 0/1:

```bash
maw plan-check runs/<run_id>/artifacts/conductor-plan.json
```

It reads JSON with `task_type`, `roles`, `caps`, and optional `role_justifications`, then enforces: known roles only, no duplicates, all core roles present, `acceptance_gate` present, team size within `max_agents`, parallel count within `max_parallel`, every optional/specialized role carries a written justification, the required roles for the task type are present, and `max_agents` has enough headroom for core + required specialists.

A second role, `plan_reviewer`, independently reviews the same plan and returns `APPROVE` or `REVISE` (redundant roles, coverage gaps, wrong team size). `plan_check.py` is the hard gate; the reviewer is advisory. The conductor replans when the gate fails or the reviewer returns `REVISE`; execution starts only after the gate passes, and the acceptance gate later verifies plan-gate evidence exists in the run.

**Acceptance gate (after execution).** `acceptance_check.py` independently verifies task conformance, handoff completeness, deterministic check results, and that every claim maps to evidence in the run.

## Roles and caps

Most runs use only the core roster:

```text
conductor, planner, worker, critic, acceptance_gate
```

Workflow templates can add specialized roles when the task needs them. The required-role rules per task type are:

```text
generic / refactor : core agents only
code               : critic, dependency_mapper      (code_reviewer -> critic, dep_mapper -> dependency_mapper)
ml                 : leakage_auditor, baseline_enforcer
frontend           : a11y_auditor, change_verifier
debugging          : debugger, bug_hunter, dependency_mapper
```

Beyond those, templates may pull in other specialists (`overfitting_checker`, `calibration_checker`, `reproducibility_checker`, `data_quality_auditor`, `aggregator`, `ui_builder`, `responsive_checker`, `perf_budgeter`, `markup_validator`, `style_drift_auditor`, `visual_verifier`, `ux_critic`, …). These are inert until a template or the conductor justifies pulling them in. Full catalog: `.codex/agents/` and `docs/maw-architecture.md`.

Team size is bounded by caps. `DEFAULT_CAPS` is `{"max_agents": 5, "max_parallel": 3}` and applies to generic core-agent runs only. **Workflow templates that require specialists declare their own caps** so a specialized run still has room for the full core team. A specialist plan left on the default cap fails with `insufficient_role_cap_for_required_roles` (reporting required count, `max_agents`, missing headroom, and a suggested cap). Never fit a specialist task by dropping `planner`, `worker`, or `critic` — missing core roles are hard plan-gate failures.

Current template caps:

```text
standard-software-task: 5     bug-investigation: 8       multi-agent-research-task: 9
refactor-task: 5              ml-validation-task: 10      frontend-ui-task: 13
                             ml-training-task: 10
```

## Templates

```text
standard-software-task     bug-investigation        refactor-task
ml-validation-task         ml-training-task         frontend-ui-task
multi-agent-research-task
```

Each template declares its agents, handoff pairs, required artifacts, acceptance gates, caps, and deterministic checks. A run conforms only when its agent notes, handoffs, and artifacts all match. Declare one in `run.md` (`- Workflow template: standard-software-task`), then:

```bash
maw list-templates
maw validate-template standard-software-task
```

`start_workflow.py` (used by `maw start`) validates the template, copies it into `artifacts/workflow-template.json`, creates the agent note files, initializes handoff placeholders, and writes `artifacts/artifact-checklist.md`.

## Command reference

The `maw` CLI is the user-facing surface:

```bash
maw list-templates                                  # available templates
maw start <template> "<task>" [--run-root runs]     # scaffold a run
maw validate-template [<template>]                  # validate template schema
maw validate-handoffs runs/<run_id>                 # check handoff completeness
maw acceptance runs/<run_id> --test-cmd "<cmd>"     # final acceptance gate
maw plan-graph artifacts/task-graph.json            # plan a multi-worker graph
maw dependency-audit <path> --fail-on high          # dependency risk audit
```

The `maw-tools/` scripts back the CLI and can be run directly (stdlib only):

```bash
python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
python maw-tools/scaffold_run.py handoff --run runs/<run_id> --from planner --to worker
python maw-tools/plan_check.py --file runs/<run_id>/artifacts/conductor-plan.json
python maw-tools/validate_handoffs.py runs/<run_id>
python maw-tools/checks.py test --cmd "python -m unittest discover -s tests"
python maw-tools/acceptance_check.py --run runs/<run_id> --test-cmd "<cmd>"
python maw-tools/task_graph.py plan --file artifacts/task-graph.json
python maw-tools/validate_workflow_template.py
```

The multi-worker graph planner validates task dependencies and emits stages: independent `worker` tasks in the same stage run concurrently, followed by `aggregate` and `merge` stages before critic and acceptance review.

## Specialized packs

These are template-driven and browser-free (they operate on local files, not rendered pages).

**ML validation/training.** Toy problems and deterministic checks live in `examples/ml_problems/`. `ml_checks.py` covers metric thresholds, target leakage, train/test overlap and ratio, reproducibility seed, fit diagnosis (overfit/underfit), baseline improvement, calibration (ECE), and data quality. Start with `maw start ml-validation-task "..."`.

**Front-end / UI.** `maw-tools/web_checks.py` runs deterministic checks on local HTML/CSS: WCAG contrast, accessibility (alt text, labels, heading order, lang/title/viewport), byte/element budgets, link resolution, markup well-formedness, CSS selector/property extraction, change verification against a snapshot, and design-token drift. Demos in `examples/frontend_demo/` and `examples/change_demo/`. Start with `maw start frontend-ui-task "..."`. `ux_critic` is advisory; hard PASS/FAIL comes from the checks.

**Dependency risk audit.** `maw dependency-audit <path>` (or `maw-tools/dependency_risk_audit.py`) scans Python for fragile coupling — global state, env/cwd dependencies, uninjected time/randomness, shared mutable args, import-time side effects, circular imports, fan-in/out risk, and more. `--fail-on high` gates; `--annotate` inserts `# MAW-DEPENDENCY-RISK:` comments. High-severity findings generate bug dossiers under `docs/bugs/` (format in `docs/bug-dossiers.md`).

## Tests

```bash
python -m unittest discover -s tests
uv run python maw-tools/selftest_all.py        # aggregate self-tests (plan gate, web checks, …)
```

## Architecture

`AGENTS.md` defines repo-wide behavior, roles, caps, and the audit format. `.codex/skills/maw/SKILL.md` is the Codex skill entry point. `.codex/agents/` holds the role prompts — each declares mission, inputs, outputs, required artifacts, deterministic tools, and pass/fail criteria. Where Codex supports role delegation the roles run as separate agents; otherwise they run sequentially in one session. For the full role catalog and the core-vs-specialized model, see `docs/maw-architecture.md`.

## Examples

`examples/sample_run/` is a small complete run folder; `examples/sample_app/` is a tiny deterministic test target:

```bash
python maw-tools/validate_handoffs.py examples/sample_run
python maw-tools/acceptance_check.py --run examples/sample_run --test-cmd "python test_textutil.py" --test-cwd examples/sample_app
```
