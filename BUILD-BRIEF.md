# Build Brief — Formalize the Multi-Agent Workflow project

**Audience:** Claude Code, running in a terminal inside this repository
(`multi-agent-workflow`). **Goal:** turn the design docs in `./docs/` into a
real, runnable, version-controlled implementation — the zero-extra-cost build
described in `docs/08-build-strategy.md`.

---

## Before you start — read these

Read the design docs in order; they are the source of truth. Do not invent
features that contradict them; if something is ambiguous, prefer the simpler
option and leave a `# MAW-TODO` note.

- `docs/00-overview.md` — what the project is, the core mental model
- `docs/01-architecture.md` — layers, conductor, roster, governor, acceptance gate
- `docs/02-patterns.md` — orchestration patterns (pipeline, orchestrate, parallel, route, refine, conductor)
- `docs/05-memory-and-handoffs.md` — the markdown memory + hand-off conventions (important: follow the templates exactly)
- `docs/06-ml-validation.md` and `docs/07-code-and-debugging.md` — the two domain packs
- `docs/08-build-strategy.md` — **the build plan you are executing** (subscription-only, Claude Code native)

## Scope for THIS pass (Phases 1–3 of doc 08)

Build a minimal but genuinely working version. Do **not** try to build every
agent in the docs yet. Target:

1. A small **roster** of subagents.
2. The **`/maw` conductor skill** that assesses a task, picks a subset of the
   roster, delegates, and enforces the memory + hand-off conventions.
3. A couple of **deterministic helper scripts** (plain Python, no model calls).
4. A working **example run** proving the chain executes end to end.

## Where to put things

Build the configuration **into this repository** (project scope), so it is
version-controlled and visible on GitHub. Create:

```
.claude/
├── agents/
│   ├── conductor.md        # assesses task, selects team, delegates, runs the loop
│   ├── planner.md          # decomposes the task into steps
│   ├── worker.md           # does the actual work of a step
│   ├── critic.md           # evaluates output against an explicit rubric (refine loop)
│   └── acceptance_gate.md  # INDEPENDENT final check: conformance + claim-to-evidence + smoke test
├── skills/
│   └── maw/
│       └── SKILL.md        # entry point: /maw <problem>
CLAUDE.md                   # the conventions (see below)
maw-tools/
│   ├── scaffold_run.py     # create a run folder with memory.md / handoffs/ / artifacts/
│   └── checks.py           # a couple of deterministic checks (e.g. run a test command, basic stats)
examples/
│   └── README.md           # one worked example invocation + what the run folder looked like
.gitignore                  # ignore runs/, __pycache__/, etc.
```

Also add a short `INSTALL.md` explaining how to make this available globally
(copy or symlink `.claude/agents` and `.claude/skills` into `~/.claude/`), so it
can be used from any folder later — but the canonical copy lives in this repo.

## How each piece should behave

**Subagents (`.claude/agents/*.md`)** — YAML frontmatter (`name`, `description`,
`tools`, `model`) + a tight system-prompt body. Use cheap models for routine
roles (`model: haiku` for `worker`, `critic`) and a stronger model for
`conductor` and `acceptance_gate` (`model: opus` or `sonnet`). Keep prompts lean.

**Conductor skill (`.claude/skills/maw/SKILL.md`)** — the orchestration logic as
a prompt. It should: (a) read the task, (b) decide which roles are actually
needed and how many — conservative by default, escalating only if the critic
fails the work, (c) call `maw-tools/scaffold_run.py` to create the run folder,
(d) delegate to subagents, writing/reading the markdown hand-off notes per
`docs/05`, (e) run the refine loop until the critic's bar is met or a max-iters
cap, (f) finish with the independent `acceptance_gate`. Enforce the governor
caps from `docs/01` (max agents, max iters).

**Memory & hand-offs** — follow `docs/05` exactly: a `runs/<timestamp>_<slug>/`
folder with `memory.md` (shared journal), `agents/<name>.md` (local notes),
`handoffs/NN_from__to__to.md` (use the exact hand-off template), and
`artifacts/`. The hand-off files are how agents pass work — do not skip them.

**Deterministic tools** — `maw-tools/` scripts are plain Python invoked via Bash.
They must not call any model. `checks.py` should expose at least a "run this test
command and report pass/fail" function; add one simple stats check as a
demonstration. The design rule is *compute first, reason second*.

## Acceptance criteria (verify before you call it done)

- Running `/maw <a simple task>` in this repo creates a run folder, delegates to
  at least two subagents via hand-off files, runs the critic loop, passes the
  acceptance gate, and produces an output. Show me the resulting run folder.
- The hand-off files match the template in `docs/05`.
- `maw-tools/*.py` run standalone with no model/network calls.
- Update `README.md`: change the status line from "implementation in progress" to
  reflect that a working minimal version now exists, and add a short "Quick start"
  showing the `/maw` command. Keep it honest — describe only what actually works.
- Add `.gitignore` (ignore `runs/`, `__pycache__/`, `*.pyc`).
- Commit everything with clear messages. Do **not** push unless I ask.

## Important: be honest

This repo backs a résumé claim, so accuracy matters more than impressiveness.
Only describe features that actually run. If a piece is stubbed or partial, say so
in the README and mark it `# MAW-TODO`. A small thing that genuinely works beats a
large thing that only looks finished.

## After this pass

Stop and summarize: what you built, what works, what's stubbed, and what Phase 4
(the full ML and code rosters) would add. I'll review before we go further.
