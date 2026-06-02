#!/usr/bin/env python3
"""Create MAW run folders and markdown handoff files."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import secrets
import sys
from pathlib import Path


ROLES = ("conductor", "planner", "worker", "critic", "acceptance_gate")

HANDOFF_TEMPLATE = """# Hand-off: {frm} -> {to}  (run {run_id}, step {step:02d})

## Task context
<What we are trying to achieve, in 1-2 lines.>

## What I did
<Concrete work completed in this step.>

## Output / artifacts
- <artifacts/...>  (what was produced)

## Open questions / risks
<Things the next role should watch.>

## Recommended next step
<What the next role should do next.>
"""

RUN_TEMPLATE = """# Run {run_id}

- Task: {task}
- Created: {created}
- Status: in-progress

## Conductor plan
Roles, pattern, quality bar, deterministic checks, and acceptance criteria.

## Final result summary
Pending acceptance gate.
"""

MEMORY_TEMPLATE = """# Shared Journal - {run_id}

Append one short entry per role turn.
"""

AGENT_TEMPLATE = """# {role} Notes - {run_id}

Local scratchpad for this role.
"""


def slugify(text: str, max_words: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:max_words]) if words else "run"


def next_step(handoffs_dir: Path) -> int:
    steps: list[int] = []
    for path in handoffs_dir.glob("[0-9][0-9]_*.md"):
        try:
            steps.append(int(path.name[:2]))
        except ValueError:
            pass
    return max(steps, default=0) + 1


def parse_agents(value: str | None) -> list[str]:
    if not value:
        return list(ROLES)
    return [agent.strip() for agent in value.split(",") if agent.strip()]


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    slug = args.slug or slugify(args.task)
    run_id = f"{dt.datetime.now().strftime('%Y-%m-%d')}_{slug}_{secrets.token_hex(2)}"
    run_dir = root / run_id
    if run_dir.exists():
        print(f"error: run folder already exists: {run_dir}", file=sys.stderr)
        return 2

    (run_dir / "agents").mkdir(parents=True)
    (run_dir / "handoffs").mkdir()
    (run_dir / "artifacts").mkdir()

    created = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    (run_dir / "run.md").write_text(RUN_TEMPLATE.format(run_id=run_id, task=args.task, created=created), encoding="utf-8")
    (run_dir / "memory.md").write_text(MEMORY_TEMPLATE.format(run_id=run_id), encoding="utf-8")

    agents = parse_agents(args.agents)
    for role in agents:
        (run_dir / "agents" / f"{role}.md").write_text(AGENT_TEMPLATE.format(role=role, run_id=run_id), encoding="utf-8")

    result = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "agents": agents,
        "handoffs": str(run_dir / "handoffs"),
        "artifacts": str(run_dir / "artifacts"),
    }
    print(json.dumps(result, indent=2) if args.json else str(run_dir))
    return 0


def cmd_handoff(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    handoffs_dir = run_dir / "handoffs"
    if not handoffs_dir.is_dir():
        print(f"error: missing handoffs directory: {handoffs_dir}", file=sys.stderr)
        return 2

    step = args.step or next_step(handoffs_dir)
    path = handoffs_dir / f"{step:02d}_{args.frm}__to__{args.to}.md"
    if path.exists() and not args.force:
        print(f"error: handoff already exists: {path}", file=sys.stderr)
        return 2
    path.write_text(HANDOFF_TEMPLATE.format(frm=args.frm, to=args.to, run_id=run_dir.name, step=step), encoding="utf-8")
    print(str(path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold Codex MAW run folders.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a new run folder")
    init.add_argument("task")
    init.add_argument("--agents", help="comma-separated role names")
    init.add_argument("--root", default="runs")
    init.add_argument("--slug")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=cmd_init)

    handoff = sub.add_parser("handoff", help="create a markdown handoff")
    handoff.add_argument("--run", required=True)
    handoff.add_argument("--from", dest="frm", required=True)
    handoff.add_argument("--to", required=True)
    handoff.add_argument("--step", type=int)
    handoff.add_argument("--force", action="store_true")
    handoff.set_defaults(func=cmd_handoff)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
