# Codex Multi-Agent Workflow

Codex Multi-Agent Workflow (MAW) is a Codex CLI convention for running one task through a small team of roles: conductor, planner, worker, critic, and acceptance gate. The workflow is file-backed: every run gets a local folder with markdown handoffs, shared memory, role notes, artifacts, and deterministic Python check output.

This repo is intentionally Codex-only. It uses `AGENTS.md`, `.codex/skills/maw/SKILL.md`, optional `.codex/agents/` role definitions, and stdlib Python helper scripts.

See `docs/maw-architecture.md` for the unified MAW architecture: core agents
are used in most runs, and specialized agents are optional template-driven
capabilities.

## Install

Use the repo directly from Codex CLI:

```text
Use $maw to fix the failing test in this repo.
```

To make the skill available in another workspace, copy these paths into that workspace:

```text
AGENTS.md
.codex/skills/maw/SKILL.md
.codex/agents/
maw-tools/
```

No package installation is required. The scripts use Python 3.11+ standard library only. On Windows, use `py` or `uv run python` if `python` is not on `PATH`.

Install the `maw` command from this checkout:

```bash
python -m pip install -e .
maw list-templates
maw start standard-software-task "implement a parser"
```

Without installation, the local wrapper still works:

```bash
python maw.py list-templates
```

## Usage

Use the single MAW CLI:

```bash
python maw.py list-templates
python maw.py start standard-software-task "implement a parser" --run-root runs
python maw.py validate-template standard-software-task
python maw.py validate-handoffs runs/<run_id>
python maw.py acceptance runs/<run_id> --test-cmd "python -m unittest discover -s tests"
python maw.py plan-graph artifacts/task-graph.json
python maw.py dependency-audit path/to/package --fail-on high
```

Create a run folder:

```bash
python maw-tools/scaffold_run.py init "implement normalize_whitespace" --agents conductor,planner,worker,critic,acceptance_gate --json
```

Create a handoff:

```bash
python maw-tools/scaffold_run.py handoff --run runs/<run_id> --from planner --to worker
```

Validate handoffs:

```bash
python maw-tools/validate_handoffs.py runs/<run_id>
```

Run deterministic checks:

```bash
python maw-tools/checks.py test --cmd "python test_textutil.py" --cwd examples/sample_app
python maw-tools/checks.py gap --train 0.91 --test 0.88 --tol 0.05
python maw-tools/checks.py dependency-map --file examples/workflow_specific_examples/dependency-map.json
python maw-tools/checks.py aggregation --file examples/workflow_specific_examples/research-aggregation.json
python maw-tools/dependency_risk_audit.py path/to/package --output dependency-risk-report.json
```

Run an acceptance gate over a completed run:

```bash
python maw-tools/acceptance_check.py --run runs/<run_id> --test-cmd "python test_textutil.py" --test-cwd examples/sample_app
```

Plan a multi-worker task graph:

```bash
python maw-tools/task_graph.py plan --file artifacts/task-graph.json
```

The graph planner validates task dependencies and emits stages. Independent
`worker` tasks in the same stage can be delegated concurrently, followed by
`aggregate` and `merge` stages before critic and acceptance review.

Validate workflow templates:

```bash
python maw-tools/validate_workflow_template.py
python maw-tools/validate_workflow_template.py --run runs/<run_id>
```

Start a run from a workflow template:

```bash
python maw-tools/start_workflow.py standard-software-task "add a CLI flag" --json
python maw-tools/start_workflow.py bug-investigation "investigate failing payment test"
python maw-tools/start_workflow.py multi-agent-research-task "compare task planning approaches"
```

Declare a template in `run.md`:

```markdown
- Workflow template: standard-software-task
```

Available templates live in `templates/workflows/`:

```text
standard-software-task
bug-investigation
refactor-task
ml-validation-task
ml-training-task
multi-agent-research-task
frontend-ui-task
```

Each template defines agents, handoff pairs, required artifacts, acceptance gates,
and deterministic checks. A declared run conforms only when its agent notes,
handoffs, and required artifacts match the template.

Most runs use the core agents:

```text
conductor, planner, worker, critic, acceptance_gate
```

Workflow templates may add specialized agents such as
`leakage_auditor`, `overfitting_checker`, `baseline_enforcer`,
`calibration_checker`, `reproducibility_checker`, `data_quality_auditor`,
`debugger`, `bug_hunter`, `dependency_mapper`, `aggregator`, `ui_builder`,
`a11y_auditor`, `responsive_checker`, `perf_budgeter`, `markup_validator`,
`change_verifier`, `style_drift_auditor`, `visual_verifier`, and `ux_critic`.
These roles are activated only when the selected workflow template declares
them.

MAW has one unified workflow system. Specialized agents are optional and
template-driven capabilities used when a
workflow needs ML validation, debugging, dependency analysis, aggregation, or
other focused review.

`start_workflow.py` validates the selected template before creating a run, copies
the template into `artifacts/workflow-template.json`, creates all configured
agent note files, initializes required handoff placeholders, and writes
`artifacts/artifact-checklist.md` for the template's required artifacts.

Run the script tests:

```bash
python -m unittest discover -s tests
```

## Architecture

`AGENTS.md` defines repo-wide behavior and the audit format. `.codex/skills/maw/SKILL.md` is the Codex skill entry point. `.codex/agents/` holds role-specific prompts for Codex environments that support role delegation; otherwise the same roles can run sequentially in one Codex session.

Each run folder has this shape:

```text
runs/<date>_<slug>_<id>/
|-- run.md
|-- memory.md
|-- agents/
|   |-- conductor.md
|   |-- planner.md
|   |-- worker.md
|   |-- critic.md
|   `-- acceptance_gate.md
|-- handoffs/
|   `-- 01_planner__to__worker.md
`-- artifacts/
```

The normal loop is:

```text
conductor -> planner -> worker -> critic -> worker if needed -> acceptance_gate
```

The critic checks the work inside the refine loop. The acceptance gate performs the final independent check and returns `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

Specialized role prompts live in `.codex/agents/`. Each prompt declares
mission, inputs, outputs, required artifacts, deterministic tools, and pass/fail
criteria.

## Examples

See `examples/sample_run/` for a small complete run folder and `examples/sample_app/` for a tiny deterministic test target.

The sample app check is:

```bash
python maw-tools/checks.py test --cmd "python test_textutil.py" --cwd examples/sample_app
```

The sample run can be validated with:

```bash
python maw-tools/validate_handoffs.py examples/sample_run
python maw-tools/acceptance_check.py --run examples/sample_run --test-cmd "python test_textutil.py" --test-cwd examples/sample_app
```

Executable toy ML problems live in `examples/ml_problems/`:

```bash
python examples/ml_problems/classification/run.py --output classification.json
python examples/ml_problems/regression/run.py --output regression.json
python examples/ml_problems/data_validation/run.py --output data_validation.json
python examples/ml_problems/ml_checks.py classification.json
```

Start ML workflow runs from templates:

```bash
python maw.py start ml-validation-task "validate the toy classification baseline"
python maw.py start ml-training-task "train the toy regression baseline"
```

The toy ML runners emit JSON with generated data metadata, baseline model,
metrics, split ids, expected seed, and acceptance criteria. `ml_checks.py`
performs deterministic checks for metric thresholds, target leakage in features,
train/test split overlap and ratio, and reproducibility seed.

Fit diagnosis checks flag overfitting and underfitting:

```bash
python examples/ml_problems/ml_checks.py fit-diagnosis \
  --problem-type classification \
  --metrics-json "{\"train_score\": 0.98, \"validation_score\": 0.72, \"test_score\": 0.69}" \
  --output fit-diagnosis.json

python examples/ml_problems/ml_checks.py fit-diagnosis \
  --problem-type regression \
  --metrics-json "{\"train_error\": 0.2, \"validation_error\": 0.8, \"test_error\": 0.75}" \
  --max-error-ratio 2.0
```

The fit diagnosis JSON artifact includes `status` (`healthy`, `overfit`,
`underfit`, or `invalid`), `passed`, `metrics`, `thresholds`, and `reasons`.

ML validation checks also support baseline, calibration, reproducibility, and data
quality artifacts:

```bash
python examples/ml_problems/ml_checks.py baseline \
  --metrics-json "{\"model_score\": 0.84, \"baseline_score\": 0.78}" \
  --min-improvement 0.03

python examples/ml_problems/ml_checks.py calibration \
  --data-json "{\"confidences\": [0.8, 0.7, 0.2], \"correct\": [true, true, false]}" \
  --max-ece 0.12

python examples/ml_problems/ml_checks.py reproducibility \
  --data-json "{\"seed\": 42, \"expected_seed\": 42, \"deterministic\": true}"

python examples/ml_problems/ml_checks.py data-quality \
  --data-json "{\"row_count\": 100, \"missing_values\": {\"x\": 0}, \"duplicate_rows\": 0}"
```

Workflow-specific examples live in `examples/workflow_specific_examples/`.

## Front-End / UI Pack

The front-end/UI workflow pack works now for deterministic, browser-free checks
that operate on local files. It does not render pages.

Workflow template:

```bash
uv run python maw.py start frontend-ui-task "audit a static landing page"
```

Front-end agents:

```text
ui_builder
a11y_auditor
responsive_checker
perf_budgeter
markup_validator
change_verifier
style_drift_auditor
visual_verifier
ux_critic
```

Deterministic checks:

```bash
uv run python maw-tools/web_checks.py contrast --foreground "#111827" --background "#ffffff"
uv run python maw-tools/web_checks.py a11y examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py budget examples/frontend_demo/index.html --max-bytes 4096 --max-elements 80 --max-assets 5
uv run python maw-tools/web_checks.py links examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py markup examples/frontend_demo/index.html
uv run python maw-tools/web_checks.py style examples/change_demo/style.after.css --selector ".btn" --property background
uv run python maw-tools/web_checks.py changed --before examples/change_demo/style.before.css --after examples/change_demo/style.after.css --selector ".btn" --property background --expected "#1a73e8"
uv run python maw-tools/web_checks.py tokens --token-file examples/change_demo/design-tokens.json examples/change_demo/style.after.css
```

Checks implemented:

```text
contrast: WCAG contrast ratio for two hex colors, threshold 4.5 or 3.0 with --large
a11y: missing image alt, unlabeled controls, skipped heading levels, missing html lang, missing title, missing viewport meta
budget: local HTML/CSS/JS/assets byte budget and element/asset counts
links: internal links, anchors, and local assets resolve
markup: unclosed tags and duplicate ids using html.parser
style: extract a selector/property value from CSS
changed: prove a file or selector/property target changed from a pre-change snapshot, optionally to an expected value
tokens: scan CSS against design-tokens.json and fail on design-token drift
```

Demo path:

```text
examples/frontend_demo/
examples/change_demo/
```

The front-end demo keeps `index.initial.html` as the planted red fixture and
`index.html` as the fixed green fixture. The change demo proves the request
"make the primary button blue (`#1a73e8`) and larger" with happy-path,
no-op-failure, and token-drift-failure fixtures.

Run the front-end pack self-tests:

```bash
uv run python maw-tools/selftest_web_checks.py
uv run python maw-tools/selftest_all.py
```

`ux_critic` records advisory usability and aesthetic critique. Hard PASS/FAIL
comes from deterministic checks.

`# MAW-TODO`: true visual regression.
`# MAW-TODO`: browser rendering checks.
`# MAW-TODO`: hard-gated aesthetic judgment.
`# MAW-TODO`: real viewport screenshot testing.
`# MAW-TODO`: automated browser screenshot diff.
`# MAW-TODO`: hard-gated visual judgment.
`# MAW-TODO`: real rendered viewport comparison.

## Dependency Risk Audit

Use `dependency-risk-audit` when a bug, refactor, or multi-worker
plan could be affected by fragile hidden dependencies. It scans Python source for
signals such as global state reads or mutations, environment variable access,
current-working-directory dependencies, time or randomness without injection,
shared mutable arguments, duplicated magic strings, broad imports, import-time
side effects, cross-module calls, fan-in/fan-out risks, circular imports, and
large mixed-responsibility functions.

Run it directly:

```bash
python maw-tools/dependency_risk_audit.py path/to/package
python maw-tools/dependency_risk_audit.py path/to/package --fail-on high
python maw-tools/dependency_risk_audit.py path/to/package --annotate --dry-run
python maw-tools/dependency_risk_audit.py path/to/package --annotate
```

Or through the single CLI:

```bash
python maw.py dependency-audit path/to/package
python maw.py dependency-audit path/to/package --annotate
python maw.py dependency-audit path/to/package --dry-run
python maw.py dependency-audit path/to/package --fail-on high
```

Annotation mode inserts short comments like:

```python
# MAW-DEPENDENCY-RISK: Changing this may affect config/defaults.py. Reason: implicit coupling magic string. See docs/bugs/MAW-BUG-1234ABCD.md
```

Review annotations before committing. They are intended for non-obvious coupling,
not for every low-risk static-analysis finding. High-severity risks generate bug
dossiers under `docs/bugs/` using the format documented in
`docs/bug-dossiers.md`; see `docs/bugs/MAW-BUG-0003.md` for a sample.
