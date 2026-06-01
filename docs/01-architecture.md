# Architecture

How the pieces fit together. This is the structural reference; the API surface lives in `03-api-design.md`.

## Layered view

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 6 — Conductor        runtime team assembly: reads task + │
│             roster, plans which roles × how many, then executes │
├──────────────────────────────────────────────────────────────┤
│  Layer 5 — Workflows        (@workflow functions you write)     │
│             compose agents + patterns into a task solution      │
├──────────────────────────────────────────────────────────────┤
│  Layer 4 — Patterns         orchestrate / pipeline / parallel / │
│             routing / refine(feedback loop) — reusable shapes   │
├──────────────────────────────────────────────────────────────┤
│  Layer 3 — Agents           (@agent) role + model + capabilities│
├──────────────────────────────────────────────────────────────┤
│  Layer 2 — Capabilities     Memory(md) · Tools · MCP · Hand-offs│
├──────────────────────────────────────────────────────────────┤
│  Layer 1 — Core runtime     LLM client · run loop · tracing ·   │
│             retries · cost/token accounting · structured output │
└──────────────────────────────────────────────────────────────┘
              Roster (agent registry) ·  Governor (caps)
                         Anthropic Claude API
```

A workflow touches Layers 3–5. The **conductor (Layer 6)** is optional and sits on top: when you don't want to hand-wire a workflow, you hand the conductor a task and it assembles the team itself. The **roster** and **governor** are cross-cutting services (right edge) the conductor relies on. Lower layers are framework-provided and rarely change.

## Layer 1 — Core runtime

> **Implementation note:** in the chosen zero-cost build (`08-build-strategy.md`), this entire layer is **provided by Claude Code running on your subscription** — you do not build it, and there is no per-token cost. The descriptions below explain what the runtime does; Claude Code already does it. (If you ever opt into the API/Agent-SDK path, this becomes a thin wrapper over the `anthropic` SDK that you build and pay per token for.)

The foundation everything else sits on.

**LLM client.** A thin wrapper over the `anthropic` SDK that centralizes: model selection, streaming, system/user/assistant message assembly, tool-call round-tripping, structured output (JSON schema → validated Python object), retries with backoff, and timeout handling. Nothing above this layer talks to the SDK directly.

**Run loop.** Drives a single agent turn to completion, including the **tool-use cycle**: send messages → if Claude requests tools, execute them → feed results back → repeat until Claude returns a final answer. This loop is the unit every pattern is built from.

**Tracing & accounting.** Every agent call, tool call, and loop iteration emits a structured event (who, prompt, response, tokens, cost, latency, iteration #). This is what makes runs debuggable and makes the feedback loops observable ("why did iteration 3 score higher?").

**Config.** Model defaults, API key handling (env var), per-agent overrides, global limits (max tokens, max loop iterations, max spend) as a safety governor.

## Layer 2 — Capabilities (opt-in per agent)

**Context (shared memory / blackboard) — markdown-backed by default.** A structured store passed through a run, but unlike a throwaway in-memory dict it is **automatically mirrored to human-readable markdown files on disk** as the run proceeds (full design in `05-memory-and-handoffs.md`). Agents read prior outputs and write their own; the framework handles loading the right files into each agent's context and saving updates — so you do not manually thread state or re-prompt each agent. Supports:
- *local memory* — each agent has its own `agents/<name>.md` it reads at start and appends to at end (persists across turns, optionally across runs)
- *shared journal* — `memory.md`, an append-only log of what every agent did, the common blackboard
- *artifacts* — named outputs written as md (e.g. `plan.md`, `draft.md`, `eval_report.md`)
- *hand-offs* — auto-generated `handoffs/NN_from__to__to.md` notes passed between agents (see below + `05`)

This is how agents coordinate without every workflow hand-threading variables — and because it's all markdown, you can open any run folder and read exactly what happened.

**Hand-offs (automatic).** At every boundary where one agent's output feeds another, the framework auto-writes a structured hand-off markdown note (context · what I did · output · open questions · recommended next step) and injects it as the next agent's input. You don't write "here's what the planner produced, now do X" — the pattern does it for you. Details in `05-memory-and-handoffs.md`.

**Tools.** A `@tool`-decorated Python function becomes a callable the agent can invoke. The framework auto-generates the JSON schema from type hints + docstring, exposes it to Claude, executes the call when requested, validates args, and returns the result into the run loop. Tools are plain Python — web search, file I/O, code execution, calling your own ML training script, etc.

**MCP.** An agent can be attached to one or more MCP servers. At run start the framework connects, lists the server's tools, and merges them into that agent's tool set — so MCP tools and native `@tool`s look identical to the agent. Connection lifecycle (start/stop) is managed by the runtime.

## Layer 3 — Agents

An **Agent** binds a role to a configuration:

- `name` — identifier (used in tracing and as a Context key)
- `system` — the system prompt (the role); a docstring or string
- `model` — which Claude model (default from config; override for cheap vs. capable agents)
- `tools` — list of `@tool` functions
- `mcp_servers` — list of MCP server handles
- `memory` — whether/how it reads & writes Context
- `output_schema` — optional structured-output type (returns a validated object instead of raw text)

Agents are **stateless definitions**; all per-run state lives in Context. The same agent definition can be reused across many workflows and many runs. Calling an agent runs the Layer-1 loop with that agent's config.

## Layer 4 — Patterns

Reusable orchestration shapes, each a function taking agents + input and returning output. They are the verbs that combine agents. Full catalog in `02-patterns.md`, but structurally they all:

- accept one or more agents,
- read/write the shared Context,
- emit trace events,
- and are themselves composable (a pattern's "worker" can be another pattern).

The key one for your quality requirement is `refine()` — the generate/evaluate/revise loop — which can wrap any other pattern.

## Layer 5 — Workflows

A `@workflow` is just a Python function that wires patterns and agents together and returns a result. It's the only thing you write per task. Because it's plain Python, you get conditionals, loops, error handling, and composition for free. A workflow is registered by name so it's discoverable and runnable by reference (`maw.run("ml_experiment", input=...)`).

## Layer 6 — Conductor (runtime team assembly)

The conductor is the "intelligently apply X agents if the roles are reasonably required" layer. It's an agent itself (structured output) that, given a task and the **roster**, decides *who* works on it and *how many*, then executes that plan through the existing patterns.

```
task ─▶ conductor ─reads─▶ Roster (available roles + descriptions + cost)
            │
            ├─ emits a PLAN (structured):
            │     roles:   [planner, ml_engineer×3, critic]
            │     pattern: orchestrate, wrapped in refine
            │     bar:     score ≥ 0.9, max_iters 4
            │     reason:  one line justifying each role
            │
            ├─ Governor validates the plan against caps (max agents,
            │   max parallel, max spend) — trims or rejects if over
            ├─ optional: plan run through refine (cheap evaluator asks
            │   "is this team over/under-built?") before expensive agents run
            ├─ executes the plan, synthesizes
            └─ ACCEPTANCE GATE (independent) → SHIP / NO-SHIP
                 NO-SHIP → loop back with the gate's reasons; SHIP → return Result
```

Key properties:
- **Justification required.** The plan carries a one-line reason per role, so under/over-staffing is visible and auditable — and it makes the conductor's decisions better.
- **Conservative by default.** Bias toward the smallest reasonable team; escalate (add agents / iterations) only if the quality loop fails to clear the bar. A trivial task can resolve with a single agent.
- **Reuses everything below.** The conductor doesn't introduce new execution machinery — it just *chooses* a pattern + agents and runs them. So it's an additive layer, not a rewrite.
- **Opt-in.** When you already know the shape, call patterns/workflows directly. When you'd rather it decide, call the conductor.

## Cross-cutting: Acceptance gate (terminal independent verification)

The patterns and `refine` loop verify the *process* — that each step is sound. They do not, on their own, verify the *deliverable as a whole*. So every run ends with one **acceptance gate**: a final, independent check that the assembled output is actually fit to ship. This is a distinct tier of checking, not another component validator.

Two-tier verification:

```
component checks  (inside refine / patterns)   →   does each piece hold up?
        │
        ▼
acceptance gate   (terminal, once, independent) →   is the WHOLE deliverable
                                                     fit to ship?
```

The acceptance gate asks three things no per-component check covers:

1. **Task conformance** — does the deliverable answer the *original request and its real-world objective*, not just score well on a proxy metric? (You can pass every component and still have solved the wrong problem.)
2. **Claim-to-evidence fidelity** — does every claim in the final output trace back to evidence recorded in the run folder (`memory.md`, validator findings, artifacts)? The synthesis step is itself an LLM and can drift or overclaim; this catches a report that says "generalizes well" when a validator flagged instability, or that quietly drops a failed gate. It is, in effect, a hallucination/consistency audit of the output against the recorded results.
3. **End-to-end soundness** — does the whole thing actually run on genuinely fresh input and produce sane output (a smoke test), catching integration breakage and deployment skew that split-based checks miss.

Two properties make it trustworthy rather than ceremonial:

- **Independence.** The acceptance gate is run by a *different agent than produced the work, ideally a different model/seed.* A producer reviewing itself reproduces its own blind spots; independence is the point. This is also the answer to "who checks the checkers" — the component validators can be wrong, and the independent gate is the backstop.
- **Terminal & bounded.** It is the *last* automated check — you don't validate infinitely (regress). It returns SHIP / NO-SHIP + reasons. For high-stakes runs it can route to optional **human sign-off** instead of spawning yet another verifier.

The gate is a framework default for any workflow (its claim-to-evidence and conformance checks are domain-agnostic); domain specializations — e.g. the ML smoke test and rubric tie-in — are layered on top (see `06-ml-validation.md`). In the conductor's flow it runs after the `refine` loop has cleared the component gates, immediately before the result is returned.

## Cross-cutting: Concurrency & dependency-aware scheduling

"Run things in parallel" is only safe for work that is *truly* independent. So the framework doesn't just fan out N agents — it schedules against a **dependency DAG**.

How it works:
- Each unit of work declares (or the planner infers) what it **reads** and **writes** — artifacts, files, external resources.
- Two units may run **concurrently only if** they share no write target and neither consumes the other's output. Everything else is ordered by the edges. The scheduler runs the independent *frontier* concurrently, then the next frontier, and so on.
- **Resource safety:** per-instance memory files mean no contention on agent state; the shared journal is written through a single serialized sink; genuinely shared external resources (a file, a DB, an API rate limit) are guarded by named locks. The governor caps `max_parallel`.
- **Hidden dependencies (the spaghetti case):** when two units assumed independent turn out to conflict — both mutate the same artifact, or one silently relies on the other's side effect — the scheduler **detects the conflict, logs it to the run journal, and feeds the edge back into the DAG** so it stops parallelizing them. For code work, the discovery is also annotated *in place* and recorded in a central dependency map (see `07-code-and-debugging.md`). This is the same hidden-coupling problem the code pack addresses, just at runtime.
- **Determinism:** concurrent outputs are combined by a reducer; journal entries are ordered by timestamp so a run is still reconstructable.

The payoff: parallelism is correct-by-construction (only the independent frontier runs at once), and discovered couplings make the next run's scheduling smarter rather than silently corrupting results.

## Cross-cutting: Roster (agent registry)

A catalog of available agent roles the conductor can draw from. Each entry: the `@agent` definition plus metadata — a short capability description ("plans ML experiments with success criteria"), rough cost tier, and which tools/MCP it needs. Populated automatically when agents are registered; you can also scope a roster per run ("only these roles are allowed for this task"). This is what lets the conductor reason about *which* roles fit without you enumerating them each time.

## Cross-cutting: Governor (safety & cost caps)

A guard that every run passes through, and that the conductor's plans are validated against. Enforces hard limits: max total agents, max concurrent agents, max refine iterations, and max token/$ spend per run. Prevents a mis-judging conductor (or a runaway loop) from spawning a 40-agent monster for a small task. Limits are configurable globally and per-run; exceeding a cap trims the plan or aborts with a clear error rather than silently overspending.

## End-to-end data flow (one run)

```
maw.run("my_workflow", input)
  │
  ├─ create Context (fresh memory + trace sink)
  ├─ connect any MCP servers needed by the workflow's agents
  ├─ execute the @workflow function:
  │     pattern A (agents…) ──reads/writes──▶ Context
  │     pattern B wraps pattern A in refine() loop:
  │         generate → evaluate → (revise)* until threshold
  │     …
  ├─ acceptance gate (independent agent): task conformance +
  │     claim-to-evidence + end-to-end smoke test → SHIP / NO-SHIP
  │     (NO-SHIP loops back with reasons; high-stakes → human sign-off)
  ├─ collect final result + full trace + cost summary
  └─ persist Context if configured; return Result object
```

The `Result` object carries: the final output, the score (if a quality loop ran), the number of iterations, the full trace, and token/cost totals.

## Directory layout (proposed)

```
maw/
├── core/
│   ├── client.py        # anthropic wrapper, structured output, retries
│   ├── runloop.py       # single-agent tool-use loop
│   ├── trace.py         # event model + sinks (console, jsonl)
│   └── config.py
├── capabilities/
│   ├── context.py       # blackboard / memory (md-backed)
│   ├── memory.py        # md read/write, local + shared journal, run folders
│   ├── handoff.py       # auto hand-off note generation + injection
│   ├── tools.py         # @tool, schema generation, executor
│   └── mcp.py           # MCP connection + tool merging
├── agents.py            # @agent, Agent definition
├── patterns/
│   ├── orchestrate.py   # orchestrator-workers
│   ├── pipeline.py      # sequential
│   ├── parallel.py      # fan-out + reducer
│   ├── route.py         # classifier / handoff
│   └── refine.py        # evaluator-optimizer feedback loop ★
├── conductor.py         # Layer 6: runtime team assembly
├── acceptance.py        # terminal independent acceptance gate
├── roster.py            # agent registry + capability metadata
├── governor.py          # cost / role caps
├── workflow.py          # @workflow, registry, run()
└── examples/
    ├── research.py
    ├── ml_experiment.py
    └── code_review.py
```
