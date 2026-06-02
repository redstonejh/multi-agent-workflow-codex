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

CHANGE_BEFORE_CSS = """.btn {
  color: #202124;
  background: #e0e0e0;
  font-size: 1rem;
  padding: 0.5rem 0.75rem;
}
"""

CHANGE_AFTER_CSS = """.btn {
  color: #ffffff;
  background: #1a73e8;
  font-size: 1.125rem;
  padding: 0.75rem 1.25rem;
}
"""

CHANGE_DRIFT_CSS = """.btn {
  color: #ffffff;
  background: #0057ff;
  font-size: 1.125rem;
  padding: 0.75rem 1.25rem;
}
"""

DESIGN_TOKENS = {
    "colors": ["#202124", "#ffffff", "#e0e0e0", "#1a73e8"],
    "font_sizes": ["1rem", "1.125rem"],
    "spacing": ["0.5rem", "0.75rem", "1.25rem"],
}


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
        before_css = tmp / "change.before.css"
        after_css = tmp / "change.after.css"
        noop_css = tmp / "change.noop.css"
        drift_css = tmp / "change.drift.css"
        tokens = tmp / "design-tokens.json"
        good.write_text(GOOD_HTML, encoding="utf-8")
        bad.write_text(BAD_HTML, encoding="utf-8")
        style.write_text("body { color: #1f2937; background: #ffffff; }\n", encoding="utf-8")
        hero.write_text("fixture asset\n", encoding="utf-8")
        before_css.write_text(CHANGE_BEFORE_CSS, encoding="utf-8")
        after_css.write_text(CHANGE_AFTER_CSS, encoding="utf-8")
        noop_css.write_text(CHANGE_BEFORE_CSS, encoding="utf-8")
        drift_css.write_text(CHANGE_DRIFT_CSS, encoding="utf-8")
        tokens.write_text(json.dumps(DESIGN_TOKENS), encoding="utf-8")

        contrast_code, contrast, contrast_stdout, contrast_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "contrast", "--foreground", "#9aa0a6", "--background", "#ffffff"]
        )
        bad_a11y_code, bad_a11y, bad_a11y_stdout, bad_a11y_stderr = run_json([sys.executable, str(WEB_CHECKS), "a11y", str(bad)])
        good_a11y_code, good_a11y, good_a11y_stdout, good_a11y_stderr = run_json([sys.executable, str(WEB_CHECKS), "a11y", str(good)])
        budget_code, budget, budget_stdout, budget_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "budget", str(good), "--max-bytes", "4096", "--max-elements", "50", "--max-assets", "5"]
        )
        before_style_code, before_style, before_style_stdout, before_style_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "style", str(before_css), "--selector", ".btn", "--property", "background"]
        )
        after_style_code, after_style, after_style_stdout, after_style_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "style", str(after_css), "--selector", ".btn", "--property", "background"]
        )
        noop_changed_code, noop_changed, noop_changed_stdout, noop_changed_stderr = run_json(
            [
                sys.executable,
                str(WEB_CHECKS),
                "changed",
                "--before",
                str(before_css),
                "--after",
                str(noop_css),
                "--selector",
                ".btn",
                "--property",
                "background",
                "--expected",
                "#1a73e8",
            ]
        )
        real_changed_code, real_changed, real_changed_stdout, real_changed_stderr = run_json(
            [
                sys.executable,
                str(WEB_CHECKS),
                "changed",
                "--before",
                str(before_css),
                "--after",
                str(after_css),
                "--selector",
                ".btn",
                "--property",
                "background",
                "--expected",
                "#1a73e8",
            ]
        )
        drift_tokens_code, drift_tokens, drift_tokens_stdout, drift_tokens_stderr = run_json(
            [sys.executable, str(WEB_CHECKS), "tokens", "--token-file", str(tokens), str(drift_css)]
        )

        pinned = {
            "bad_contrast_ratio": contrast["ratio"],
            "bad_a11y_violation_count": bad_a11y["violation_count"],
            "good_a11y_violation_count": good_a11y["violation_count"],
            "page_budget_passed": budget["passed"],
            "page_budget_total_bytes": budget["total_bytes"],
            "before_style_value": before_style["value"],
            "after_style_value": after_style["value"],
            "noop_changed_passed": noop_changed["passed"],
            "real_changed_passed": real_changed["passed"],
            "token_drift_passed": drift_tokens["passed"],
        }
        expected = {
            "bad_contrast_ratio": 2.640526,
            "bad_a11y_violation_count": 6,
            "good_a11y_violation_count": 0,
            "page_budget_passed": True,
            "before_style_value": "#e0e0e0",
            "after_style_value": "#1a73e8",
            "noop_changed_passed": False,
            "real_changed_passed": True,
            "token_drift_passed": False,
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
                {
                    "name": "pinned_before_style_value",
                    "passed": before_style_code == 0 and pinned["before_style_value"] == expected["before_style_value"],
                    "expected": expected["before_style_value"],
                    "actual": pinned["before_style_value"],
                    "stdout": before_style_stdout.strip(),
                    "stderr": before_style_stderr.strip(),
                },
                {
                    "name": "pinned_after_style_value",
                    "passed": after_style_code == 0 and pinned["after_style_value"] == expected["after_style_value"],
                    "expected": expected["after_style_value"],
                    "actual": pinned["after_style_value"],
                    "stdout": after_style_stdout.strip(),
                    "stderr": after_style_stderr.strip(),
                },
                {
                    "name": "pinned_noop_changed_result_red",
                    "passed": noop_changed_code != 0 and pinned["noop_changed_passed"] == expected["noop_changed_passed"],
                    "expected": expected["noop_changed_passed"],
                    "actual": pinned["noop_changed_passed"],
                    "stdout": noop_changed_stdout.strip(),
                    "stderr": noop_changed_stderr.strip(),
                },
                {
                    "name": "pinned_real_changed_result_green",
                    "passed": real_changed_code == 0 and pinned["real_changed_passed"] == expected["real_changed_passed"],
                    "expected": expected["real_changed_passed"],
                    "actual": pinned["real_changed_passed"],
                    "stdout": real_changed_stdout.strip(),
                    "stderr": real_changed_stderr.strip(),
                },
                {
                    "name": "pinned_token_drift_fixture_red",
                    "passed": drift_tokens_code != 0 and pinned["token_drift_passed"] == expected["token_drift_passed"],
                    "expected": expected["token_drift_passed"],
                    "actual": pinned["token_drift_passed"],
                    "stdout": drift_tokens_stdout.strip(),
                    "stderr": drift_tokens_stderr.strip(),
                },
            ]
        )

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "checks": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
