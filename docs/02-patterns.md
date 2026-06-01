# Orchestration Patterns

The reusable shapes a workflow composes. Each is a framework-provided function; you supply the agents. They all share the Context, emit traces, and **nest inside one another** — that composability is what lets quality compound.

Quick map of which pattern fits which job:

| Pattern | Shape | Best for | Cost profile |
|---|---|---|---|
| `pipeline` | A → B → C | Staged transformation with clear hand-offs | Low, predictable |
| `orchestrate` | lead → workers → synthesize | Open-ended tasks needing decomposition | Medium–high |
| `parallel` | fan-out → reduce | Independent slices, breadth (research, scanning) | High but fast (concurrent) |
| `route` | classify → specialist | Heterogeneous request types | Low (one specialist runs) |
| `refine` ★ | generate ⇄ evaluate loop | **Anything where quality must improve** | Scales with iterations |
| `debate` | propose ⇄ critique ⇄ judge | High-stakes correctness, reducing blind spots | High |
| `conductor` ★ | plan team → execute | **When you want it to decide the team** | Variable (governed) |

★ = the recursive feedback mechanism you specifically asked for. It's designed to wrap the others.

---

## 1. `pipeline` — sequential

Agents run in a fixed order, each consuming the previous output.

```
input ─▶ [extract] ─▶ [analyze] ─▶ [summarize] ─▶ output
```

Use when the task has natural stages and you want predictability and low cost. Weakness: a bad early step propagates — which is why you'd often wrap a stage (or the whole pipeline) in `refine`.

## 2. `orchestrate` — orchestrator-workers

A **lead** agent decomposes the task into subtasks, **worker** agents execute them (often in parallel), and the lead **synthesizes** the results. This is the best general-purpose default for open-ended work where you don't know the sub-structure ahead of time.

```
            ┌──▶ worker(subtask 1) ──┐
input ─▶ lead ──▶ worker(subtask 2) ──▶ lead(synthesize) ─▶ output
            └──▶ worker(subtask 3) ──┘
```

Workers can be the *same* agent run on different subtasks, or *different* specialist agents. The lead decides the decomposition at runtime, so it adapts to each input.

## 3. `parallel` — fan-out + reducer

Run many agents (or one agent over many inputs) concurrently, then a **reducer** agent merges. Differs from `orchestrate` in that the split is fixed/known rather than decided by a lead. Great for breadth and speed: scan 20 documents, research 8 sub-questions, generate N candidate solutions.

```
input ─▶ split ─▶ [agent]×N (concurrent) ─▶ reducer ─▶ output
```

Pairs naturally with `refine`: generate N candidates in parallel, then let an evaluator pick/merge the best — a single-shot quality boost.

**Only truly independent work runs concurrently.** Each slice declares what it reads/writes; `parallel` schedules against a dependency DAG and runs only the independent frontier at once (full design in `01-architecture.md`, "Concurrency & dependency-aware scheduling"). Slices write to their own per-instance memory files, so there's no contention; shared external resources are lock-guarded; `max_parallel` is governed. If two slices assumed independent turn out to conflict (a hidden dependency), the conflict is detected, logged, and fed back into the DAG so they're serialized next time rather than silently corrupting the merge.

## 4. `route` — classifier / handoff

A lightweight (cheap-model) **router** classifies the input and hands off to the right specialist agent/workflow. Keeps cost down because only the relevant specialist runs, and keeps each specialist's prompt focused.

```
input ─▶ router ─┬─▶ specialist_A
                 ├─▶ specialist_B
                 └─▶ specialist_C ─▶ output
```

Good top-level entry point for a "do anything" workflow: route ML tasks to an ML workflow, research tasks to a research workflow, etc.

## 5. `refine` — evaluator-optimizer (the recursive quality loop) ★

The core quality mechanism. A **generator** produces output; an **evaluator** scores it against explicit criteria and returns actionable critique; the generator revises using that critique; repeat until the score clears a threshold or a max-iteration cap is hit.

```
                 ┌─────────── critique ───────────┐
                 ▼                                 │
input ─▶ generator ─▶ candidate ─▶ evaluator ─▶ {score, critique}
                 ▲                                 │
                 └─ revise (candidate + critique) ◀┘
        loop while score < threshold and iters < max
```

Design details that make it good rather than a gimmick:

- **Explicit rubric.** The evaluator is given concrete, task-specific criteria (correctness, completeness, style, constraints) and must return a structured score per criterion + an overall — not a vague "looks good." Structured output (Layer 1) enforces this.
- **Actionable critique, not just a number.** The evaluator must say *what to change*. The generator's revise step receives the previous candidate + the critique, so each loop is targeted.
- **Stopping conditions.** Threshold met, max iterations, *or* "no improvement over last iteration" (to avoid burning tokens once it plateaus). All configurable.
- **Generator can be anything.** It can be a single agent, an `orchestrate` team, or another whole workflow. That's the key: `refine(generator=orchestrate(...), evaluator=critic)` gives you a self-improving multi-agent team.
- **Separate models allowed.** Cheap fast model for generation, stronger model for evaluation (or vice-versa) — your call per workflow.

**Why this is the backbone of "quality keeps increasing":** because `refine` is just a function over a generator, you can wrap it around any pattern and even nest it (an inner loop perfects each section, an outer loop perfects the assembled whole). Quality compounds instead of relying on a single lucky pass.

## 6. `conductor` — runtime team assembly (the meta-pattern) ★

Where the other patterns are shapes *you* pick, the conductor *picks the shape for you*. Hand it a task and a **roster** of available roles; it plans which roles to use, how many of each, in which pattern, with what quality bar — then executes. This is the "a bunch of options + a conductor that intelligently applies X agents if the roles are reasonably required" idea.

```
task ─▶ conductor ─▶ PLAN (structured, justified):
                       roles:   [planner, ml_engineer×3, critic]
                       pattern: orchestrate wrapped in refine
                       bar:     score ≥ 0.9, max_iters 4
                       reason:  one line per role
                     │
   governor checks caps ◀┘   (trim / reject if over budget)
                     │
   (optional) plan itself run through refine: "is this team right-sized?"
                     │
                     ├─▶ execute plan ─▶ synthesize
                     │
                     └─▶ ACCEPTANCE GATE (independent agent, runs once at the end):
                           • task conformance — did we answer the real ask?
                           • claim-to-evidence — does the output match the run folder?
                           • end-to-end smoke test — does it run on fresh input?
                         SHIP ─▶ return output   |   NO-SHIP ─▶ loop back with reasons
```

The acceptance gate (detailed in `01-architecture.md`) is a **terminal, independent** check — a different agent/model than produced the work — distinct from the per-component evaluation inside `refine`. The `refine` loop verifies *each piece*; the acceptance gate verifies the *whole deliverable is fit to ship*, and is the last automated step before a result is returned (high-stakes runs can route NO-SHIP/uncertain to human sign-off instead of looping).

How it decides "reasonably required":
- The roster gives each role a **capability description + cost tier**; the conductor matches task needs to roles and must **justify each addition** in the plan.
- It starts **conservative** (smallest reasonable team) and **escalates only on failure** — if the `refine` loop can't clear the bar, the next plan may add roles or instances. So simple tasks stay cheap (maybe one agent), hard tasks grow a team.
- The **governor** is the backstop: hard caps on total agents, concurrency, iterations, and spend mean a mis-judgment gets trimmed, not executed.

Relationship to the other patterns: the conductor doesn't replace them — it **chooses and composes** them. Its output is literally "run `orchestrate` with these agents, wrapped in `refine`." So it's the optional top layer; drop down to calling patterns directly whenever you already know the shape.

## 7. `debate` — propose / critique / judge (optional, advanced)

Two or more agents argue opposing or independent positions; a judge agent reconciles. Reduces single-model blind spots on high-stakes correctness questions. More expensive; reserve for when being wrong is costly. Can be seen as a multi-generator variant of `refine`.

---

## Composition is the point

These are deliberately small so they combine. Realistic workflows look like:

```python
# Pseudocode — real API in 03-api-design.md
def solve(input):
    kind = route(router, input)              # pick the sub-workflow
    draft = orchestrate(lead, workers, input)# decompose + execute
    final = refine(                          # ← recursive quality loop
        generator=lambda c: orchestrate(lead, workers, c),
        evaluator=critic,
        seed=draft,
        threshold=0.9, max_iters=4,
    )
    return final
```

Read that as: route to the right approach, decompose and solve, then *keep improving the whole solution against a rubric until it's good enough.* Any future task plugs new agents into the same skeleton.
