#!/usr/bin/env python3
"""Validate task-type risk checklist coverage and deterministic artifact links."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import acceptance_check


REQUIRED_CHECKLISTS = ("refactor", "salvage", "ml", "frontend", "debugging", "code", "generic")
ARTIFACT_RE = re.compile(r"`(?P<artifact>artifacts/[A-Za-z0-9_.\-/]+)`")
EVIDENCE_RE = re.compile(r"Evidence:\s*(?P<value>.+)$")
ADVISORY = "advisory critic-only"


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def template_artifacts(root: Path) -> set[str]:
    artifacts: set[str] = set()
    for path in (root / "templates" / "workflows").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for artifact in data.get("required_artifacts", []):
            if isinstance(artifact, str):
                artifacts.add(artifact)
    return artifacts


def known_artifacts(root: Path) -> set[str]:
    artifacts = set(template_artifacts(root))
    for values in acceptance_check.REQUIRED_EVIDENCE.values():
        artifacts.update(values)
    return artifacts


def checklist_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("- "):
            lines.append((index, stripped))
    return lines


def validate_checklist(path: Path, known: set[str]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    entries = checklist_lines(path)
    if not entries:
        violations.append(violation("empty_checklist", "checklist has no invariant entries", checklist=str(path)))
        return violations

    for line_number, line in entries:
        evidence = EVIDENCE_RE.search(line)
        if not evidence:
            violations.append(
                violation(
                    "missing_evidence_marker",
                    "checklist invariant is missing an Evidence marker",
                    checklist=str(path),
                    line=line_number,
                    text=line,
                )
            )
            continue

        value = evidence.group("value")
        if ADVISORY in value:
            continue

        artifacts = ARTIFACT_RE.findall(value)
        if not artifacts:
            violations.append(
                violation(
                    "missing_deterministic_artifact",
                    "deterministic checklist item must reference artifacts/<name>",
                    checklist=str(path),
                    line=line_number,
                    text=line,
                )
            )
            continue

        for artifact in artifacts:
            if artifact not in known:
                violations.append(
                    violation(
                        "unknown_deterministic_artifact",
                        f"deterministic artifact is not known to any evidence map or workflow template: {artifact}",
                        checklist=str(path),
                        line=line_number,
                        artifact=artifact,
                    )
                )
    return violations


def validate(root: Path) -> dict[str, Any]:
    checklist_dir = root / ".codex" / "checklists"
    known = known_artifacts(root)
    violations: list[dict[str, Any]] = []
    checklists: dict[str, str] = {}

    for name in REQUIRED_CHECKLISTS:
        path = checklist_dir / f"{name}.md"
        checklists[name] = str(path)
        if not path.is_file():
            violations.append(violation("missing_checklist", f"missing checklist for task type: {name}", task_type=name, path=str(path)))
            continue
        violations.extend(validate_checklist(path, known))

    return {
        "check": "task_type_checklists",
        "passed": not violations,
        "checklists": checklists,
        "known_artifact_count": len(known),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MAW task-type risk checklist links.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    result = validate(Path(args.root))
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
