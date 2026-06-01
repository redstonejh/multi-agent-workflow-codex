# Multi-Agent Workflow

**A framework for turning a single Claude assistant into a coordinated team of specialized agents — with built-in quality loops, independent verification, and shared memory — for tackling complex tasks like ML experiments, debugging, and research.**

Instead of one model doing one pass, a *conductor* reads your task, assembles the right team of specialist agents (planner, workers, critics, validators), and runs them through a pipeline where they hand work off to each other, check each other, and iterate until the result actually holds up. It's designed to run on Claude Code with no per-token API cost.

> **Status:** Architecture & design complete (see [`docs/`](docs/)), and a **working
> minimal version now runs** — Phases 1–3 of [`docs/08-build-strategy.md`](docs/08-build-strategy.md).
> A small roster of subagents, the `/maw` conductor skill, and deterministic helper
> tools are implemented and tested end to end (see the [worked example](examples/README.md)).
> The full domain rosters (ML and code packs, Phase 4) are still design-only. See
> [What works today](#what-works-today-vs-whats-still-design) below for the honest line.

---

## The problem it solves

A single LLM pass is fast but fragile: no second opinion, no check on whether the output is actually correct, and for technical work (ML especially) the most impressive-looking results are often the most misleading. This framework makes **multi-agent coordination and self-verification the default**, so that:

- work is **decomposed** across specialists instead of crammed into one prompt,
- output is **critiqued and revised in a loop** until it meets an explicit quality bar,
- results are **independently verified** before they're accepted,
- and the whole run is **self-documenting** — every agent's reasoning and hand-off is written to disk as readable markdown.

## How it works

```
your task
   │
   ▼
┌─────────────┐   reads a roster of available specialist roles, then
│  CONDUCTOR  │   plans the team: which roles, how many, which pattern,
└─────────────┘   with what quality bar — staying within safety caps
   │
   ▼
┌──────────────────────────────────────────────┐
│  the team executes (orchestrate / pipeline /   │
│  parallel / route), passing markdown hand-off  │
│  notes between agents and sharing a journal     │
└──────────────────────────────────────────────┘
   │
   ▼
┌─────────────┐   generate → evaluate → revise, looping until the
│ QUALITY LOOP│   output clears the bar (the "refine" pattern)
└─────────────┘
   │
   ▼
┌─────────────┐   an INDEPENDENT agent (not the one that did the work)
│ ACCEPTANCE  │   checks: did we answer the real ask? does every claim
│    GATE     │   trace to evidence? does it run end-to-end?  SHIP / NO-SHIP
└─────────────┘
   │
   ▼
result + a readable run folder documenting how it got there
```

## Key features

- **Conductor (dynamic team assembly).** Given a task, it intelligently selects which specialist agents are actually needed and how many — conservative by default, escalating only when quality checks fail, all within hard caps on agent count and cost.
- **Composable orchestration patterns.** `pipeline`, `orchestrate` (lead + workers), `parallel` (fan-out + reduce), `route` (classify + specialist), and `debate` — mixed and nested as a task requires.
- **Recursive quality loop (`refine`).** A generate → evaluate → revise loop that wraps *any* pattern and repeats until output meets an explicit, rubric-based bar. This is the core mechanism for compounding quality rather than relying on a single lucky pass.
- **Markdown memory & automatic hand-offs.** Each agent keeps local notes; the team shares a journal; and at every step the framework auto-writes a structured hand-off note and passes it to the next agent — so a multi-agent chain runs from one instruction with no manual prompt-threading. Every run produces a human-readable folder you can open and audit.
- **Independent acceptance gate.** A terminal verification step run by a *different* agent than produced the work, checking task conformance, claim-to-evidence consistency (anti-overclaiming), and end-to-end soundness — with an optional human sign-off for high-stakes runs.
- **Dependency-aware parallelism.** Work runs concurrently only when it's truly independent (scheduled against a dependency graph); discovered hidden couplings feed back so the system stops parallelizing things that secretly conflict.
- **Domain validation packs.** Specialized agents + checks for domains where naive results mislead (below).

## Domain packs

### ML validation
A generic "looks good" critic isn't enough for machine learning — the best-looking metric is often an artifact. This pack ships specialized validators with deterministic, tool-computed checks (not LLM guesswork) for the ways ML results mislead: **overfitting** (train/test gap, learning curves, CV stability), **data leakage** (target/temporal/group leakage, the shuffled-label control), **misleading metrics** (imbalance, wrong metric for the goal), **weak baselines & non-significant gains**, **distribution shift & shortcut learning**, **calibration**, **label quality**, and **reproducibility**. A model only counts as "good" once it survives the audits *and* an independent acceptance gate. See [`docs/06-ml-validation.md`](docs/06-ml-validation.md).

### Code & debugging
A methodology pack for working on real codebases: reproduce-first bug finding, structured bug reports, a hypothesis-driven debugging loop (bisection, delta-debugging), written **root-cause analyses** (not just patches), fix + permanent regression test, a disciplined comment policy (explain *why*, never restate *what*), and — notably — a convention for capturing **hidden dependencies / spaghetti coupling** both inline (a greppable marker right above the line) and in a central, queryable dependency map that also makes parallelization safe. See [`docs/07-code-and-debugging.md`](docs/07-code-and-debugging.md).

## How you'd use it

The framework installs as a set of agent and workflow definitions in your Claude Code config directory (`~/.claude/`), so it's available in **every** terminal automatically — no per-project setup. Day to day:

```bash
cd your-project          # any folder you want to work in
claude                   # start Claude Code (runs on your subscription)
/maw fix the failing test in payments.py      # the team assembles and goes
```

The agents operate on the files in your current folder, while their definitions live once in `~/.claude/`. Runs on a Claude Pro/Max subscription with no separate API billing. See [`docs/08-build-strategy.md`](docs/08-build-strategy.md) for the full build and install plan.

## Quick start

The working minimal version lives in this repo under [`.claude/`](.claude/) and
[`maw-tools/`](maw-tools/). From inside the repo:

```bash
claude                                  # start Claude Code (on your subscription)
/maw <your task>                        # the conductor assembles the team and runs it
```

For example: `/maw implement normalize_whitespace in examples/sample_app/textutil.py so the tests pass`.
The conductor scaffolds a `runs/<timestamp>_<slug>/` folder, delegates to the
`planner → worker → critic` team through markdown hand-off notes, loops the critic
until the bar is met, and finishes with an **independent `acceptance_gate`**
(SHIP / NO-SHIP). See the [worked example](examples/README.md) for an actual run.

To make `/maw` available from any folder, install the agents and skill under
`~/.claude/` — see [`INSTALL.md`](INSTALL.md).

The deterministic tools run standalone, no model needed:

```bash
python maw-tools/scaffold_run.py init "demo task" --agents planner,worker,critic
python maw-tools/checks.py test --cmd "python test_textutil.py" --cwd examples/sample_app
python maw-tools/checks.py gap --train 0.98 --test 0.81 --tol 0.05
# (use `uv run maw-tools/...` or `py maw-tools/...` if `python` isn't on PATH)
```

## What works today vs. what's still design

Honest scope — this repo backs a résumé claim, so only the lines below actually run:

**Works now (Phases 1–3 of [doc 08](docs/08-build-strategy.md)):**
- A 5-role roster of subagents in [`.claude/agents/`](.claude/agents/): `conductor`,
  `planner`, `worker`, `critic`, `acceptance_gate` (cheap models for routine roles,
  stronger models for the conductor and the independent gate).
- The [`/maw` conductor skill](.claude/skills/maw/SKILL.md): assess → select a
  conservative team → scaffold → delegate → refine loop → acceptance gate, within
  governor caps.
- Markdown memory + automatic hand-offs ([`docs/05`](docs/05-memory-and-handoffs.md)
  template enforced by a deterministic helper).
- Deterministic, model-free tools in [`maw-tools/`](maw-tools/): `scaffold_run.py`
  (run folders + hand-off files) and `checks.py` (test runner + stats + a
  train-test-gap demo).
- A verified [end-to-end example](examples/README.md): four subagents, hand-off
  files, a passing refine loop, and a SHIP verdict.

**Still design-only (Phase 4+):**
- The full **ML validation roster** ([`docs/06`](docs/06-ml-validation.md)):
  `leakage_auditor`, `overfitting_checker`, `baseline_enforcer`, etc., and their
  deterministic check scripts (only a single `gap` demo exists so far). `# MAW-TODO`
- The full **code & debugging roster** ([`docs/07`](docs/07-code-and-debugging.md)):
  `repro_engineer`, `bug_hunter`, `debugger`, `dep_mapper`, etc., plus `deps.md`
  tooling. `# MAW-TODO`
- Dependency-aware **parallel scheduling** and the `route` / `debate` patterns —
  the current conductor runs the team sequentially. `# MAW-TODO`
- Workflow skills (`ml-experiment`, `debug`) and Phase-5 polish (path-resolution
  for `maw-tools/`, retention/compaction). `# MAW-TODO`

## Design documentation

The complete architecture is specified in [`docs/`](docs/):

| Doc | Contents |
|---|---|
| [`00-overview.md`](docs/00-overview.md) | Vision, design goals, the recursive-quality principle |
| [`01-architecture.md`](docs/01-architecture.md) | System layers, components, conductor, acceptance gate, concurrency |
| [`02-patterns.md`](docs/02-patterns.md) | The orchestration pattern library |
| [`03-api-design.md`](docs/03-api-design.md) | Developer-facing API and usage examples |
| [`04-roadmap.md`](docs/04-roadmap.md) | Phased build plan and open questions |
| [`05-memory-and-handoffs.md`](docs/05-memory-and-handoffs.md) | Markdown memory + automatic hand-off subsystem |
| [`06-ml-validation.md`](docs/06-ml-validation.md) | ML validators, checks, and evaluation rubric |
| [`07-code-and-debugging.md`](docs/07-code-and-debugging.md) | Bug methodology, RCA, hidden-dependency annotation |
| [`08-build-strategy.md`](docs/08-build-strategy.md) | The zero-extra-cost build path (runs on Claude Code) |

## Tech

Built on [Claude Code](https://code.claude.com), running on a Pro/Max subscription (no API key, no per-token cost). Agents are defined as configuration (subagents, skills, conventions); deterministic checks are plain stdlib Python scripts; the multi-agent runtime is provided by Claude Code. (The same configuration could later be driven by the Claude Agent SDK / API for unattended use — see [`docs/08`](docs/08-build-strategy.md).)
