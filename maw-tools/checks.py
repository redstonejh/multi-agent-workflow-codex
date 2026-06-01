#!/usr/bin/env python3
"""checks.py — deterministic checks for Multi-Agent Workflow.

The design rule from docs/08 is *compute first, reason second*: push every check
that can be deterministic onto a plain script, and let the agent only interpret
the result. These checks call NO model and touch NO network — they are pure
computation that runs locally for free and is more reliable than asking an LLM
to eyeball a number.

Subcommands
-----------
  test   Run a shell command and report pass/fail (exit code 0 == pass).
  stats  Descriptive statistics for a list of numbers (count/mean/std/...).
  gap    Train-vs-held-out gap check (a docs/06 overfitting demo).

All subcommands print a JSON object to stdout and exit 0 when the check itself
ran (the *result* of the check is in the JSON `passed` field), or non-zero on a
usage/runtime error.

Examples
--------
  python checks.py test --cmd "python -m pytest -q"
  python checks.py stats 0.81 0.83 0.79 0.85
  python checks.py gap --train 0.98 --test 0.81 --tol 0.05
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


def _emit(obj: dict) -> int:
    print(json.dumps(obj, indent=2))
    return 0


def _tail(text: str, limit: int = 2000) -> str:
    text = text or ""
    return text if len(text) <= limit else "...(truncated)...\n" + text[-limit:]


# ---------------------------------------------------------------------------
# Subcommand: test  — run a command, report pass/fail
# ---------------------------------------------------------------------------

def cmd_test(args: argparse.Namespace) -> int:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            args.cmd,
            shell=True,
            cwd=args.cwd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        timed_out = False
        exit_code = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        timed_out = True
        exit_code = None
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
    duration = round(time.monotonic() - start, 3)

    passed = (exit_code == 0) and not timed_out
    _emit({
        "check": "test",
        "command": args.cmd,
        "cwd": args.cwd or ".",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "passed": passed,
        "duration_sec": duration,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    })
    # The check tool's OWN exit code must track the test result, so callers that
    # gate on `$?` (the acceptance gate, CI, `&&` chains) can't read a failing
    # test as success. Previously this always returned 0 — a false-negative
    # vector (see bugs/RCA-001).
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# Subcommand: stats — descriptive statistics
# ---------------------------------------------------------------------------

def _load_numbers(args: argparse.Namespace) -> list[float]:
    raw: list[str] = list(args.numbers or [])
    if args.file:
        raw += Path(args.file).read_text(encoding="utf-8").split()
    return [float(x) for x in raw]


def cmd_stats(args: argparse.Namespace) -> int:
    nums = _load_numbers(args)
    if not nums:
        print("error: no numbers provided", file=sys.stderr)
        return 2
    n = len(nums)
    result = {
        "check": "stats",
        "count": n,
        "mean": statistics.fmean(nums),
        "min": min(nums),
        "max": max(nums),
        "median": statistics.median(nums),
        # Sample stdev needs n>=2; report 0.0 for a single value.
        "stdev": statistics.stdev(nums) if n > 1 else 0.0,
        "passed": True,  # stats always "succeeds"; interpretation is the agent's job
    }
    return _emit(result)


# ---------------------------------------------------------------------------
# Subcommand: gap — train-vs-held-out gap (overfitting demo, docs/06)
# ---------------------------------------------------------------------------

def cmd_gap(args: argparse.Namespace) -> int:
    gap = args.train - args.test
    passed = gap <= args.tol
    _emit({
        "check": "gap",
        "train_score": args.train,
        "test_score": args.test,
        "gap": round(gap, 6),
        "tolerance": args.tol,
        "passed": passed,
        "note": (
            "train-test gap within tolerance"
            if passed
            else "gap exceeds tolerance — possible overfitting (see docs/06)"
        ),
    })
    # Exit code tracks the verdict so callers can gate on `$?`.
    return 0 if passed else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Deterministic checks (no model, no network).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("test", help="run a shell command, report pass/fail")
    pt.add_argument("--cmd", required=True, help="the test command to run")
    pt.add_argument("--cwd", default=None, help="working directory")
    pt.add_argument("--timeout", type=float, default=600, help="timeout in seconds (default 600)")
    pt.set_defaults(func=cmd_test)

    ps = sub.add_parser("stats", help="descriptive statistics for numbers")
    ps.add_argument("numbers", nargs="*", help="numbers (space-separated)")
    ps.add_argument("--file", help="read whitespace-separated numbers from a file")
    ps.set_defaults(func=cmd_stats)

    pg = sub.add_parser("gap", help="train-vs-held-out gap check (overfitting demo)")
    pg.add_argument("--train", type=float, required=True, help="train score")
    pg.add_argument("--test", type=float, required=True, help="held-out / test score")
    pg.add_argument("--tol", type=float, default=0.05, help="max acceptable gap (default 0.05)")
    pg.set_defaults(func=cmd_gap)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
