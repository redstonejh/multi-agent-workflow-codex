#!/usr/bin/env python3
"""Self-test the stdlib front-end/UI web checks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


WEB_CHECKS = Path(__file__).with_name("web_checks.py")


GOOD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Good Fixture</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header>
    <h1>Good Fixture</h1>
    <nav><a href="#content">Content</a></nav>
  </header>
  <main id="content">
    <h2>Section</h2>
    <img src="hero.txt" alt="Decorative fixture block">
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
  <link rel="stylesheet" href="missing.css">
</head>
<body>
  <h1>Bad Fixture</h1>
  <h3>Skipped Heading</h3>
  <a href="#missing">Broken anchor</a>
  <img src="missing-image.txt">
  <input id="email" name="email">
  <div id="dup">One</div>
  <div id="dup">Two</div>
  <section><p>Unclosed section
</body>
</html>
"""


def run_check(*args: str) -> tuple[int, dict, str, str]:
    proc = subprocess.run([sys.executable, str(WEB_CHECKS), *args], capture_output=True, text=True)
    data = json.loads(proc.stdout)
    return proc.returncode, data, proc.stdout, proc.stderr


def write_fixture(root: Path, html: str) -> Path:
    page = root / "index.html"
    page.write_text(html, encoding="utf-8")
    (root / "style.css").write_text("body { color: #1f2937; background: #ffffff; }\n", encoding="utf-8")
    (root / "hero.txt").write_text("fixture asset\n", encoding="utf-8")
    return page


def main() -> int:
    assertions: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        good_dir = tmp / "good"
        bad_dir = tmp / "bad"
        good_dir.mkdir()
        bad_dir.mkdir()
        good_page = write_fixture(good_dir, GOOD_HTML)
        bad_page = write_fixture(bad_dir, BAD_HTML + ("x" * 2048))

        checks = [
            ("contrast_good", ("contrast", "--foreground", "#111827", "--background", "#ffffff"), True),
            ("contrast_bad", ("contrast", "--foreground", "#9aa0a6", "--background", "#ffffff"), False),
            ("a11y_good", ("a11y", str(good_page)), True),
            ("a11y_bad", ("a11y", str(bad_page)), False),
            ("budget_good", ("budget", str(good_page), "--max-bytes", "4096", "--max-elements", "50", "--max-assets", "5"), True),
            ("budget_bad", ("budget", str(bad_page), "--max-bytes", "512", "--max-elements", "50", "--max-assets", "5"), False),
            ("links_good", ("links", str(good_page)), True),
            ("links_bad", ("links", str(bad_page)), False),
            ("markup_good", ("markup", str(good_page)), True),
            ("markup_bad", ("markup", str(bad_page)), False),
        ]

        for name, args, expected_passed in checks:
            code, data, stdout, stderr = run_check(*args)
            passed = data["passed"] is expected_passed and ((code == 0) is expected_passed)
            assertions.append(
                {
                    "name": name,
                    "passed": passed,
                    "expected_check_passed": expected_passed,
                    "tool_exit_code": code,
                    "tool_passed": data["passed"],
                    "stdout": stdout.strip(),
                    "stderr": stderr.strip(),
                }
            )

    ok = sum(1 for item in assertions if item["passed"])
    result = {"passed": ok == len(assertions), "assertions": len(assertions), "ok": ok, "results": assertions}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
