"""Optional JS/TS code-graph adapter for MAW.

This adapter is intentionally outside the stdlib-only maw-tools spine. It
requires Node plus the TypeScript compiler API and emits NEEDS-HUMAN when those
dependencies are unavailable.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve().parent / "vendor" / "code_graph_js.js"


def emit(data: dict[str, Any], output: str | None = None) -> int:
    text = json.dumps(data, indent=2, sort_keys=True)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if data.get("passed") is True else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit normalized JS/TS code graph JSON.")
    parser.add_argument("path")
    parser.add_argument("--lang", choices=["js", "ts"], default="ts")
    parser.add_argument("--entrypoint", action="append", dest="entrypoints")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if shutil.which("node") is None:
        return emit({"schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "errors": ["Node.js is required for JS/TS code graph generation"], "modules": [], "symbols": [], "edges": [], "entrypoints": []}, args.output)
    command = [
        "node",
        str(SCRIPT),
        "--path",
        args.path,
        "--lang",
        args.lang,
        "--output",
        args.output,
        "--entrypoints-json",
        json.dumps(args.entrypoints or []),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return emit({"schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "errors": [str(exc)], "modules": [], "symbols": [], "edges": [], "entrypoints": []}, args.output)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "errors": [proc.stderr.strip() or "JS/TS code graph adapter produced invalid JSON"], "modules": [], "symbols": [], "edges": [], "entrypoints": []}
    if proc.returncode != 0:
        data["passed"] = False
        data.setdefault("status", "NEEDS-HUMAN")
        if proc.stderr.strip():
            data.setdefault("errors", []).append(proc.stderr.strip())
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0 if data.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
