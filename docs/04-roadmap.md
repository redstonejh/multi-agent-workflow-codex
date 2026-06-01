# Roadmap, Dependencies & Open Questions

> **Two build tracks.** The **default, chosen track is zero-extra-cost**: implement Multi-Agent Workflow as Claude Code configuration that runs on your Pro/Max subscription — see `08-build-strategy.md` for its phased plan (this is the one to follow). The **API/Agent-SDK track below** is the original, more powerful but **pay-per-token** alternative, kept for reference in case you later want unattended/embedded use. Don't build the API track unless you specifically want to pay for that elasticity.

## Build phases (API/Agent-SDK track — optional, pay-per-token)

Each phase is independently useful — you can stop and have something that works.

**Phase 0 — Skeleton & core runtime**
- Package scaffold, config, env-based API key.
- `core/client.py`: anthropic wrapper with retries + structured output.
- `core/runloop.py`: single-agent tool-use loop.
- `core/trace.py`: event model + console/jsonl sinks.
- Deliverable: call one agent, get a traced response. No patterns yet.

**Phase 1 — Agents + tools + the first pattern**
- `@agent`, `@tool` (schema generation from type hints/docstring).
- `pipeline` pattern (simplest).
- Deliverable: a 2-stage pipeline workflow runs end to end.

**Phase 2 — Markdown memory + the quality loop (the headline features)**
- `capabilities/memory.py` (md-backed local + shared journal, run folders) and `capabilities/handoff.py` (auto hand-off notes + injection).
- `patterns/refine.py` (evaluator-optimizer) + structured-output evaluator.
- Deliverable: a 2-agent chain that runs from one prompt — agents hand off via md notes, remember their own context — and a workflow that measurably improves output across iterations, with the run folder + trace showing scores rising.

**Phase 3 — The rest of the pattern library**
- `orchestrate`, `parallel` (async fan-out), `route`.
- `@workflow` registry + `maw.run()` / `arun()`.
- Deliverable: compose patterns; nest `refine` around `orchestrate`.

**Phase 3.5 — Conductor (runtime team assembly)**
- `roster.py` (agent registry + capability metadata), `governor.py` (caps), `conductor.py` (plan → validate → execute).
- Deliverable: `conductor.run(task, roster, governor=...)` chooses the team, stays within caps, and self-documents to a run folder.

**Phase 3.6 — Acceptance gate (terminal independent verification)**
- `acceptance.py`: the SHIP/NO-SHIP gate run once at the end by an independent agent (different model/seed).
- Domain-agnostic checks: task conformance + claim-to-evidence audit (output vs. run folder) + end-to-end smoke test; optional human sign-off hook for high-stakes.
- Deliverable: any workflow's result is gated before return; NO-SHIP loops back with reasons. See `01-architecture.md`.

**Phase 3.7 — ML validation pack**
- Validator agents (`leakage_auditor`, `overfitting_checker`, `metric_validator`, `baseline_enforcer`, `variance_auditor`, `robustness_tester`, `calibration_checker`, `data_quality_auditor`, `reproducibility_checker`) and their backing `@tool`s.
- ML evaluation rubric (hard PASS/FAIL gates) wired into `refine`, plus the ML-specialized acceptance gate (`acceptance_gate` agent + claim-evidence/smoke-test tools).
- Deliverable: an ML workflow whose "good" means it survived leakage/overfitting/baseline/robustness audits *and* an independent acceptance gate, with markdown evidence per gate. See `06-ml-validation.md`.

**Phase 3.8 — Code-work pack**
- Dependency-DAG scheduler for concurrency (read/write footprints, resource locks, hidden-edge feedback).
- Code roster (`repro_engineer`, `bug_hunter`, `debugger`, `rca_writer`, `fixer`, `dep_mapper`, `code_reviewer`) + bug-report/RCA templates + `MAW-DEP/BUG/RCA/TODO` annotation convention and `deps.md` map.
- Deliverable: a debugging workflow that reproduces → finds root cause → fixes with a regression test → annotates discovered hidden couplings inline + centrally, gated by independent review. See `07-code-and-debugging.md`.

**Phase 4 — MCP + richer capabilities**
- `capabilities/mcp.py`: connect servers, merge tools into agents.
- Context persistence (jsonl/SQLite), resumable runs.
- Deliverable: an agent uses an MCP server's tools transparently.

**Phase 5 — Polish & reuse ergonomics**
- Three worked `examples/` (research, ml_experiment, code_review) — these double as the "reference back to" library you wanted.
- Optional thin CLI.
- Cost governor (max spend / iterations), better trace pretty-printing.

## Dependencies (intentionally minimal)

- `anthropic` — the Claude API SDK (required).
- `pydantic` — structured output validation (likely).
- `mcp` — official MCP client SDK (Phase 4).
- `anyio`/`asyncio` — concurrency for `parallel` (stdlib-ish).
- Dev: `pytest`, `ruff`. That's it — keep the surface small so it stays easy to revisit.

## Cross-cutting concerns to keep in mind

- **Cost/safety governor.** Loops + parallel fan-out can blow up token spend. Hard caps on max iterations, max concurrent agents, and max total tokens per run, enforced in Layer 1.
- **Determinism & debugging.** Every run produces a full trace; seeds/inputs logged so a run can be replayed and a `refine` loop's score history inspected.
- **Failure handling.** What happens when a worker errors mid-orchestration or an evaluator returns garbage? Need a defined policy (retry, skip, abort) per pattern.
- **Prompt management.** System prompts live in docstrings for v1; if they grow, consider a `prompts/` directory. Decide before it sprawls.

## Open questions I want your call on

1. **Scope of v1.** Ship just `pipeline` + `refine` first (proves the quality-loop thesis fastest), or build the full pattern set before first use? *My lean: Phases 0–2 first, get the feedback loop working, then expand.*
2. **Sync vs async core.** Async unlocks real parallelism but is more complex to write and debug. Worth it from day one, or add later? *My lean: async core from Phase 3, sync-friendly wrappers on top.*
3. **How opinionated should agents be?** Ship a small library of generic reusable agents (a generic `critic`, `planner`, `summarizer`), or keep the core empty and let each project define its own? *My lean: ship a few generic ones as defaults you can override.*
4. **Evaluator trust.** For `refine`, do we trust a single evaluator agent's score, or require agreement between two evaluators for high-stakes runs (tie-in to `debate`)? *My lean: single evaluator default, multi-evaluator opt-in.*
5. **Name.** Keep "Multi-Agent Workflow" or pick something else? Affects package name / imports.
6. **Persistence depth.** Is resumable runs (Phase 4) actually valuable to you, or is in-memory-per-run enough? Cutting it simplifies a lot.

## What I'd want from you before writing code

- Pick the v1 scope (Q1).
- Confirm the decorator API in `03-api-design.md` feels right to type.
- One concrete first workflow to build against — a real task you have (you mentioned ML). A real target keeps the design honest.
