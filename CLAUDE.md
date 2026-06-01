# Multi-Agent Workflow — Conventions

This repo is a **library of configuration** that Claude Code executes on your
subscription (no API key, no per-token cost). The "intelligence" lives in
subagents (`.claude/agents/`) and the `/maw` skill (`.claude/skills/maw/`); the
only real *code* is non-AI plumbing in `maw-tools/` (run via Bash, free).

These are the conventions every agent and the conductor must follow. They
realize docs `01` (architecture), `05` (memory & hand-offs), `06`/`07` (domain
packs). When something is ambiguous, prefer the simpler option and leave a
`# MAW-TODO` note.

---

## Running the deterministic tools

`maw-tools/*.py` are plain stdlib Python 3 — no third-party deps, no model, no
network. Invoke them via Bash:

```bash
python maw-tools/scaffold_run.py init "<task>" --agents conductor,planner,worker,critic,acceptance_gate --json
python maw-tools/checks.py test --cmd "<test command>"
```

If `python` is not on PATH (e.g. this Windows machine, where it resolves to a
Microsoft Store stub), use a fallback that is: **`uv run maw-tools/...`** (uv is
installed), or `py maw-tools/...`. The scripts themselves are interpreter-
agnostic. **Compute first, reason second:** push every check that can be a
deterministic script onto `maw-tools/`, and let agents only *interpret* the
result.

---

## The run folder (docs/05)

Every `/maw` run gets a folder, created by `scaffold_run.py init`:

```
runs/<date>_<slug>_<id>/
├── run.md            # conductor plan + final result summary
├── memory.md         # shared journal (append-only, timestamped)
├── agents/<name>.md  # each agent's local scratchpad notes
├── handoffs/NN_<from>__to__<to>.md   # ordered hand-off notes
└── artifacts/        # named outputs (plan.md, draft.md, eval_report.md, ...)
```

`runs/` is git-ignored — it is a local logbook, not source.

### Shared journal (`memory.md`)
Append one short, timestamped entry per agent turn: `## HH:MM — <agent>` then
2-4 lines (what you did, where output landed, next step). Read the recent tail
on start for situational awareness.

### Local memory (`agents/<name>.md`)
Read your own file on start ("your notes so far"); append a short structured
note on finish (conclusions, decisions, open threads).

---

## Hand-offs (the part that removes manual prompting)

At **every boundary** where one agent's output feeds another, write a hand-off
note and pass it as the next agent's input. Create the file with the helper so
the naming and template are enforced by code:

```bash
python maw-tools/scaffold_run.py handoff --run <run_dir> --from planner --to worker
```

Then fill the template. **Use this exact template** (docs/05) — it is both
human-readable and machine-parseable:

```markdown
# Hand-off: <from> → <to>  (run <id>, step NN)

## Task context
What we're ultimately trying to achieve, in 1-2 lines.

## What I did
The concrete work completed in this step.

## Output / artifacts
- artifacts/<file>  (what it is)
- key result values inline if small

## Open questions / risks
Things the next agent should watch out for.

## Recommended next step
What the next agent should do, specifically.
```

In the `refine` loop, the critic's critique **is** a hand-off back to the worker
(`critic → worker`), so "revise with this feedback" needs no manual wiring.

---

## Governor caps (docs/01 — hard limits)

The conductor must stay within these unless the user explicitly raises them:

| Cap | Default | Meaning |
|---|---|---|
| `max_agents` | 5 | total subagent roles used in a run |
| `max_parallel` | 3 | concurrent subagents |
| `max_iters` | 3 | refine (generate→evaluate→revise) iterations |

**Conservative by default:** start with the smallest reasonable team (a trivial
task may need a single agent). **Escalate only on failure** — add roles or
iterations only when the critic can't clear the bar. Every role added to a plan
needs a one-line justification in `run.md`.

---

## Two-tier verification (docs/01)

1. **Component check — `critic`** (inside the `refine` loop): scores the work
   against an explicit rubric and returns *actionable* critique, looping until
   the bar is met or `max_iters` is hit.
2. **Acceptance gate — `acceptance_gate`** (terminal, once, **independent**): a
   different agent than produced the work checks (a) task conformance — does it
   answer the *real* ask; (b) claim-to-evidence — does every claim trace to
   something recorded in the run folder; (c) end-to-end soundness — does it
   actually run (a smoke test). Returns **SHIP / NO-SHIP** + reasons. NO-SHIP
   loops back with the reasons; high-stakes/uncertain → human sign-off.

---

## Code-work annotation tags (docs/07 — all greppable)

When working on real code, record non-obvious couplings both **inline** (right
above the line) and **centrally** in a `deps.md`, linked by a stable ID:

- `# MAW-DEP[id]:` — hidden dependency / implicit precondition
- `# MAW-BUG[id]:` — known bug or caveat at this spot
- `# MAW-RCA[id]:` — why this code is the way it is (links to an RCA)
- `# MAW-TODO[id]:` — deferred work

Comment the **why, never the what**. Bug reports, RCAs, and the dependency map
follow the templates in docs/07.
