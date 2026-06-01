# Markdown Memory & Automatic Hand-offs

This is the subsystem that makes agents coordinate **without you prompting each one by hand**. Two ideas:

1. **Memory is markdown on disk, automatically.** Every agent has local memory; the team shares a journal; all of it is written and re-loaded for you.
2. **Hand-offs are auto-generated markdown notes.** When one agent's output feeds the next, the framework writes a structured note and injects it as the next agent's input — so the chain runs itself.

Everything is plain `.md`, so any run folder is something you can open and read like a logbook.

## Run folder layout

Each run gets a folder (under a configurable `runs/` root). The framework creates and maintains it:

```
runs/2026-06-01_ml-experiment_a1b2/
├── run.md                       # the conductor's plan + final result summary
├── memory.md                    # shared journal (append-only): who did what, when
├── agents/
│   ├── planner.md               # planner's local memory / scratchpad
│   ├── ml_engineer.md
│   └── critic.md
├── handoffs/
│   ├── 01_planner__to__ml_engineer.md
│   ├── 02_ml_engineer__to__critic.md
│   └── 03_critic__to__ml_engineer.md     # refine loop sends critique back
└── artifacts/
    ├── plan.md
    ├── draft.md
    └── eval_report.md
```

Optionally, **persistent (cross-run) memory** lives outside the run folder so a role accumulates lessons over time:

```
memory/
├── planner.md       # long-term notes the planner keeps across all runs
└── ml_engineer.md
```

Per-run local memory is the default (clean slate each run); cross-run persistence is opt-in per agent (`memory="persistent"`).

## Local memory (per agent)

When an agent with `memory=True` runs:
1. **On start**, the framework loads that agent's `agents/<name>.md` (and persistent file if enabled) and prepends it to the agent's context as "Your notes so far."
2. The agent works.
3. **On finish**, the framework appends a short, structured note to the same file — what it concluded, decisions made, open threads. (The agent writes this itself, since it knows what mattered; a cheap summarizer is the fallback.)

Net effect: an agent invoked again later "remembers" without you re-feeding context.

## Shared journal (`memory.md`)

An append-only, timestamped log every agent writes one entry to per turn. It's the common blackboard:

```markdown
## 14:02 — planner
Decomposed the churn task into 3 experiments. Success bar: AUC ≥ 0.85.
Wrote artifacts/plan.md. Next: ml_engineer runs experiment 1.

## 14:09 — ml_engineer (×3, parallel)
Ran experiments 1–3. Best AUC 0.81 (gradient boosting). Underperforming the bar.
Wrote artifacts/draft.md. Open: feature set may be too thin.
```

Agents with memory read the recent tail of the journal on start, so they have shared situational awareness automatically.

## Automatic hand-off files (the part that removes manual prompting)

A hand-off happens at any boundary where agent A's output becomes agent B's input (a pipeline step, orchestrate lead→worker, a refine critique going back to the generator). At each boundary the framework:

1. Asks the **producing** agent to fill a fixed hand-off template (it just produced the work, so it writes the best note cheaply — or a small model summarizes if the producer used structured output).
2. Writes it to `handoffs/NN_from__to__to.md`.
3. **Injects that file as the consuming agent's input** — the consumer's prompt becomes "Here is your hand-off:" + the note. You never type the glue.

### Hand-off template (standard, so every note is parseable)

```markdown
# Hand-off: planner → ml_engineer  (run a1b2, step 01)

## Task context
What we're ultimately trying to achieve, in 1–2 lines.

## What I did
The concrete work completed in this step.

## Output / artifacts
- artifacts/plan.md  (the experiment plan)
- key result values inline if small

## Open questions / risks
Things the next agent should watch out for.

## Recommended next step
What you (the next agent) should do, specifically.
```

Because the template is fixed, hand-offs are both human-readable and machine-parseable, and the conductor/patterns can route them automatically. This is what lets a 4-agent chain run end-to-end from a single top-level prompt.

## How it plugs into the patterns

- **pipeline / orchestrate / route:** each boundary auto-emits a hand-off; downstream agent auto-receives it.
- **parallel:** each concurrent agent writes to its *own* `agents/<name>__<i>.md` (no write contention); the reducer receives N hand-offs.
- **refine:** the evaluator's critique *is* a hand-off back to the generator (`critic → generator`), so "revise with this feedback" needs no manual wiring — the loop feeds itself.
- **conductor:** writes the plan to `run.md` and treats it as the first hand-off into the team.

## Design tradeoffs & how we handle them

- **Token cost of injecting markdown.** Full memory files can grow large. Mitigation: inject only the *recent tail* of the journal + a *summarized* head of local memory; hand-offs are deliberately short by template. Trimming/summarization thresholds are configurable.
- **Concurrency / write contention.** Parallel agents never share a file — per-instance memory files + an append-only journal written through a single serialized sink. No locks needed on the hot path.
- **Staleness.** Persistent cross-run memory can accumulate outdated notes. Mitigation: periodic compaction (a maintenance agent rewrites a role's memory file, keeping durable lessons, dropping run-specific noise) — opt-in.
- **Privacy / cleanup.** Run folders are local files; a retention setting prunes old runs. Nothing leaves the machine except the API calls themselves.
- **Determinism.** Because memory + hand-offs are on disk, a run is fully reconstructable after the fact — you can read exactly what each agent saw and said.

## What this gives you in practice

One top-level call (`maw.run(...)` or the conductor) produces a self-documenting run folder where the agents passed work to each other through readable notes, remembered their own context, and looped for quality — and you never wrote a single "now take the previous output and…" prompt.
