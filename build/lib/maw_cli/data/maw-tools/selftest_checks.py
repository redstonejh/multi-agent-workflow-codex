#!/usr/bin/env python3
"""Small self-test for maw-tools/checks.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


CHECKS = Path(__file__).with_name("checks.py")


def run_checks(*args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(CHECKS), *args], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def main() -> int:
    results: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        passing = tmp / "passing.py"
        failing = tmp / "failing.py"
        passing.write_text("raise SystemExit(0)\n", encoding="utf-8")
        failing.write_text("raise SystemExit(1)\n", encoding="utf-8")

        code, data = run_checks("test", "--cmd", f'"{sys.executable}" "{passing}"')
        results.append(code == 0 and data["passed"] is True)
        code, data = run_checks("test", "--cmd", f'"{sys.executable}" "{failing}"')
        results.append(code != 0 and data["passed"] is False)
        code, data = run_checks("gap", "--train", "0.8", "--test", "0.78", "--tol", "0.05")
        results.append(code == 0 and data["passed"] is True)
        code, data = run_checks("gap", "--train", "0.98", "--test", "0.70", "--tol", "0.05")
        results.append(code != 0 and data["passed"] is False)

    print(json.dumps({"passed": all(results), "assertions": len(results), "ok": sum(results)}, indent=2))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
