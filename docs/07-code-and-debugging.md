# Code Work — Bugs, Debugging, Root Cause, Comments & Hidden Dependencies

The software counterpart to the ML pack (`06`). A roster of specialized agents, methodologies, markdown artifacts, and **code-annotation conventions** for working on real codebases — including the spaghetti-code / hidden-coupling case. Everything is recorded in the markdown run folder (`05`) and gated by the acceptance gate (`01`).

---

## 1. Parallelizing code work safely

Code tasks are full of non-obvious ordering constraints, so parallelism here leans hard on the dependency DAG (`01-architecture.md`). The rule: decompose the work, declare each unit's read/write footprint (which files/modules/resources it touches), run only the independent frontier concurrently, serialize the rest. As hidden edges are discovered (below), they feed back into the DAG so the next pass parallelizes correctly. Two refactors that both edit the same module, or a fix that depends on another fix landing first, must *not* run concurrently — the scheduler enforces that.

## 2. Finding bugs (methodology)

Order matters: **reproduce first.** A bug you can't reproduce, you can't confirm fixed.

1. **Reproduce** — establish a deterministic repro (ideally a failing test) before touching anything.
2. **Discover** via multiple sources, not just the reported symptom: failing/added tests, static analysis + linters, type checks, runtime errors and logs, recent-diff review, property/fuzz testing, and explicit edge-case enumeration (empty, null, boundary, concurrent, malformed input).
3. **Triage** — severity, blast radius (what else touches this), frequency/trigger conditions.
4. **Write it up** as a structured bug report (artifact).

### Bug report template (`bugs/BUG-NNN.md`)

```markdown
# BUG-007: dedupe drops valid orders when input arrives unsorted
Severity: high   Status: open   Found-by: bug_hunter

## Symptom        — what is observed (the failure, not the guess)
## Reproduction   — exact steps / the failing test, deterministic
## Expected vs actual
## Scope / blast radius — modules, callers, data affected
## Evidence        — stack trace, failing assertion, log excerpt
```

## 3. Debugging (the root-cause search loop)

This is the `refine` loop applied to debugging: **hypothesis → instrument/test → observe → narrow**, each iteration recorded to the journal. The goal is the single change that reliably toggles the bug — that's the cause, not a symptom. Techniques the `debugger` agent uses:

- **Bisection** — binary-search the offending change (`git bisect`) or the failing input.
- **Delta debugging** — minimize the failing input to the smallest reproducer.
- **Differential** — it works here but not there; enumerate what differs.
- **Instrumentation** — targeted logging/asserts around the hypothesis.
- **Trace / rubber-duck** — walk the execution path and state explicitly.

Stop condition: a change that flips the bug on/off deterministically, with the mechanism understood.

## 4. Root cause analysis (written, not just "added a null check")

A fix without an RCA repeats the mistake elsewhere. The `rca_writer` produces:

```markdown
# RCA BUG-007
## Root cause      — the underlying mechanism (e.g. "dedupe assumes sorted input;
                      an upstream change removed the sort"). NOT the symptom.
## Why not caught  — the gap: no test for unsorted input; the coupling was implicit.
## Fix             — what changed and why it addresses the *cause*.
## Prevention      — regression test added / guard / lint rule / type so it can't recur.
## Related risks   — other call sites with the same latent assumption.
```

The "why not caught" + "prevention" + "related risks" sections are what turn a one-off patch into a durable improvement and surface sibling bugs.

## 5. Fix & verification

- The repro test must now **pass**, and is kept as a **permanent regression test**.
- Re-run the broader suite — no new breakage.
- The **acceptance gate** (`01`) gives independent confirmation: the fix addresses the *reported symptom*, the RCA's claims match the actual diff and test results (claim-to-evidence), and nothing is overclaimed. For code, the independent `code_reviewer` is the gate's reviewer role.

## 6. Should agents write comments? — Yes, but only the right kind

Default policy the agents follow:

- **Comment the *why*, never the *what*.** The code already states what it does; comments capture intent, constraints, trade-offs, and non-obvious reasoning. `# increment i` is noise; `# retry 3x: upstream API returns 503 under load (see BUG-014)` is gold.
- **Don't restate code** — redundant comments rot and mislead once code changes.
- **Do comment:** non-obvious dependencies (below), surprising invariants, workarounds for external/library bugs, performance- or security-critical choices, and "do not reorder / must stay in sync" constraints.
- **Keep comments adjacent** to the code they describe and update/delete them when that code changes.

## 7. Hidden dependencies / spaghetti code — annotate in place AND centrally

When the system discovers a non-obvious coupling — changing X silently breaks Y, with no visible link — it captures it in **two** places, linked by an ID:

### (a) Inline marker, right above the line/function

A greppable tag so the next person editing that exact spot sees the landmine:

```python
# MAW-DEP[D12]: `orders` must be pre-sorted by sync_job() (jobs.py:88).
# Filtering or reordering before this point silently breaks the dedupe below.
# See deps.md#D12.
def dedupe_orders(orders):
    ...
```

### (b) Central dependency map (`deps.md`)

Every discovered coupling, queryable, with a stable ID:

```markdown
## D12  jobs.sync_job  →  orders.dedupe_orders
Type: ordering (implicit precondition: input sorted)
Discovered: BUG-007 debugging, 2026-06-01
Risk: high — no test guards it; 3 other callers (api.py:41, batch.py:9, cli.py:77)
Annotated at: orders.py:88
```

### Tag conventions (all greppable)

- `# MAW-DEP[id]:` — hidden dependency / implicit precondition
- `# MAW-BUG[id]:` — known bug or caveat at this spot
- `# MAW-RCA[id]:` — why this code is the way it is (links to an RCA)
- `# MAW-TODO[id]:` — deferred work

**Why both inline and central?** Inline catches you at the moment of editing, where a separate doc would be forgotten; central makes the knowledge discoverable and lets agents/tooling reason over the *whole* coupling graph. The inline marker links to the central entry by ID, so the two stay in sync, and removing a dependency means closing both.

### This is what makes parallelism safe

The dependency map *is* the input to the DAG scheduler (§1): two code tasks may run concurrently only if they don't touch a shared `DEP` edge. Every hidden coupling discovered during debugging is therefore not just documented — it tightens future scheduling and blast-radius estimates so the system stops parallelizing things that secretly conflict.

## 8. Code roster

| agent | owns | key tools |
|---|---|---|
| `repro_engineer` | deterministic reproduction / failing test | test runner, env capture |
| `bug_hunter` | discovery via tests, static analysis, fuzzing | linter, type checker, fuzzer, diff reader |
| `debugger` | hypothesis-driven root-cause search | bisection, delta-debug, instrumentation |
| `rca_writer` | root cause + prevention writeups | (LLM over journal + diff) |
| `fixer` | implements the fix + regression test | editor, test runner |
| `dep_mapper` | finds, annotates, and maintains hidden deps | call-graph/AST analysis, deps.md writer |
| `code_reviewer` | independent review (acceptance-gate role) | diff reader, test runner |

The conductor pulls in whichever roles a task warrants (a quick fix may need only `repro_engineer` + `fixer` + `code_reviewer`; a gnarly heisenbug pulls in `debugger` and `dep_mapper`), within the governor's caps — exactly like the ML pack, just a different roster and rubric.
