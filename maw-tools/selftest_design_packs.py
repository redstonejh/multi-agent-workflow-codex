#!/usr/bin/env python3
"""Self-tests for reusable MAW design-language packs."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
APPLY = TOOLS / "apply_design.py"
PARITY = TOOLS / "design_parity.py"


FIXTURE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Liquid Glass Fixture</title>
</head>
<body>
  <main>
    <section class="glass">Glass</section>
    <section class="glass-strong">Strong</section>
    <button class="glass-control" type="button">Control</button>
    <aside class="glass-popover">Popover</aside>
  </main>
</body>
</html>
"""


def run_json(command: list[str]) -> tuple[int, dict, str, str]:
    proc = subprocess.run(command, capture_output=True, text=True)
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, data, proc.stdout, proc.stderr


def main() -> int:
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "site"
        target.mkdir()
        (target / "index.html").write_text(FIXTURE_HTML, encoding="utf-8")

        apply_code, apply_data, apply_stdout, apply_stderr = run_json([sys.executable, str(APPLY), "liquid-glass", str(target)])
        parity_code, parity_data, parity_stdout, parity_stderr = run_json([sys.executable, str(PARITY), str(target)])

        drift = Path(tmp_dir) / "drift"
        shutil.copytree(target, drift)
        tokens = drift / "assets" / "liquid-glass" / "tokens.css"
        tokens.write_text(tokens.read_text(encoding="utf-8").replace("--liquid-glass-backdrop-blur: 6px;", "--liquid-glass-backdrop-blur: 14px;"), encoding="utf-8")
        drift_code, drift_data, drift_stdout, drift_stderr = run_json([sys.executable, str(PARITY), str(drift)])

        results.extend(
            [
                {
                    "name": "apply_liquid_glass_to_web_fixture",
                    "passed": apply_code == 0 and apply_data.get("passed") is True and (target / "assets" / "liquid-glass" / "glass-kit.css").is_file(),
                    "stdout": apply_stdout.strip(),
                    "stderr": apply_stderr.strip(),
                },
                {
                    "name": "design_parity_passes_for_adopted_pack",
                    "passed": parity_code == 0 and parity_data.get("passed") is True and parity_data.get("diff_count") == 0,
                    "stdout": parity_stdout.strip(),
                    "stderr": parity_stderr.strip(),
                },
                {
                    "name": "design_parity_trips_on_blur_token_drift",
                    "passed": drift_code != 0 and drift_data.get("passed") is False and drift_data.get("diff_count", 0) > 0,
                    "stdout": drift_stdout.strip(),
                    "stderr": drift_stderr.strip(),
                },
            ]
        )

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "checks": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
