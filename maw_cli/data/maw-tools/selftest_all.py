#!/usr/bin/env python3
"""Aggregate deterministic MAW self-tests, including the front-end/UI pack."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
WEB_CHECKS = TOOLS / "web_checks.py"
SELFTEST_CHECKS = TOOLS / "selftest_checks.py"
SELFTEST_WEB = TOOLS / "selftest_web_checks.py"


GOOD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Good Fixture</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>Good Fixture</h1>
  <main id="content">
    <h2>Section</h2>
    <img src="hero.txt" alt="Fixture image">
    <label for="email">Email</label>
    <input id="email" name="email">
    <button type="button">Save</button>
  </main>
</body>
</html>
"""


BAD_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
</head>
<body>
  <h1>Bad Fixture</h1>
  <h3>Skipped Heading</h3>
  <img src="hero.txt">
  <input id="email" name="email">
</body>
</html>
"""


def run_json(command: list[str]) -> tuple[int, dict, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout), proc.stdout, proc.stderr


def main() -> int:
    results: list[dict] = []

    for name, script in (("core_checks", SELFTEST_CHECKS), ("web_checks", SELFTEST_WEB)):
        code, data, stdout, stderr = run_json([sys.executable, str(script)])
        results.append({"name": name, "passed": code == 0 and data.get("passed") is True, "exit_code": code, "stdout": stdout.strip(), "stderr": stderr.strip()})

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        good = tmp / "good.html"
        bad = tmp / "bad.html"
        style = tmp / "style.css"
        hero = tmp / "hero.txt"
        good.write_text(GOOD_HTML, encoding="utf-8")
        bad.write_text(BAD_HTML, encoding="utf-8")
        style.write_text("body { color: #1f2937; background: #ffffff; }\n", encoding="utf-8")
        hero.write_text("fixture asset\n", encoding="utf-8")

        contrast_code, contrast, contrast_stdout, contrast_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "contrast", "--foreground", "#9aa0a6", "--background", "#ffffff"]
        )
        bad_a11y_code, bad_a11y, bad_a11y_stdout, bad_a11y_stderr = run_json([sys.executable, str(WEB_CHECKS), "a11y", str(bad)])
        good_a11y_code, good_a11y, good_a11y_stdout, good_a11y_stderr = run_json([sys.executable, str(WEB_CHECKS), "a11y", str(good)])
        budget_code, budget, budget_stdout, budget_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "budget", str(good), "--max-bytes", "4096", "--max-elements", "50", "--max-assets", "5"]
        )

        pinned = {
            "bad_contrast_ratio": contrast["ratio"],
            "bad_a11y_violation_count": bad_a11y["violation_count"],
            "good_a11y_violation_count": good_a11y["violation_count"],
            "page_budget_passed": budget["passed"],
            "page_budget_total_bytes": budget["total_bytes"],
        }
        expected = {
            "bad_contrast_ratio": 2.640526,
            "bad_a11y_violation_count": 6,
            "good_a11y_violation_count": 0,
            "page_budget_passed": True,
        }
        results.extend(
            [
                {
                    "name": "pinned_bad_contrast_ratio",
                    "passed": contrast_code != 0 and pinned["bad_contrast_ratio"] == expected["bad_contrast_ratio"],
                    "expected": expected["bad_contrast_ratio"],
                    "actual": pinned["bad_contrast_ratio"],
                    "stdout": contrast_stdout.strip(),
                    "stderr": contrast_stderr.strip(),
                },
                {
                    "name": "pinned_a11y_violation_count_before_fix",
                    "passed": bad_a11y_code != 0 and pinned["bad_a11y_violation_count"] == expected["bad_a11y_violation_count"],
                    "expected": expected["bad_a11y_violation_count"],
                    "actual": pinned["bad_a11y_violation_count"],
                    "stdout": bad_a11y_stdout.strip(),
                    "stderr": bad_a11y_stderr.strip(),
                },
                {
                    "name": "pinned_a11y_violation_count_after_fix",
                    "passed": good_a11y_code == 0 and pinned["good_a11y_violation_count"] == expected["good_a11y_violation_count"],
                    "expected": expected["good_a11y_violation_count"],
                    "actual": pinned["good_a11y_violation_count"],
                    "stdout": good_a11y_stdout.strip(),
                    "stderr": good_a11y_stderr.strip(),
                },
                {
                    "name": "pinned_page_byte_budget_result",
                    "passed": budget_code == 0 and pinned["page_budget_passed"] == expected["page_budget_passed"],
                    "expected": expected["page_budget_passed"],
                    "actual": pinned["page_budget_passed"],
                    "stdout": budget_stdout.strip(),
                    "stderr": budget_stderr.strip(),
                },
            ]
        )

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "checks": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
