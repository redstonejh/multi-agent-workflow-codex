# API Design (Developer Experience)

This is the surface I'd actually type. It's illustrative — a target to build toward and react to, not final. Goal: defining a new multi-agent workflow should be mostly declaring agents + picking patterns.

## 1. Define a tool

A plain function. Schema is generated from type hints + docstring; the docstring becomes the tool description Claude sees.

```python
from maw import tool

@tool
def run_training(dataset: str, epochs: int = 10) -> dict:
    """Train the model on a dataset and return metrics.

    Args:
        dataset: path or name of the dataset to train on.
        epochs: number of training epochs.
    """
    metrics = my_trainer.fit(dataset, epochs=epochs)
    return {"accuracy": metrics.acc, "loss": metrics.loss}
```

## 2. Define an agent

Decorator carries config; the docstring is the system prompt. Plain-LLM agents just omit capabilities.

```python
from maw import agent

@agent(model="claude-sonnet-4-6")
def planner():
    """You are a planning specialist. Given an ML problem, break it into
    concrete, ordered experiment steps with success criteria for each."""

@agent(
    model="claude-opus-4-6",
    tools=[run_training],
    mcp_servers=["github"],     # MCP tools merged in automatically
    memory=True,                # may read/write shared Context
)
def ml_engineer():
    """You are an ML engineer. Use the training tool to run experiments,
    inspect results, and iterate toward the success criteria."""
```

Structured output: declare a return type and the agent returns a validated object instead of text.

```python
from pydantic import BaseModel
from maw import agent

class Eval(BaseModel):
    score: float          # 0..1 overall
    per_criterion: dict[str, float]
    critique: str         # what to change

@agent(model="claude-opus-4-6", output_schema=Eval)
def critic():
    """You are a strict evaluator. Score the candidate against the rubric
    in context, return per-criterion scores and concrete, actionable critique."""
```

## 3. Use patterns

Patterns are functions you call inside a workflow. They take agents + input and use the shared Context implicitly.

```python
from maw import patterns as p

draft   = p.pipeline([extract, analyze, summarize], input=doc)
result  = p.orchestrate(lead=planner, workers=[ml_engineer], task=problem)
scan    = p.parallel(agent=reader, inputs=list_of_docs, reducer=synth)
picked  = p.route(router=triage, routes={"ml": ml_flow, "research": research_flow}, input=q)
```

The recursive quality loop — note the generator can be *any callable*, including another pattern:

```python
final = p.refine(
    generator=lambda ctx: p.orchestrate(lead=planner, workers=[ml_engineer], task=ctx),
    evaluator=critic,                 # returns an Eval (score + critique)
    seed=problem,
    threshold=0.9,
    max_iters=4,
    stop_on_plateau=True,
)
```

## 4. Define a workflow

A `@workflow` is plain Python — full control flow available. Registered by name so it's runnable by reference.

```python
from maw import workflow, patterns as p

@workflow
def ml_experiment(problem: str):
    """Plan, run, and iteratively improve an ML experiment until it meets the bar."""
    plan = p.orchestrate(lead=planner, workers=[ml_engineer], task=problem)

    return p.refine(
        generator=lambda ctx: p.orchestrate(lead=planner, workers=[ml_engineer], task=ctx),
        evaluator=critic,
        seed=plan,
        threshold=0.9,
        max_iters=4,
    )

@workflow
def do_anything(request: str):
    """Top-level router: send the request to the right specialist workflow."""
    return p.route(
        router=triage,
        routes={
            "ml": ml_experiment,
            "research": research_report,
            "code_review": review_pr,
        },
        input=request,
    )
```

## 4b. Let the conductor assemble the team (no hand-wiring)

When you don't want to write the workflow yourself, register agents in a roster and hand the conductor a task. It plans the team and runs it.

```python
from maw import conductor, roster

# roster auto-populates from @agent definitions; metadata aids selection
roster.register(planner,     does="breaks ML problems into ordered experiments", cost="low")
roster.register(ml_engineer, does="runs training experiments, iterates on results", cost="high")
roster.register(critic,      does="scores output against a rubric, gives critique", cost="med")

result = conductor.run(
    task="predict churn from the customers table, beat AUC 0.85",
    roster=roster,                 # or roster.scope("ml") to restrict roles
    governor={"max_agents": 6, "max_parallel": 3, "max_iters": 4, "max_usd": 2.00},
    acceptance=acceptance_gate,    # terminal independent gate; default if omitted
    human_signoff="high_stakes",   # off | high_stakes | always
)

print(result.plan)        # the team it chose + one-line reason per role
print(result.output)      # final answer
print(result.shipped)     # True only if the acceptance gate said SHIP
print(result.gate_report) # SHIP/NO-SHIP + reasons (conformance, claim-evidence, smoke test)
print(result.run_dir)     # path to the markdown run folder (memory + hand-offs)
```

The conductor decides how many `ml_engineer` instances to spin up, picks the pattern, sets the quality bar, stays inside the governor's caps, and — last — runs the **acceptance gate**: an independent agent (different model/seed than the producers) that checks task conformance, audits every claim in the output against the run folder, and smoke-tests the assembled pipeline on fresh input. NO-SHIP loops back with reasons; high-stakes/uncertain results route to human sign-off rather than auto-shipping.

## 4c. Memory & hand-offs are automatic

You don't manage these — you opt in and the framework does the rest (full design in `05-memory-and-handoffs.md`).

```python
@agent(model="claude-sonnet-4-6", memory=True)            # per-run md memory
def planner():
    """..."""

@agent(model="claude-opus-4-6", memory="persistent")       # remembers across runs
def ml_engineer():
    """..."""
```

With `memory` on, each agent auto-loads its `agents/<name>.md` at start and appends notes at finish, every step is logged to the shared `memory.md`, and **hand-off notes are generated and injected between agents automatically** — so a multi-agent chain runs from one top-level call with no manual "pass this to the next agent" prompts. Everything lands in a readable run folder you can open afterward.

## 4d. Specialized ML validators (tool-backed checks)

For ML work, validators combine a deterministic `@tool` (the actual computation) with an `@agent` that interprets it. Full catalog + rubric in `06-ml-validation.md`.

```python
from maw import tool, agent

@tool
def shuffled_label_control(dataset: str, model_spec: dict) -> dict:
    """Retrain on randomly shuffled labels; above-chance score implies leakage/bug."""
    return {"score": retrain_with_shuffled_labels(dataset, model_spec)}

@tool
def train_test_gap(history: dict) -> dict:
    """Return train vs held-out scores and their gap."""
    return {"train": history["train"], "test": history["test"],
            "gap": history["train"] - history["test"]}

@agent(model="claude-opus-4-6", tools=[shuffled_label_control, train_test_gap],
       output_schema=Eval)
def leakage_auditor():
    """Run the leakage tools, read the numbers, and judge whether features are
    plausibly future/target information. Number first, judgment second."""
```

These validators register in the roster like any other role, so the conductor can pull in `leakage_auditor`, `overfitting_checker`, `baseline_enforcer`, etc. when the task is ML, and the `refine` loop scores against the ML rubric (hard PASS/FAIL gates) instead of a vibe score.

## 5. Run it (library usage — the primary interface)

```python
import maw

# by reference, anywhere in any project
result = maw.run("ml_experiment", input="predict churn from the customers table")

print(result.output)        # final answer
print(result.score)         # quality score from the refine loop
print(result.iterations)    # how many improvement passes ran
print(result.cost)          # token + $ totals
result.trace.save("run.jsonl")   # full step-by-step for debugging
```

Async variant for concurrency-heavy workflows:

```python
result = await maw.arun("research_report", input=question)
```

## 6. Shared memory (Context) when you need explicit control

Most of the time patterns thread Context for you. When a workflow needs to read/write directly:

```python
@workflow
def staged(problem: str, ctx):           # ctx injected when declared
    ctx.put("problem", problem)
    plan = p.pipeline([planner], input=problem)
    ctx.put("plan", plan)                # later agents with memory=True can read it
    ...
```

## 7. Optional thin CLI (later, wraps the same core)

```bash
maw run ml_experiment --input "predict churn from the customers table"
maw list                     # show registered workflows + agents
maw trace run.jsonl          # pretty-print a past run
```

## Open API questions for us

- `refine` generator signature: pass the previous candidate + critique explicitly, or let the agent read them from Context? (Leaning: both — explicit args, Context as backup.)
- Should `@agent` decorate a function (docstring = prompt) or a class? Function is lighter; class allows lifecycle hooks. (Leaning: function for v1.)
- Structured output via Pydantic (nice validation, extra dep) vs. plain `TypedDict`/dataclass? (Leaning: Pydantic.)
- Concurrency model: `asyncio` throughout, or threads for tool execution? (Leaning: async core, threads for blocking tools.)
