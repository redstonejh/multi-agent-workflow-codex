#!/usr/bin/env python3
"""selftest_checks.py — prove maw-tools/checks.py reflects reality.

A check is only trustworthy once it has been shown to go RED on known-bad input.
`checks.py test` once exited 0 even when the test command failed (its JSON said
`passed: false` but the process returned 0), so any caller gating on `$?` read a
failing test as success — see bugs/RCA-001. This self-test runs `checks.py`
against commands with known outcomes and asserts both the JSON verdict AND the
process exit code are correct.

Run:  python maw-tools/selftest_checks.py   (or: uv run maw-tools/selftest_checks.py)
Exit: 0 if every assertion holds, 1 otherwise.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

CHECKS = Path(__file__).with_name("checks.py")
results: list[tuple[bool, str]] = []


def record(ok: bool, msg: str) -> None:
    results.append((ok, msg))
    print(f"  {'[ok]' if ok else '[XX]'} {msg}")


def run_checks(*args: str) -> tuple[int, dict | None]:
    """Run checks.py with args; return (exit_code, parsed_json_or_None)."""
    proc = subprocess.run(
        [sys.executable, str(CHECKS), *args],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = None
    return proc.returncode, data


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        passing = tmp / "t_pass.py"
        failing = tmp / "t_fail.py"
        passing.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
        failing.write_text("import sys; sys.exit(1)\n", encoding="utf-8")

        # --- test: a passing command -> passed true AND exit 0 ---
        print("checks.py test:")
        code, data = run_checks("test", "--cmd", f'"{sys.executable}" "{passing}"')
        record(code == 0 and data and data["passed"] is True,
               f"passing cmd -> exit {code}, passed={data and data.get('passed')} (want exit 0)")

        # --- test: a failing command -> passed false AND exit != 0 ---
        code, data = run_checks("test", "--cmd", f'"{sys.executable}" "{failing}"')
        record(code != 0 and data and data["passed"] is False,
               f"failing cmd -> exit {code}, passed={data and data.get('passed')} (want exit != 0)")

        # --- gap: verdict and exit code agree ---
        print("checks.py gap:")
        code, data = run_checks("gap", "--train", "0.80", "--test", "0.78", "--tol", "0.05")
        record(code == 0 and data and data["passed"] is True,
               f"within tolerance -> exit {code}, passed={data and data.get('passed')} (want exit 0)")
        code, data = run_checks("gap", "--train", "0.98", "--test", "0.70", "--tol", "0.05")
        record(code != 0 and data and data["passed"] is False,
               f"exceeds tolerance -> exit {code}, passed={data and data.get('passed')} (want exit != 0)")

    ok = all(r[0] for r in results)
    print(f"\n{'ALL PASS' if ok else 'FAILURES PRESENT'}: "
          f"{sum(1 for r in results if r[0])}/{len(results)} assertions held")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
