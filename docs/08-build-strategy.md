# Build Strategy — Zero Extra Cost (Subscription Only)

> Goal: run the entire framework on your existing **Claude Pro/Max subscription**, through **Claude Code** in the terminal. No Anthropic API key, no per-token charges, no separate billing. The only "cost" is your normal subscription usage limits, which you already pay for.

## The core idea

Earlier docs described Multi-Agent Workflow as a Python program that calls the Claude API. That path is powerful but **bills per token** — separate from your subscription. To avoid any extra cost, we flip the implementation:

**Don't build a program that calls the model. Build a library of configuration that Claude Code executes.**

Claude Code (the terminal tool) is included in Pro/Max and runs on your subscription. So the "intelligence" — the conductor, the agents, the quality loops, the gates — lives in **prompts** (subagents and skills) that Claude Code runs in a normal session. The only actual *code* Multi-Agent Workflow contains is non-AI plumbing — scaffolding folders, running tests, computing checks, git — which executes as shell/Bash and costs nothing.

Net result: the same architecture from docs 00–07, but the runtime is Claude Code on your plan instead of metered API calls.

## What "Multi-Agent Workflow" physically becomes

A set of files installed under **user scope** (`~/.claude/`), so it's available in *every* terminal/project automatically — that is your "reference back to this whenever I need a multi-agent workflow":

```
~/.claude/
├── agents/                      # the ROSTER — one .md per role (subagents)
│   ├── conductor.md             # assesses task, selects team, delegates
│   ├── planner.md
│   ├── critic.md
│   ├── leakage_auditor.md       # ML pack (doc 06)
│   ├── overfitting_checker.md
│   ├── baseline_enforcer.md
│   ├── bug_hunter.md            # code pack (doc 07)
│   ├── debugger.md
│   ├── dep_mapper.md
│   ├── code_reviewer.md
│   └── acceptance_gate.md       # independent terminal gate (doc 01)
├── skills/
│   ├── maw/SKILL.md         # entry point: /maw <problem>
│   ├── ml-experiment/SKILL.md   # workflow skills (optional)
│   └── debug/SKILL.md
├── CLAUDE.md                    # the conventions: md memory, hand-off template,
│                                #   MAW-DEP tags, deps.md, governor caps
└── maw-tools/               # NON-AI helper scripts (run via Bash = free)
    ├── scaffold_run.py          # create the run folder + memory/handoff files
    ├── ml_checks.py             # train-test gap, shuffled-label, calibration…
    └── code_checks.py           # test runner, static analysis, AST dep scan
```

Each `agents/*.md` is a subagent with its own system prompt, restricted tool list, and model (`model: haiku|sonnet|opus`). `skills/maw/SKILL.md` is the conductor logic written as a prompt. No `anthropic` SDK, no API client, no `maw.run()`.

## How a run goes — entirely on the subscription

1. Open a terminal anywhere and run `claude`.
2. Type `/maw <your problem>` (or just describe the task — the skill can auto-trigger on its description).
3. The **conductor skill** assesses the problem, picks the needed roles from the roster, sets the quality bar, and delegates to subagents — all normal Claude Code turns on your plan.
4. Agents coordinate through markdown files in a run folder (doc 05); deterministic checks run as Bash scripts (free); the `refine` loop iterates; the **acceptance gate** subagent ships or kicks it back.
5. Output lands in your working folder. **No token bill** — just subscription usage.

The `/maw` skill *is* Stages 1 and 2 from the build discussion (assess → select → execute), but performed inside the session rather than by an external API-calling program.

## The deterministic-tools advantage (saves turns *and* improves quality)

Many checks in docs 06–07 are pure computation, not judgment: train-test gap, shuffled-label control, calibration/ECE, significance tests, running the test suite, static analysis, AST dependency scanning. Implement these as **plain scripts in `maw-tools/`** that subagents invoke via the Bash tool.

Two wins: they consume **zero model tokens** (it's just Python running locally), and they're **more reliable** than asking an LLM to eyeball a number. So the design rule is *compute first, reason second* — push every check that can be deterministic onto a script, and let the agent only interpret the result. This both stretches your subscription limits and raises quality.

## Managing subscription usage (the only real constraint)

Multi-agent work means more turns, which draws down your plan's limits faster than normal chat. Everything here is free to do:

- **Right-size the models per role.** Set `model: haiku` on routine subagents (auditors, formatters), reserve `sonnet`/`opus` for the conductor and acceptance gate. Cheaper models = less of your quota per turn.
- **Keep the conductor conservative.** The governor (doc 01) already biases toward the smallest reasonable team and escalates only on failure — fewer agents, fewer turns.
- **Lean on deterministic tools** (above) so model turns aren't spent on things a script can compute.
- **Tight prompts.** Lean subagent system prompts and short hand-off notes (doc 05) reduce tokens per turn.
- **Schedule heavy runs** when you're not otherwise using your quota.
- If you hit a limit, you simply **wait for the reset** — there is never a surprise charge. That's the whole point of staying subscription-only.

## Honest tradeoffs vs. the API/SDK path

- Runs **in/through a terminal session** (interactive, or `claude -p` headless — both on the subscription). It is not an unattended cloud service or embeddable library. Fine for personal/reference use.
- Bound by **subscription usage limits** rather than pay-as-you-go elasticity. You trade "unlimited if you pay" for "free up to your plan's cap."
- **Per-subagent MCP filtering** isn't available — a subagent sees all servers in `.mcp.json`.
- Harder to run on a **server/CI** without your auth/session present.

None of these matter for the stated goal: a reusable, personal, multi-agent tool at no extra cost.

## Phased build (zero-cost throughout)

**Phase 0 — Confirm the free runtime.** Ensure Claude Code is working on your Pro/Max login (no API key configured). A `claude` session that responds confirms you're on subscription billing.

**Phase 1 — Minimal roster + conventions.** Create 2–3 subagents in `~/.claude/agents/` (e.g. `planner`, `worker`, `critic`) and a `CLAUDE.md` with the memory/hand-off conventions. Test manual delegation in a session.

**Phase 2 — The conductor skill.** Write `~/.claude/skills/maw/SKILL.md`: assess the task, select roles, delegate, enforce the markdown memory + hand-off conventions. Test `/maw` on a simple task end to end.

**Phase 3 — Deterministic tools + quality loop.** Add `maw-tools/` scripts (test runner, a couple of ML/code checks) invoked via Bash; wire the `refine` loop and the `acceptance_gate` subagent.

**Phase 4 — Fill out the packs.** Add the full ML roster (doc 06) and code roster (doc 07) as subagents, plus workflow skills (`ml-experiment`, `debug`).

**Phase 5 — Polish.** A scaffolding helper for run folders, a few worked examples, and tightening prompts/models to economize on usage.

## What changes vs. the earlier (API-centric) docs

- **No `core/client.py`** wrapping the `anthropic` SDK — Claude Code *is* the runtime. (Doc 01's Layer 1 is provided by Claude Code, not built.)
- **`maw.run(...)`** becomes **`/maw ...`** in the terminal (or `claude -p "/maw ..."` for headless, still subscription-billed).
- The conceptual layers, patterns, memory/hand-offs, ML/code packs, and gates (docs 00–07) are all unchanged — they're realized as subagents, skills, `CLAUDE.md`, and helper scripts instead of Python that calls the API.
- **`@tool` functions** split: deterministic ones become Bash-invoked scripts (free, reliable); only genuinely dynamic tools would need Claude Code custom tools.

## If you ever *do* want the API path later

Nothing here blocks it. Because the agents and conventions are plain markdown, the same roster could later be driven by the Agent SDK or raw API for unattended/embedded use — you'd just be choosing to pay per token for elasticity. The subscription-only build is the default; the API build is an optional upgrade, not a prerequisite.
