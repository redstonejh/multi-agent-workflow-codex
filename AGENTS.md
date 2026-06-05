# Codex Multi-Agent Workflow - Repo Instructions

This repository defines a Codex-native Multi-Agent Workflow (MAW). The workflow uses a small team of roles, markdown handoffs, deterministic Python checks, and auditable run folders.

The main Codex entry point is `.codex/skills/maw/SKILL.md`. Role definitions live in `.codex/agents/`. Deterministic tools live in `maw-tools/` and must use only the Python standard library.

## Roles

- `conductor`: selects the smallest useful team, records the run plan, and enforces caps.
- `planner`: decomposes the task into concrete steps and acceptance criteria.
- `worker`: implements the plan and records outputs.
- `critic`: evaluates the worker output against the criteria and deterministic check results.
- `acceptance_gate`: performs the final independent check and records `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

Some workflow templates add specialized agents for ML validation, debugging,
dependency analysis, research aggregation, salvage verification, or other
focused review. These agents are optional and template-driven. MAW has one
unified workflow system; there is no separate mode for specialized capabilities.

The `salvage` task type is a system-level polyglot refactor workflow for gutting
legacy code while preserving a frozen surface. Its hard gates are preserved
behavior parity, static-first test triage, hidden dependency and cross-language
coupling proof, dead-code proof, duplicate collapse, and salvage resistance. The required roster is the
core roles plus `dependency_mapper`, `dependency_untangler`, and
`dead_code_auditor`; `salvage_verifier` is advisory. `maw-tools/` evaluates only
normalized JSON artifacts and remains standard-library-only: Python graph
generation uses `ast`, HTML/CSS graph generation uses `html.parser` plus
`web_checks.py`, characterization replay uses stdlib HTTP/JSON, and test triage
uses static symbol evidence before any target test suite execution. JS/TS graph
generation and client-rendered browser capture live outside the deterministic
spine in `maw_cli/`; when optional Node or browser dependencies are unavailable,
those adapters must emit `NEEDS-HUMAN` rather than guessing.

Default caps:

| Cap | Default |
|---|---:|
| `max_agents` | 5 |
| `max_parallel` | 3 |
| `max_iters` | 3 |

The default `max_agents` cap is for generic core-agent runs. Workflow templates
that require specialist agents must declare explicit larger caps, and the
pre-execution plan gate rejects specialist plans whose `max_agents` cannot fit
the full core roster plus required specialists.

## Deterministic Tools

Use deterministic checks whenever possible before relying on model judgment:

```bash
python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
python maw-tools/scaffold_run.py handoff --run <run_dir> --from planner --to worker
python maw-tools/validate_handoffs.py <run_dir>
python maw-tools/checks.py test --cmd "<test command>"
python maw-tools/acceptance_check.py --run <run_dir> --test-cmd "<test command>"
python maw-tools/salvage_check.py verdict <run_dir>
maw start salvage-task "<task>"
maw code-graph <path> [--lang auto|py|js|ts|html|css] --output artifacts/code-graph.json
python maw-tools/salvage_check.py test-triage --root <path> --graph artifacts/code-graph.json --plan artifacts/salvage-plan.md --test-cmd "<active test command with {tests}>" --output artifacts/test-triage.json
maw characterize <path-or-url> --output artifacts/characterization-baseline.json
maw salvage-check <run_dir>
```

On Windows, `py` or `uv run python` are acceptable substitutes when `python` is unavailable.

## Run Folder

Every run folder must contain:

```text
run.md
memory.md
agents/<role>.md
handoffs/NN_<from>__to__<to>.md
artifacts/
```

Append one short entry per role turn to `memory.md`:

```markdown
## HH:MM - <agent>
What changed, where output landed, and the next step.
```

Each role may append scratch notes to `agents/<role>.md`.

## Handoffs

Create handoffs with `maw-tools/scaffold_run.py handoff`. Fill every generated section:

```markdown
# Hand-off: <from> -> <to>  (run <id>, step NN)

## Task context
What we are trying to achieve.

## What I did
Concrete work completed.

## Output / artifacts
- artifacts/<file>  (what it is)

## Open questions / risks
Risks the next role should watch.

## Recommended next step
Specific next action.
```

Validate handoffs before acceptance:

```bash
python maw-tools/validate_handoffs.py <run_dir>
```

## Verification

Use two tiers:

1. `critic`: checks worker output inside the refine loop and requests revision when needed.
2. `acceptance_gate`: independently checks task conformance, claim-to-evidence fidelity, deterministic results, and handoff completeness.

For code work, record non-obvious couplings with:

- `# MAW-DEP[id]:` hidden dependency or implicit precondition
- `# MAW-BUG[id]:` known caveat
- `# MAW-RCA[id]:` why the code is shaped this way
- `# MAW-TODO[id]:` deferred work

For salvage work, freeze `artifacts/preserved-surface.json` and
`artifacts/preserved-surface.sha256` only after static-first test triage defines
the ACTIVE keep-bound test contract. Acceptance and verdict must force `NO-SHIP`
if the preserved surface shrinks, the hash changes, graph entrypoints differ
from the frozen surface, dead-code proof uses a different entrypoint set, parity
lacks a pre-gut characterization baseline, field-level interaction evidence
drifts beyond tolerance, legacy do-not-resurrect symbols return, or a
cross-language coupling is dismissed without a justification.

## Design-Language Packs

Reusable design-language packs live under `packs/` and are mirrored into
`maw_cli/data/packs/`. `packs/liquid-glass/` is the canonical liquid-glass pack:
`kit/` contains the CSS/JS data, `manifest.json` declares the public API and kit
hash, and `reference/reference-render.json` is the frozen computed-CSS oracle.

Use:

```bash
maw apply-design liquid-glass <target> --output artifacts/apply-design.json
maw design-parity <target> --output artifacts/design-parity.json
```

`maw-tools/apply_design.py` and `maw-tools/design_parity.py` must remain Python
standard-library-only. The optional `liquid-glass-webgl.js` file is pack data,
not deterministic-tool logic. When a frontend run selects a design pack,
acceptance should include `artifacts/design-parity.json`.
