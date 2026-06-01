# Worked example — `/maw` end to end

This is a real, recorded run of the minimal `/maw` conductor. It proves the chain
executes end to end: the conductor assembles a small team, delegates to **four
separate subagents** through markdown hand-off files, runs the refine loop, and
finishes with an **independent acceptance gate** — all on disk, reconstructable.

## The task

`sample_app/` contains a deliberately unimplemented function and a dependency-free
test:

- `sample_app/textutil.py` — `normalize_whitespace(text)` (started as a stub that
  raised `NotImplementedError`).
- `sample_app/test_textutil.py` — 6 cases; runnable with `python test_textutil.py`
  (exit 0 = pass), so the test runner needs no pytest.

The invocation:

```
/maw Implement normalize_whitespace in examples/sample_app/textutil.py so the tests pass
```

(On a machine where `python` isn't on PATH, the tools were invoked with `uv run`.)

## What happened

| Step | Agent (subagent) | Did | Hand-off written |
|---|---|---|---|
| Plan | conductor | assessed task, picked the team, set the bar, wrote `run.md` | `01_conductor__to__planner.md` |
| 1 | planner (sonnet) | decomposed into `artifacts/plan.md` | `02_planner__to__worker.md` |
| 2 | worker (haiku) | implemented the function, ran the test (`passed: true`) | `03_worker__to__critic.md` |
| 3 | critic (haiku) | re-ran the test, scored 15/15, **PASS** → `artifacts/eval_report.md` | `04_critic__to__acceptance_gate.md` |
| 4 | acceptance_gate (sonnet) | independent re-run + claim audit → **SHIP** → `artifacts/acceptance.md` | — (terminal) |

The refine loop cleared the bar on iteration 1 (max 3), so no revise cycle was
needed. The deliverable: `normalize_whitespace` implemented as
`return " ".join(text.split())`, with `test_textutil.py` green.

## The resulting run folder

```
runs/2026-06-01_implement-normalize-whitespace-in_81aa/
├── run.md                  # conductor plan + final SHIP summary
├── memory.md               # shared journal: one timestamped entry per agent
├── agents/
│   ├── conductor.md  planner.md  worker.md  critic.md  acceptance_gate.md
├── handoffs/
│   ├── 01_conductor__to__planner.md
│   ├── 02_planner__to__worker.md
│   ├── 03_worker__to__critic.md
│   └── 04_critic__to__acceptance_gate.md
└── artifacts/
    ├── plan.md             # the decomposition
    ├── eval_report.md      # critic's rubric scores + evidence
    └── acceptance.md       # gate's SHIP verdict + the three checks
```

Every hand-off file follows the fixed template in
[`../docs/05-memory-and-handoffs.md`](../docs/05-memory-and-handoffs.md): *Task
context · What I did · Output/artifacts · Open questions/risks · Recommended next
step*.

> Run folders are git-ignored (they're local logbooks). This example describes a
> run rather than committing the folder. To reproduce it, reset the deliverable
> stub and re-run:
>
> ```bash
> # restore the unimplemented stub, then:
> /maw Implement normalize_whitespace in examples/sample_app/textutil.py so the tests pass
> ```

## Reproduce the tools directly (no model needed)

```bash
python maw-tools/scaffold_run.py init "demo task" --agents planner,worker,critic --json
python maw-tools/checks.py test --cmd "python test_textutil.py" --cwd examples/sample_app
python maw-tools/checks.py stats 0.81 0.83 0.79 0.85
python maw-tools/checks.py gap --train 0.98 --test 0.81 --tol 0.05
# (use `uv run` / `py` if `python` is not on PATH)
```
