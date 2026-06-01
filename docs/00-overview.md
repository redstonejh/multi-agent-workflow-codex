# Multi-Agent Workflow — Overview

> A framework that coordinates many specialized Claude agents (like a conductor leading an orchestra) to tackle complex tasks.
> Status: **architecture / design only.** No code written yet. These docs are the reference we build from.
> Runtime decision: built to run on **Claude Code on your existing Pro/Max subscription — no API key, no per-token charges**. See `08-build-strategy.md` for the chosen zero-extra-cost build path. (Earlier docs describe layers in API terms; those layers are realized by Claude Code rather than built from scratch.)

## The one-sentence pitch

A reusable library of **agents** and **workflows** that runs on Claude Code (your subscription) — so any future task needing multi-agent coordination becomes "open the terminal, run `/maw <problem>`, and let it assemble the team" instead of rebuilding orchestration from scratch every time. The agents, patterns, memory, and quality gates are defined once as configuration; Claude Code executes them at no extra cost.

## What problem this solves

Today, every multi-agent task (research, ML experimentation, code generation, document review, etc.) means re-wiring the same plumbing: calling the API, passing context between calls, retrying, parsing, looping for quality. Multi-Agent Workflow factors that plumbing out **once** so the only thing that changes per task is:

1. **Which agents** exist (their roles / system prompts / tools).
2. **How they're wired together** (which orchestration pattern).

Everything else — the LLM client, shared memory, tool execution, MCP connections, the quality-improvement loop — is provided by the framework.

## Design goals (in priority order)

1. **Reusable by reference.** I should be able to come back months later, read one example, and stand up a new workflow in minutes. The library is the canonical place orchestration lives.
2. **Recursive quality by default.** Per your requirement: workflows should be able to *critique and improve their own output in a loop* until a quality bar is met, not just produce a single pass. This is a first-class, composable wrapper (see `02-patterns.md`), not an afterthought.
3. **Pattern-agnostic.** Different jobs want different shapes (an ML workflow ≠ a research workflow ≠ a code-review workflow). Multi-Agent Workflow ships several orchestration patterns as building blocks and lets a workflow mix them.
4. **Defined in code, with decorators.** Agents, tools, and workflows are declared with `@agent`, `@tool`, `@workflow`. Type-safe, discoverable in an IDE, no separate config language to learn.
5. **Capability-rich agents.** An agent can be plain-LLM, or have shared memory, real tools, and MCP servers — opt in per agent.
6. **Importable as a library.** Primary interface is `import maw`. A thin CLI can wrap it later, but the core is a normal Python package.

## Non-goals (for v1)

- Not a hosted service, web UI, or job scheduler. It's a library you call.
- Not tied to one task domain. No "research-only" assumptions baked into the core.
- Not a general agent marketplace. You write the agents; Multi-Agent Workflow coordinates them.

## The core mental model

Four nouns and one verb:

- **Agent** — a configured Claude caller with a role (system prompt), a model, and optional capabilities (memory, tools, MCP).
- **Memory** — per-agent local notes + a shared journal, **auto-saved as markdown** on disk, plus auto-generated hand-off notes so agents pass work to each other without you prompting each one (see `05-memory-and-handoffs.md`).
- **Workflow** — a Python function that composes agents using patterns, producing a result.
- **Conductor** — an optional top layer that, given a task and a roster of roles, **decides the team itself** (which roles, how many, which pattern) within safety caps (see `01-architecture.md`).
- **Acceptance gate** — a terminal, *independent* check (different agent/model than produced the work) that every run ends with: does the deliverable answer the real ask, does every claim trace to recorded evidence, and does it run end-to-end. SHIP / NO-SHIP, with optional human sign-off (see `01-architecture.md`).
- **Run** (the verb) — execute a workflow (or the conductor) on an input; everything is observable, logged to a readable markdown run folder, and reconstructable.

## The recursive-quality principle (the heart of it)

Most "multi-agent" code is a single forward pass. Multi-Agent Workflow treats **feedback loops as the default route to quality**. The canonical loop is *generate → evaluate → revise → repeat until good enough*:

```
        ┌─────────────────────────────────────┐
        │                                       │
   input ──▶ Generator ──▶ output ──▶ Evaluator ──▶ score + critique
        │                                       │        │
        └──────────── revise with critique ◀────────────┘
                     (loop until score ≥ threshold or max iters)
```

This `refine()` loop is composable: the "Generator" can itself be a single agent, an orchestrator-workers team, or another whole workflow. That's how quality compounds — you can wrap a quality loop around any pattern, and even nest loops.

See `01-architecture.md` for components, `02-patterns.md` for the pattern library, `03-api-design.md` for the developer-facing API, `04-roadmap.md` for build phases and open questions, `05-memory-and-handoffs.md` for the markdown memory + auto hand-off subsystem, `06-ml-validation.md` for the specialized ML validators and rubric (overfitting, leakage, baselines, robustness, etc.), `07-code-and-debugging.md` for the code-work pack (bug methodology, root-cause analysis, comment policy, and hidden-dependency annotation), and **`08-build-strategy.md` for the chosen zero-extra-cost build path (run it all on your Claude Code subscription)**.
