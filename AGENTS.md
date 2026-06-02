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
dependency analysis, research aggregation, or other focused review. These agents
are optional and template-driven. MAW has one unified workflow system; there is
no separate mode for specialized capabilities.

Default caps:

| Cap | Default |
|---|---:|
| `max_agents` | 5 |
| `max_parallel` | 3 |
| `max_iters` | 3 |

## Deterministic Tools

Use deterministic checks whenever possible before relying on model judgment:

```bash
python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
python maw-tools/scaffold_run.py handoff --run <run_dir> --from planner --to worker
python maw-tools/validate_handoffs.py <run_dir>
python maw-tools/checks.py test --cmd "<test command>"
python maw-tools/acceptance_check.py --run <run_dir> --test-cmd "<test command>"
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
