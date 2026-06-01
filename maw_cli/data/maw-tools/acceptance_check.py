#!/usr/bin/env python3
"""Final deterministic acceptance check for a Codex MAW run."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import validate_handoffs


def run_test(command: str | None, cwd: str | None, timeout: float) -> dict:
    if not command:
        return {"configured": False, "passed": True}
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("checks.py")), "test", "--cmd", command, "--timeout", str(timeout), *([] if cwd is None else ["--cwd", cwd])],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "stdout": proc.stdout, "stderr": proc.stderr}
    data["configured"] = True
    data["tool_exit_code"] = proc.returncode
    return data


def verdict(handoffs: dict, test: dict) -> str:
    if not handoffs.get("passed"):
        return "NO-SHIP"
    if not test.get("passed"):
        return "NO-SHIP"
    return "SHIP"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final deterministic MAW acceptance checks.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--test-cmd")
    parser.add_argument("--test-cwd")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)

    run_dir = Path(args.run)
    handoffs = validate_handoffs.validate_run(run_dir)
    test = run_test(args.test_cmd, args.test_cwd, args.timeout)
    result = {
        "run": str(run_dir),
        "handoffs": handoffs,
        "test": test,
        "verdict": verdict(handoffs, test),
    }
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "SHIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
