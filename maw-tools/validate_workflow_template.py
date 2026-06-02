#!/usr/bin/env python3
"""Validate MAW workflow templates and run conformance."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "id",
    "name",
    "description",
    "caps",
    "agents",
    "handoffs",
    "required_artifacts",
    "acceptance_gates",
    "deterministic_checks",
}
HANDOFF_RE = re.compile(r"^[0-9]{2}_(?P<frm>[a-zA-Z0-9_-]+)__to__(?P<to>[a-zA-Z0-9_-]+)\.md$")
TEMPLATE_RE = re.compile(r"^- Workflow template:\s*(?P<id>[a-zA-Z0-9_-]+)\s*$", re.MULTILINE)


def load_json(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path}: template must be a JSON object"]
    return data, []


def validate_template(path: Path) -> list[str]:
    data, errors = load_json(path)
    if data is None:
        return errors

    missing = sorted(REQUIRED_FIELDS - set(data))
    if missing:
        errors.append(f"{path}: missing required fields: {', '.join(missing)}")

    template_id = data.get("id")
    if not isinstance(template_id, str) or not template_id:
        errors.append(f"{path}: id must be a non-empty string")
    elif template_id != path.stem:
        errors.append(f"{path}: id must match filename stem")

    for field in ("name", "description"):
        if field in data and (not isinstance(data[field], str) or not data[field]):
            errors.append(f"{path}: {field} must be a non-empty string")

    agents = data.get("agents")
    if not isinstance(agents, list) or not agents or not all(isinstance(agent, str) and agent for agent in agents):
        errors.append(f"{path}: agents must be a non-empty list of strings")

    caps = data.get("caps")
    if not isinstance(caps, dict):
        errors.append(f"{path}: caps must be an object with max_agents and max_parallel")
    else:
        max_agents = caps.get("max_agents")
        max_parallel = caps.get("max_parallel")
        if not isinstance(max_agents, int) or max_agents < 1:
            errors.append(f"{path}: caps.max_agents must be a positive integer")
        if not isinstance(max_parallel, int) or max_parallel < 1:
            errors.append(f"{path}: caps.max_parallel must be a positive integer")
        if isinstance(max_agents, int) and isinstance(agents, list) and max_agents < len(agents):
            errors.append(f"{path}: caps.max_agents {max_agents} is smaller than agent roster size {len(agents)}")
        if isinstance(max_agents, int) and isinstance(max_parallel, int) and max_parallel > max_agents:
            errors.append(f"{path}: caps.max_parallel cannot exceed caps.max_agents")

    handoffs = data.get("handoffs")
    if not isinstance(handoffs, list) or not handoffs:
        errors.append(f"{path}: handoffs must be a non-empty list")
    else:
        for index, handoff in enumerate(handoffs):
            if not isinstance(handoff, dict):
                errors.append(f"{path}: handoffs[{index}] must be an object")
                continue
            if not isinstance(handoff.get("from"), str) or not handoff.get("from"):
                errors.append(f"{path}: handoffs[{index}].from must be a non-empty string")
            if not isinstance(handoff.get("to"), str) or not handoff.get("to"):
                errors.append(f"{path}: handoffs[{index}].to must be a non-empty string")

    for field in ("required_artifacts", "acceptance_gates", "deterministic_checks"):
        value = data.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"{path}: {field} must be a non-empty list")

    checks = data.get("deterministic_checks", [])
    if isinstance(checks, list):
        for index, check in enumerate(checks):
            if not isinstance(check, dict):
                errors.append(f"{path}: deterministic_checks[{index}] must be an object")
                continue
            if not isinstance(check.get("name"), str) or not check.get("name"):
                errors.append(f"{path}: deterministic_checks[{index}].name must be a non-empty string")
            if not isinstance(check.get("command"), str) or not check.get("command"):
                errors.append(f"{path}: deterministic_checks[{index}].command must be a non-empty string")

    return errors


def template_dir(root: Path) -> Path:
    return root / "templates" / "workflows"


def load_template(root: Path, template_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    path = template_dir(root) / f"{template_id}.json"
    if not path.is_file():
        return None, [f"template not found: {path}"]
    schema_errors = validate_template(path)
    if schema_errors:
        return None, schema_errors
    return load_json(path)


def declared_template(run_dir: Path) -> tuple[str | None, list[str]]:
    run_md = run_dir / "run.md"
    if not run_md.is_file():
        return None, [f"missing run.md: {run_md}"]
    text = run_md.read_text(encoding="utf-8")
    match = TEMPLATE_RE.search(text)
    if not match:
        return None, [f"{run_md}: missing '- Workflow template: <template_id>' declaration"]
    return match.group("id"), []


def handoff_pairs(run_dir: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for path in (run_dir / "handoffs").glob("*.md"):
        match = HANDOFF_RE.match(path.name)
        if match:
            pairs.add((match.group("frm"), match.group("to")))
    return pairs


def validate_run(root: Path, run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not run_dir.is_dir():
        return {"run": str(run_dir), "passed": False, "errors": [f"not a directory: {run_dir}"]}

    template_id, declaration_errors = declared_template(run_dir)
    errors.extend(declaration_errors)
    if template_id is None:
        return {"run": str(run_dir), "passed": False, "errors": errors}

    template, template_errors = load_template(root, template_id)
    errors.extend(template_errors)
    if template is None:
        return {"run": str(run_dir), "template": template_id, "passed": False, "errors": errors}

    for agent in template["agents"]:
        if not (run_dir / "agents" / f"{agent}.md").is_file():
            errors.append(f"missing agent notes for template agent: {agent}")

    actual_pairs = handoff_pairs(run_dir)
    for handoff in template["handoffs"]:
        pair = (handoff["from"], handoff["to"])
        if pair not in actual_pairs:
            errors.append(f"missing handoff pair: {pair[0]} -> {pair[1]}")

    for artifact in template["required_artifacts"]:
        if not (run_dir / artifact).is_file():
            errors.append(f"missing required artifact: {artifact}")

    return {
        "run": str(run_dir),
        "template": template_id,
        "passed": not errors,
        "errors": errors,
    }


def validate_all_templates(root: Path) -> dict[str, Any]:
    workflows = template_dir(root)
    errors: list[str] = []
    files = sorted(workflows.glob("*.json"))
    if not files:
        errors.append(f"no workflow templates found in {workflows}")
    for path in files:
        errors.extend(validate_template(path))
    return {"templates": len(files), "passed": not errors, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MAW workflow templates and run conformance.")
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--run", help="run folder to validate against its declared template")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.run:
        result = validate_run(root, Path(args.run))
    else:
        result = validate_all_templates(root)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
