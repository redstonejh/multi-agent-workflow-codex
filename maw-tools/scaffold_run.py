#!/usr/bin/env python3
"""scaffold_run.py — create and maintain a Multi-Agent Workflow run folder.

This is a DETERMINISTIC helper. It calls no model and touches no network — it
only creates folders and writes markdown templates. The /maw conductor invokes
it via Bash so that the run-folder layout and the hand-off file naming from
docs/05-memory-and-handoffs.md are enforced by code rather than by prompt.

Usage
-----
  # Create a new run folder (prints the run dir path, or JSON with --json):
  python scaffold_run.py init "fix the failing test in payments.py" \
      --agents conductor,planner,worker,critic,acceptance_gate

  # Append a correctly-named, template-filled hand-off file to a run:
  python scaffold_run.py handoff --run runs/2026-06-01_fix-the_ab12 \
      --from planner --to worker

Both subcommands print the path(s) they create so the caller can capture them.
On a machine where `python` is not on PATH, invoke with `uv run` or `py`
instead (see CLAUDE.md / INSTALL.md).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import secrets
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str, max_words: int = 4) -> str:
    """Turn a task sentence into a short, filesystem-safe slug."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if not words:
        return "run"
    return "-".join(words[:max_words])


def _timestamp() -> str:
    # Local date is enough for a human-readable, sortable prefix.
    return _dt.datetime.now().strftime("%Y-%m-%d")


HANDOFF_TEMPLATE = """\
# Hand-off: {frm} → {to}  (run {run_id}, step {step:02d})

## Task context
<What we're ultimately trying to achieve, in 1-2 lines.>

## What I did
<The concrete work completed in this step.>

## Output / artifacts
- <artifacts/...>  (what was produced)
- <key result values inline if small>

## Open questions / risks
<Things the next agent should watch out for.>

## Recommended next step
<What you (the next agent) should do, specifically.>
"""

RUN_MD_TEMPLATE = """\
# Run {run_id}

- **Task:** {task}
- **Created:** {created}
- **Status:** in-progress

## Conductor plan
<Filled in by the conductor: roles selected, pattern, quality bar, one-line
reason per role, governor caps applied.>

## Final result summary
<Filled in at the end: the deliverable, the critic score / iterations, and the
acceptance gate verdict (SHIP / NO-SHIP + reasons).>
"""

MEMORY_MD_TEMPLATE = """\
# Shared journal — run {run_id}

Append-only, timestamped. One entry per agent turn. This is the common
blackboard: who did what, when, and where the output landed.

<!-- Append entries below, newest at the bottom. Example:

## 14:02 - planner
Decomposed the task into 3 steps. Wrote artifacts/plan.md.
Next: worker executes step 1.
-->
"""

AGENT_MD_TEMPLATE = """\
# {name} — local notes (run {run_id})

Your scratchpad for this run. Read this on start ("your notes so far"); append a
short structured note on finish (what you concluded, decisions, open threads).
"""


def _next_step(handoffs_dir: Path) -> int:
    """Find the next NN_ prefix for an ordered hand-off file."""
    existing = []
    for p in handoffs_dir.glob("[0-9][0-9]_*.md"):
        try:
            existing.append(int(p.name[:2]))
        except ValueError:
            continue
    return (max(existing) + 1) if existing else 1


# ---------------------------------------------------------------------------
# Subcommand: init
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    slug = args.slug or slugify(args.task)
    run_id = f"{_timestamp()}_{slug}_{secrets.token_hex(2)}"
    run_dir = root / run_id

    if run_dir.exists():
        print(f"error: run folder already exists: {run_dir}", file=sys.stderr)
        return 1

    # Folder layout from docs/05.
    (run_dir / "agents").mkdir(parents=True)
    (run_dir / "handoffs").mkdir()
    (run_dir / "artifacts").mkdir()

    created = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    (run_dir / "run.md").write_text(
        RUN_MD_TEMPLATE.format(run_id=run_id, task=args.task, created=created),
        encoding="utf-8",
    )
    (run_dir / "memory.md").write_text(
        MEMORY_MD_TEMPLATE.format(run_id=run_id), encoding="utf-8"
    )

    agents = [a.strip() for a in (args.agents or "").split(",") if a.strip()]
    for name in agents:
        (run_dir / "agents" / f"{name}.md").write_text(
            AGENT_MD_TEMPLATE.format(name=name, run_id=run_id), encoding="utf-8"
        )

    if args.json:
        print(json.dumps({
            "run_id": run_id,
            "run_dir": str(run_dir),
            "memory": str(run_dir / "memory.md"),
            "handoffs": str(run_dir / "handoffs"),
            "artifacts": str(run_dir / "artifacts"),
            "agents": agents,
        }, indent=2))
    else:
        print(str(run_dir))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: handoff
# ---------------------------------------------------------------------------

def cmd_handoff(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    handoffs_dir = run_dir / "handoffs"
    if not handoffs_dir.is_dir():
        print(f"error: no handoffs/ dir in {run_dir} (run init first)", file=sys.stderr)
        return 1

    step = args.step if args.step is not None else _next_step(handoffs_dir)
    fname = f"{step:02d}_{args.frm}__to__{args.to}.md"
    path = handoffs_dir / fname
    run_id = run_dir.name
    path.write_text(
        HANDOFF_TEMPLATE.format(frm=args.frm, to=args.to, run_id=run_id, step=step),
        encoding="utf-8",
    )
    print(str(path))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scaffold a Multi-Agent Workflow run folder.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="create a new run folder")
    pi.add_argument("task", help="the task / problem statement")
    pi.add_argument("--slug", help="explicit slug (default: derived from task)")
    pi.add_argument("--root", default="runs", help="root dir for runs (default: runs)")
    pi.add_argument("--agents", help="comma-separated agent names to pre-seed local memory files")
    pi.add_argument("--json", action="store_true", help="print machine-readable JSON")
    pi.set_defaults(func=cmd_init)

    ph = sub.add_parser("handoff", help="append a template-filled hand-off file")
    ph.add_argument("--run", required=True, help="path to the run folder")
    ph.add_argument("--from", dest="frm", required=True, help="producing agent name")
    ph.add_argument("--to", dest="to", required=True, help="consuming agent name")
    ph.add_argument("--step", type=int, default=None, help="step number (default: auto-increment)")
    ph.set_defaults(func=cmd_handoff)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
