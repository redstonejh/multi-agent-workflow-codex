---
name: maw
description: Run a Codex-native multi-agent workflow with conductor, planner, worker, critic, acceptance gate, markdown handoffs, deterministic checks, and auditable run folders.
---

# Codex Multi-Agent Workflow

Use this skill when the user asks for MAW, a multi-agent workflow, a conductor/planner/worker/critic/acceptance-gate loop, auditable handoffs, or deterministic acceptance checks.

MAW uses core agents for most runs. Workflow templates may add optional
specialized agents for ML validation, debugging, dependency analysis, research
aggregation, or similar focused work. There is no separate mode for these
capabilities.

## Workflow

1. Read `AGENTS.md` and the relevant `.codex/agents/<role>.md` files.
2. Scaffold a run folder:

   ```bash
   python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
   ```

3. Conductor proposes a structured plan in `artifacts/conductor-plan.json`, including `task_type`, `roles`, `caps`, optional `parallel_roles`, and optional `role_justifications`. Generic core-agent tasks may use the default caps. Workflow templates and specialist tasks must use the template's explicit caps; do not drop core roles to fit a cap.
4. Run the pre-execution plan gate:

   ```bash
   uv run python maw-tools/plan_check.py --file artifacts/conductor-plan.json
   ```

5. `plan_reviewer` reviews the plan and returns `APPROVE` or `REVISE`. The reviewer is advisory; `plan_check.py` is the hard deterministic gate.
6. If `plan_check.py` fails or `plan_reviewer` returns `REVISE`, conductor replans and reruns the gate. Cap the replan loop at 2 revisions.
7. Only execute after the plan gate passes. Record the proposed plan, plan check result, plan reviewer verdict, final accepted plan, and revision count in `run.md` or artifacts.
8. Planner writes a concrete plan and creates a `planner -> worker` handoff.
9. Worker implements or drafts the requested output and creates a `worker -> critic` handoff.
10. Critic runs deterministic checks where possible and returns PASS or a specific revision request.
11. Repeat worker/critic up to `max_iters` if needed.
12. Acceptance gate validates handoffs, plan-gate evidence, and deterministic results, then records `SHIP`, `NO-SHIP`, or `NEEDS-HUMAN`.

## Deterministic Commands

```bash
python maw-tools/scaffold_run.py handoff --run <run_dir> --from <from_agent> --to <to_agent>
python maw-tools/validate_handoffs.py <run_dir>
python maw-tools/checks.py test --cmd "<test command>" --cwd <path>
python maw-tools/acceptance_check.py --run <run_dir> --test-cmd "<test command>" --test-cwd <path>
uv run python maw-tools/plan_check.py --file <conductor-plan.json>
```

## Handoff Rules

Every handoff must include and fill:

- `## Task context`
- `## What I did`
- `## Output / artifacts`
- `## Open questions / risks`
- `## Recommended next step`

Do not leave generated placeholders in completed handoffs. Keep artifacts in `artifacts/` when they are specific to one run.

## Subagents

If Codex subagent tools are available and delegation is authorized, use the role prompts in `.codex/agents/`. Otherwise run the roles sequentially in the current Codex session while preserving the same files and handoffs.
