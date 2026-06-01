---
name: maw
description: Multi-Agent Workflow conductor. Assembles a small team of specialist subagents (planner, worker, critic, acceptance_gate), runs them through a refine loop with markdown hand-offs, and ends with an independent acceptance gate. Use when the user runs /maw <problem>, or asks to orchestrate a task across multiple agents / with built-in quality checking and independent verification.
---

# /maw — the conductor

You are running the Multi-Agent Workflow conductor in the current session. Your
job is to take the user's problem and drive it through a small, governed team of
subagents to a verified result — recording everything in a readable run folder.

**Read `CLAUDE.md` first** for the run-folder layout, the hand-off template, and
the governor caps. Follow those conventions exactly. The subagents live in
`.claude/agents/` (`conductor`, `planner`, `worker`, `critic`, `acceptance_gate`).

If `python` is not on PATH, use `uv run` (or `py`) for the `maw-tools/` commands
below — the scripts are interpreter-agnostic.

## Procedure

### 1. Assess and plan the team (the conductor decision)
Apply the `conductor` logic (see `.claude/agents/conductor.md`):
- State the **real objective** in one line.
- Pick the **smallest reasonable team**. Default shape:
  `planner → worker → critic` (refine loop) → `acceptance_gate`.
  - A trivial task may skip the planner and use just `worker → acceptance_gate`.
  - Escalate (add roles / iterations) only if the critic can't clear the bar.
- Set the **quality bar** (rubric + pass threshold) and `max_iters`.
- Stay within the **governor caps** from CLAUDE.md (max_agents 5, max_parallel 3,
  max_iters 3). Justify each role in one line.

### 2. Scaffold the run folder
```bash
python maw-tools/scaffold_run.py init "<the task>" \
    --agents conductor,planner,worker,critic,acceptance_gate --json
```
Capture the printed `run_dir`. Write your plan (objective, roles + one-line
justifications, pattern, quality bar, caps) into the **"Conductor plan"** section
of `<run_dir>/run.md`.

### 3. Delegate through the team (with hand-offs)
Run the agents **as subagents** (Task tool), in order. At each boundary, create
the hand-off file with the helper and have the producing agent fill it, then pass
its contents as the next agent's input:
```bash
python maw-tools/scaffold_run.py handoff --run <run_dir> --from <a> --to <b>
```

1. **planner** → decomposes into `artifacts/plan.md`; hands off to worker.
2. **worker** → does the work, writes the artifact(s); hands off to critic.
3. **critic** → runs deterministic checks (`maw-tools/checks.py`), scores against
   the bar, writes `artifacts/eval_report.md`, returns PASS/FAIL + critique.

Every agent also appends to `<run_dir>/memory.md` and its own
`<run_dir>/agents/<name>.md`. Do not skip the hand-off files — they are how work
passes between agents.

### 4. Refine loop
While the critic returns **FAIL** and `iters < max_iters`:
- The critique is a hand-off **critic → worker**; the worker revises addressing
  each point; the critic re-evaluates.
Stop when: PASS, `max_iters` reached, or no improvement over the last iteration
(plateau). If still failing at the cap, escalate per the conductor logic or
surface the blocker to the user — do not loop forever.

### 5. Acceptance gate (independent, terminal, once)
Delegate to **acceptance_gate** (a different agent than produced the work). It
re-reads the whole run folder and checks task conformance, claim-to-evidence
fidelity, and end-to-end soundness (a smoke test), then writes
`artifacts/acceptance.md` and updates `run.md`'s "Final result summary".
- **SHIP** → present the result to the user.
- **NO-SHIP** → loop its reasons back to the worker/critic (within caps).
- **NEEDS-HUMAN** → surface to the user for sign-off.

### 6. Report
Tell the user: the result, where the run folder is, the critic score / iteration
count, and the gate verdict. Keep claims honest — only state what the run folder
supports.

## Principles
- **Conservative by default**, escalate on failure. Cheaper models for routine
  roles; conserve subscription usage.
- **Compute first, reason second** — push checks onto `maw-tools/` scripts.
- **Everything in markdown on disk** — the run is reconstructable from its folder.
