# Codex Multi-Agent Workflow (MAW)

MAW is a Codex-native workflow scaffold for running one task through explicit roles, markdown handoffs, deterministic checks, and an auditable `runs/` folder. Its core rule is simple: use model judgment for planning and critique, but make shipping decisions depend on recorded evidence and standard-library checks wherever possible.

The repository is intentionally small: `AGENTS.md` and `.codex/skills/maw/SKILL.md` define the Codex-facing workflow, `.codex/agents/` defines role prompts, `templates/workflows/` defines task templates, `packs/core/manifest.json` defines known roles/task types/caps, and `maw-tools/` contains the deterministic Python tools.

## 30-Second Quickstart

Use the skill from Codex:

```text
Use $maw to fix the failing test in this repo.
```

Or drive the local CLI directly:

```bash
python -m pip install -e .
maw start standard-software-task "add a --verbose flag to the CLI"
maw validate-handoffs runs/<run_id>
maw acceptance runs/<run_id> --test-cmd "python -m unittest discover -s tests"
```

No install is required from a checkout; `python maw.py ...` uses the same CLI. On Windows, `py` or `uv run python` are fine substitutes when `python` is not on `PATH`.

## Headline ML Workflow

The real one-line ML entry point is:

```bash
maw ml-auto data.csv --goal "predict churn"
```

`ml-auto` supports tabular CSV and Parquet. It profiles the data, infers the target and problem type when confidence is high, trains a deterministic numeric-feature model, derives validation config, emits raw per-example exports, runs the existing ML validators, runs acceptance, and writes `artifacts/ml-report.md` in the run folder. If the target or problem type is ambiguous, it records `NEEDS-HUMAN` and one targeted question instead of guessing.

Dependency boundary: the autopilot adapter in `maw_cli/ml_autopilot.py` may use pandas/scikit-learn for data loading and training. The deterministic spine, `maw-tools/`, and `examples/ml_problems/ml_checks.py` remain standard-library only.

For fixed-split WILDS-style benchmark harness work, use:

```bash
maw wilds-benchmark manifest.json predictions.json --output artifacts/wilds-harness-result.json
```

`wilds-benchmark` is infrastructure for evaluating prediction exports by stable example id across fixed splits. It does not train a model and does not import WILDS or Torch; callers provide a small manifest with `id`, `split`, and `label` fields plus a prediction file with matching `id` values.

When the WILDS package is available, `maw wilds-benchmark predictions.json --wilds-dataset <name> --split <split>` lazily loads `wilds.get_dataset(...)`, reads the fixed subset, and delegates metrics to `dataset.eval(all_y_pred, all_y_true, all_metadata)`.

For end-to-end inference harness checks, export a fixed WILDS split to JSONL, run an optional model command over that JSONL, and score the resulting predictions:

```bash
maw wilds-export --wilds-dataset <name> --split <split> --output artifacts/wilds-examples.jsonl --model-cmd "python model.py {input} {output}" --score-output artifacts/wilds-score.json
```

`wilds-export` writes one JSON object per example with `id` and `x`; string inputs also include `text`. When `--model-cmd` is set, `{input}` is replaced with the export path and `{output}` with the prediction JSON path, then the predictions feed the existing WILDS scorer.

The included CivilComments baseline model command lives at `model.py`. It trains a TF-IDF + logistic regression baseline on the CivilComments train split using optional WILDS and scikit-learn dependencies, then writes prediction JSONL with ids passed through:

```bash
maw wilds-export --wilds-dataset civilcomments --split val --limit 500 --output artifacts/civilcomments-val-500.jsonl --model-cmd "python model.py {input} {output}" --score-output artifacts/civilcomments-val-500-score.json
```

The score artifact should report `metrics_source: "wilds.dataset.eval"` and parseable real metrics from `dataset.eval(...)`. Set `--wilds-root <path>` when the local CivilComments data is outside the default WILDS root. This loop is a manual benchmark check; `model.py` is outside the standard-library MAW tools spine.

To wrap an existing WILDS score in a closed MAW validation loop, use:

```bash
maw wilds-loop --score score.json --predictions predictions.jsonl --majority-accuracy 0.5
```

`wilds-loop` starts an `ml-validation-task` run folder, copies the score and optional prediction artifacts, runs the stdlib-only `maw-tools/wilds_validator.py`, and writes `artifacts/wilds-validator.json`, `artifacts/critic-diagnosis.md`, `artifacts/wilds-loop-result.json`, and `artifacts/acceptance-result.json`. The validator flags worst-group-vs-average gaps above `0.20`, expected calibration error above `0.10`, Brier score above `0.25`, majority-baseline margin below `0.02`, and missing deterministic reproducibility metadata. Tripped checks produce worker instructions such as trying group-balanced/reweighted training, calibrated probabilities, or a stronger model before re-scoring. Retries are bounded by `--max-iters`.

Closed-loop WILDS runs can opt into anti-gaming hard gates by writing `artifacts/evaluation-protocol.json` with `anti_gaming: true` plus `artifacts/evaluation-protocol.sha256` before iteration 0. Once present, `maw-tools/acceptance_check.py` and `maw-tools/verdict_check.py` independently run `maw-tools/anti_gaming_check.py` and force `NO-SHIP` when the protocol hash changes, iterating roles can reach the sealed test split, the sealed test is not scored exactly once by `acceptance_gate`, any banked candidate fails an orthogonal gate or banks a sub-CI worst-group gain, validation query budget is exceeded, prediction distribution degenerates, or the final val-to-test gap exceeds the pre-registered bound. These are blocking verdict conditions, not advisory reports.

## Run Loop

The executing core roster is:

```text
conductor -> planner -> worker -> critic -> acceptance_gate
```

The conductor classifies the task, chooses roles, records caps, and writes a structured plan. The deterministic plan gate (`maw-tools/plan_check.py`, exposed as `maw plan-check`) validates that plan before execution. `plan_reviewer` is an advisory reviewer for the same conductor plan: it can return `APPROVE` or `REVISE`, but the hard pass/fail decision comes from `plan_check.py`.

The planner turns the accepted plan into steps and acceptance criteria. The worker implements or drafts the work. The critic reviews the worker output and can request revisions. The acceptance gate independently checks handoffs, required evidence, optional test command output, and final verdict consistency. Final verdicts are `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

Every scaffolded run has this shape:

```text
runs/<date>_<slug>_<id>/
  run.md
  memory.md
  agents/<role>.md
  handoffs/NN_<from>__to__<to>.md
  artifacts/
```

## Roles

Hard deterministic gates:

- `plan_check.py`: validates conductor plans before execution.
- `acceptance_check.py`: validates final handoffs, configured tests, required task evidence, and writes `artifacts/acceptance-result.json`.
- `verdict_check.py`: verifies the verdict declared in `run.md` matches `artifacts/acceptance-result.json`.

Executing core roles from `packs/core/manifest.json`:

- `conductor`
- `planner`
- `worker`
- `critic`
- `acceptance_gate`

Advisory reviewers:

- `plan_reviewer`: reviews the conductor plan; advisory, not a hard gate.
- `ux_critic`: used by front-end templates for UX judgment; deterministic UI checks still decide hard evidence.

Specialists available in `.codex/agents/` include `a11y_auditor`, `aggregator`, `baseline_enforcer`, `bug_hunter`, `calibration_checker`, `change_verifier`, `data_quality_auditor`, `debugger`, `dependency_mapper`, `leakage_auditor`, `markup_validator`, `overfitting_checker`, `perf_budgeter`, `reproducibility_checker`, `responsive_checker`, `style_drift_auditor`, `ui_builder`, and `visual_verifier`. They are selected by templates or conductor plans and must fit the configured caps.

For the full role catalog, see `docs/maw-architecture.md`.

## Task Types And Caps

The core pack knows these task types: `debugging`, `generic`, `ml`, `frontend`, `code`, and `refactor`.

Aliases:

- `standard-software-task` -> `generic`
- `bug-investigation` -> `debugging`
- `ml-training-task` and `ml-validation-task` -> `ml`
- `frontend-ui-task` -> `frontend`
- `refactor-task` -> `refactor`

Default caps are `max_agents: 5` and `max_parallel: 3`. Required roles by task type:

- `generic`: core roles only
- `refactor`: core roles only
- `code`: `critic`, `dependency_mapper`
- `ml`: `leakage_auditor`, `baseline_enforcer`
- `frontend`: `a11y_auditor`, `change_verifier`
- `debugging`: `debugger`, `bug_hunter`, `dependency_mapper`

Role aliases are `code_reviewer -> critic` and `dep_mapper -> dependency_mapper`.

Template caps currently are:

| Template | max_agents | max_parallel |
|---|---:|---:|
| `standard-software-task` | 5 | 3 |
| `refactor-task` | 5 | 3 |
| `bug-investigation` | 8 | 3 |
| `multi-agent-research-task` | 9 | 3 |
| `ml-training-task` | 10 | 3 |
| `ml-validation-task` | 10 | 3 |
| `wilds-benchmark-task` | 6 | 3 |
| `frontend-ui-task` | 13 | 3 |

Templates define scaffolded agents, handoffs, artifacts, acceptance gates, and deterministic check commands. The plan gate is stricter than template schema validation: actual conductor plans must include all core roles and justify optional specialists.

## Command Reference

The `maw` CLI subcommands are:

```bash
maw list-templates
maw start <template> "<task>" [--run-root runs] [--slug <slug>]
maw validate-template [<template>]
maw validate-handoffs runs/<run_id>
maw acceptance runs/<run_id> [--test-cmd "<cmd>"] [--test-cwd <path>]
maw verdict-check runs/<run_id>
maw plan-check runs/<run_id>/artifacts/conductor-plan.json
maw plan-graph artifacts/task-graph.json
maw run-report runs/<run_id>
maw dependency-audit <path> [--annotate] [--dry-run] [--fail-on low|medium|high]
maw ml-auto <csv-or-parquet> --goal "<goal>"
maw wilds-benchmark <manifest.json> <predictions.json> [--output artifacts/wilds-harness-result.json]
maw wilds-export --wilds-dataset <name> --split <split> [--limit N] --output examples.jsonl [--model-cmd "... {input} {output}" --score-output score.json]
maw wilds-loop --score score.json [--predictions predictions.jsonl] [--max-iters 3]
```

Common direct tool commands:

```bash
python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
python maw-tools/scaffold_run.py handoff --run runs/<run_id> --from planner --to worker
python maw-tools/plan_check.py --file runs/<run_id>/artifacts/conductor-plan.json
python maw-tools/validate_handoffs.py runs/<run_id>
python maw-tools/checks.py test --cmd "python -m unittest discover -s tests"
python maw-tools/acceptance_check.py --run runs/<run_id> --test-cmd "<cmd>"
python maw-tools/verdict_check.py runs/<run_id>
python maw-tools/validate_workflow_template.py --root .
python maw-tools/check_vendored_data.py
```

`maw plan-graph` delegates to `maw-tools/task_graph.py plan --file <graph.json>`, which validates worker/aggregate/merge task dependencies and emits executable stages.

## Workflow Templates

Template JSON files live in `templates/workflows/`; installed package data mirrors them under `maw_cli/data/templates/workflows/`.

- `standard-software-task`: core software task scaffold; required artifacts include test result, worker output, critic review, and acceptance result.
- `refactor-task`: behavior baseline/diff, coverage, API surface, structure, complexity, perf budget, resistance, and baseline tests.
- `bug-investigation`: dependency map/risk audit, reproduction notes, regression test, root-cause analysis, and fix verification.
- `frontend-ui-task`: local HTML/CSS checks for contrast, accessibility, budgets, links, markup, style extraction, change verification, tokens, visual verification, and UX/critic artifacts.
- `ml-training-task`: training/evaluation commands plus ML validator artifacts, split/config/log/report artifacts, and acceptance.
- `ml-validation-task`: ML validator artifacts without the training-command/evaluation-command artifacts.
- `wilds-benchmark-task`: fixed-split benchmark harness work with dependency mapping, parse-level artifact checks, and prediction-id alignment.
- `multi-agent-research-task`: research plan, source notes, aggregation, dependency-risk audit, final report, and acceptance artifacts.

Use `maw list-templates` and `maw validate-template [<template>]` to inspect/validate them.

## ML Checks

`examples/ml_problems/ml_checks.py` is the standard-library ML validator. It implements:

- Leakage and split checks: seed match, train/test overlap, split ratio, direct target feature leakage, labels-shuffled marker, preprocessing fit scope, content-duplicate leakage, group/entity leakage, temporal leakage, and high feature-target correlation.
- Distribution drift: PSI and Kolmogorov-Smirnov statistics over shared numeric train/test or reference/current feature maps.
- Data quality: missing-value and duplicate-row rate thresholds.
- Classification metrics: confusion matrix, per-class precision/recall/F1, accuracy, macro precision/recall/F1, majority-class rate, optional ROC AUC and PR AUC for binary scores, and optional subgroup slice gates.
- Baseline comparison: model-vs-baseline improvement with paired bootstrap confidence intervals.
- Fit diagnosis: classification train/validation/test score gaps and regression train/validation/test error ratios.
- Calibration: expected calibration error, maximum calibration error, and Brier score gates.
- Shuffled-label check: real score versus shuffled-label scores, chance/baseline collapse, and permutation p-value.
- Multi-seed stability: score floor/ceiling, variance/CV, seed count, and bootstrap mean confidence interval.
- Validator aggregation: `artifacts/ml-validator.json` summarizes leakage, drift, baseline, multi-seed, and shuffled-label evidence.
- Regression resistance: planted failures for leakage, train/test overlap, preprocessing scope, missing metrics, weak baseline, unstable seeds, bad calibration, insignificant shuffled-label results, distribution drift, and hard examples for imbalanced majority, content duplicates, and temporal leakage.

The hard example fixtures live in `examples/ml_problems/hard_examples/`.

## Other Tooling

- `maw-tools/web_checks.py`: local-file front-end checks for contrast, accessibility, budget, links, markup, style extraction, changed CSS values, and design-token drift.
- `maw-tools/dependency_risk_audit.py`: Python dependency/coupling risk audit with optional annotations and severity gating.
- `maw-tools/behavior_baseline.py`: refactor behavior manifest/diff and related refactor checks.
- `maw-tools/validate_handoffs.py`: checks generated handoffs contain all required sections and no placeholders.
- `maw-tools/validate_workflow_template.py`: validates template schema and optional run conformance to a declared template.
- `maw-tools/run_report.py`: writes `artifacts/run-summary.md` with task type, caps, role pipeline, deterministic gate status, required evidence status, and final verdict.
- `maw-tools/checklist_check.py`: checks `.codex/checklists/` entries link to known deterministic evidence artifacts.
- `maw-tools/check_vendored_data.py`: fails when package-data mirrors drift from top-level `maw-tools/`, `templates/workflows/`, `examples/ml_problems/`, or `packs/`.
- `maw-tools/readme_check.py`: fails when README `maw ...` subcommands or literal path references drift from the codebase.

Task risk checklists live in `.codex/checklists/`. They are the source of checklist invariants; this README only summarizes them.

## Tests

```bash
python -m unittest discover -s tests
python maw-tools/selftest_all.py
python maw-tools/selftest_ml_checks.py
python maw-tools/check_vendored_data.py
python maw-tools/readme_check.py
```

`selftest_all.py` aggregates core checks, web checks, ML checks, refactor checks, plan-gate checks, checklist validation, README reference validation, and vendored package-data drift validation.

Manual pre-release WILDS smoke check, not part of `unittest discover`:

```bash
MAW_WILDS_SMOKE=1 python tests/manual_wilds_smoke.py
```

This offline check requires the WILDS package and a locally available `civilcomments` dataset. It runs `maw wilds-benchmark` on the real `civilcomments` validation split with `download=False` and asserts that `dataset.eval(...)` returns parseable metrics. Set `MAW_WILDS_ROOT` to the local WILDS data root when needed, or `MAW_WILDS_SPLIT` to override the default `val` split.

Manual CivilComments baseline loop, also not part of `unittest discover`:

```bash
maw wilds-export --wilds-dataset civilcomments --split val --limit 500 --output artifacts/civilcomments-val-500.jsonl --model-cmd "python model.py {input} {output}" --score-output artifacts/civilcomments-val-500-score.json
maw wilds-loop --score artifacts/civilcomments-val-500-score.json --predictions artifacts/civilcomments-val-500-predictions.jsonl --majority-accuracy 0.5
```

This requires WILDS, scikit-learn, and a local CivilComments dataset. The resulting score JSON confirms real WILDS metrics when `passed` is true and `metrics_source` is `wilds.dataset.eval`.

## Examples

`examples/sample_run/` is a small complete run folder; `examples/sample_app/` is a tiny deterministic test target:

```bash
python maw-tools/validate_handoffs.py examples/sample_run
python maw-tools/acceptance_check.py --run examples/sample_run --test-cmd "python test_textutil.py" --test-cwd examples/sample_app
```

Additional examples live under `examples/ml_problems/`, `examples/frontend_demo/`, `examples/change_demo/`, and `examples/workflow_specific_examples/`.
