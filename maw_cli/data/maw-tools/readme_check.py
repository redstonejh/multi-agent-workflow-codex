#!/usr/bin/env python3
"""Check README command and path references against the current repo."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CLI_FILES = (
    ROOT / "maw_cli" / "cli.py",
    ROOT / "maw_cli" / "ml_autopilot.py",
    ROOT / "maw_cli" / "wilds_benchmark.py",
)
COMMAND_RE = re.compile(r"^\s*maw\s+(?P<command>[a-z][a-z0-9-]*)\b", re.MULTILINE)
ADD_PARSER_RE = re.compile(r"\.add_parser\(\s*[\"'](?P<command>[a-z][a-z0-9-]*)[\"']")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def known_maw_commands() -> set[str]:
    commands: set[str] = set()
    for path in CLI_FILES:
        if path.is_file():
            commands.update(match.group("command") for match in ADD_PARSER_RE.finditer(path.read_text(encoding="utf-8")))
    return commands


def readme_maw_commands(text: str) -> list[str]:
    return [match.group("command") for match in COMMAND_RE.finditer(text)]


def looks_like_path(value: str) -> bool:
    if any(token in value for token in ("<", ">", "*", "...", " ")):
        return False
    if value.startswith(("http://", "https://", "python ", "maw ", "uv ")):
        return False
    if value.startswith(("runs/", "artifacts/", "data.")):
        return False
    if "/" not in value and "\\" not in value:
        return value in {"README.md", "AGENTS.md", "pyproject.toml"}
    return True


def readme_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in BACKTICK_RE.finditer(text):
        value = match.group(1).strip()
        if looks_like_path(value):
            paths.append(value)
    return paths


def check() -> dict[str, Any]:
    text = README.read_text(encoding="utf-8")
    known = known_maw_commands()
    commands = readme_maw_commands(text)
    paths = readme_paths(text)
    violations: list[dict[str, str]] = []

    for command in commands:
        if command not in known:
            violations.append({"type": "unknown_maw_command", "command": command})

    for value in paths:
        normalized = value.replace("\\", "/").rstrip("/")
        if not (ROOT / normalized).exists():
            violations.append({"type": "missing_referenced_path", "path": value})

    return {
        "check": "readme_references",
        "passed": not violations,
        "known_maw_commands": sorted(known),
        "readme_maw_commands": commands,
        "referenced_paths": paths,
        "violations": violations,
    }


def main() -> int:
    result = check()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
