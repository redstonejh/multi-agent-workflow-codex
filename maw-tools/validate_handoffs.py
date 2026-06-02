#!/usr/bin/env python3
"""Validate Codex MAW markdown handoff files."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


REQUIRED_SECTIONS = (
    "## Task context",
    "## What I did",
    "## Output / artifacts",
    "## Open questions / risks",
    "## Recommended next step",
)
NAME_RE = re.compile(r"^(?P<step>[0-9]{2})_(?P<frm>[a-zA-Z0-9_-]+)__to__(?P<to>[a-zA-Z0-9_-]+)\.md$")
HEADER_RE = re.compile(r"^# Hand-off: (?P<frm>.+?) -> (?P<to>.+?)  \(run (?P<run>.+?), step (?P<step>[0-9]{2})\)", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"<[^>\n]+>")


def section_body(text: str, section: str) -> str:
    start = text.find(section)
    if start == -1:
        return ""
    start += len(section)
    next_match = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def validate_file(path: Path, run_id: str) -> list[str]:
    errors: list[str] = []
    match = NAME_RE.match(path.name)
    if not match:
        return [f"{path}: invalid filename"]

    text = path.read_text(encoding="utf-8")
    header = HEADER_RE.search(text)
    if not header:
        errors.append(f"{path}: missing or invalid header")
    else:
        if header.group("frm") != match.group("frm") or header.group("to") != match.group("to"):
            errors.append(f"{path}: header roles do not match filename")
        if header.group("step") != match.group("step"):
            errors.append(f"{path}: header step does not match filename")
        if header.group("run") != run_id:
            errors.append(f"{path}: header run id does not match run folder")

    for section in REQUIRED_SECTIONS:
        body = section_body(text, section)
        if not body:
            errors.append(f"{path}: missing content for {section}")
        elif PLACEHOLDER_RE.search(body):
            errors.append(f"{path}: placeholder remains in {section}")
    return errors


def validate_sequence(files: list[Path]) -> list[str]:
    errors: list[str] = []
    steps_by_number: dict[int, list[Path]] = {}
    invalid_names = False

    for path in files:
        match = NAME_RE.match(path.name)
        if not match:
            invalid_names = True
            continue
        step = int(match.group("step"))
        steps_by_number.setdefault(step, []).append(path)

    if invalid_names:
        return errors

    for step, paths in sorted(steps_by_number.items()):
        if len(paths) > 1:
            names = ", ".join(path.name for path in paths)
            errors.append(f"duplicate handoff step {step:02d}: {names}")

    actual = sorted(steps_by_number)
    expected = list(range(1, len(files) + 1))
    if actual != expected:
        actual_text = ", ".join(f"{step:02d}" for step in actual) or "<none>"
        expected_text = ", ".join(f"{step:02d}" for step in expected) or "<none>"
        errors.append(f"handoff steps must be contiguous from 01: found [{actual_text}], expected [{expected_text}]")

    return errors


def validate_structure(run_dir: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    required_files = ("run.md", "memory.md")
    required_dirs = ("agents", "artifacts")

    for name in required_files:
        path = run_dir / name
        if not path.is_file():
            errors.append(f"missing required file: {path}")

    for name in required_dirs:
        path = run_dir / name
        if not path.is_dir():
            errors.append(f"missing required directory: {path}")

    agents_dir = run_dir / "agents"
    if not agents_dir.is_dir():
        return errors

    required_agents: set[str] = set()
    for path in files:
        match = NAME_RE.match(path.name)
        if match:
            required_agents.add(match.group("frm"))
            required_agents.add(match.group("to"))

    for agent in sorted(required_agents):
        path = agents_dir / f"{agent}.md"
        if not path.is_file():
            errors.append(f"missing required agent notes: {path}")

    return errors


def validate_run(run_dir: Path) -> dict:
    handoffs_dir = run_dir / "handoffs"
    errors: list[str] = []
    if not run_dir.is_dir():
        return {"run": str(run_dir), "passed": False, "errors": [f"not a directory: {run_dir}"]}
    if not handoffs_dir.is_dir():
        return {"run": str(run_dir), "passed": False, "errors": [f"missing handoffs directory: {handoffs_dir}"]}

    files = sorted(handoffs_dir.glob("*.md"))
    if not files:
        errors.append(f"{handoffs_dir}: no handoff files")
    errors.extend(validate_structure(run_dir, files))
    errors.extend(validate_sequence(files))
    for path in files:
        errors.extend(validate_file(path, run_dir.name))

    return {"run": str(run_dir), "handoffs": len(files), "passed": not errors, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MAW handoff markdown.")
    parser.add_argument("run")
    args = parser.parse_args(argv)
    result = validate_run(Path(args.run))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
