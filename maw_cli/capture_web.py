"""Optional browser characterization adapter for client-rendered DOM capture.

This adapter is intentionally outside the stdlib-only maw-tools spine. It
requires Playwright and a browser install. Missing dependencies produce
NEEDS-HUMAN instead of silently downgrading coverage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def emit(data: dict[str, Any], output: str | None = None) -> int:
    text = json.dumps(data, indent=2, sort_keys=True)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if data.get("passed") is True else 1


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture(url: str) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {
            "check": "salvage_browser_characterization",
            "schema_version": 1,
            "passed": False,
            "status": "NEEDS-HUMAN",
            "errors": ["Playwright is required for client-rendered DOM capture"],
            "items": [],
            "target": url,
        }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            response = page.goto(url, wait_until="networkidle", timeout=15_000)
            html = page.content()
            title = page.title()
            browser.close()
        return {
            "check": "salvage_browser_characterization",
            "schema_version": 1,
            "passed": True,
            "target": url,
            "captured_at_epoch": time.time(),
            "items": [
                {
                    "type": "client_dom",
                    "name": url,
                    "url": url,
                    "status": response.status if response else 0,
                    "sha256": sha256_text(html),
                    "metadata": {"title": title},
                }
            ],
            "errors": [],
        }
    except Exception as exc:
        return {
            "check": "salvage_browser_characterization",
            "schema_version": 1,
            "passed": False,
            "status": "NEEDS-HUMAN",
            "errors": [str(exc)],
            "items": [],
            "target": url,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture client-rendered DOM with Playwright.")
    parser.add_argument("url")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return emit(capture(args.url), args.output)


if __name__ == "__main__":
    raise SystemExit(main())
