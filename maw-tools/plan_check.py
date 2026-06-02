#!/usr/bin/env python3
"""Deterministic pre-execution plan gate for MAW conductor plans."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import registry


REGISTRY = registry.load_registry()
CORE_ROLES = REGISTRY["core_roles"]
KNOWN_ROLES = REGISTRY["known_roles"]
ROLE_ALIASES = REGISTRY["role_aliases"]
TASK_TYPE_ALIASES = REGISTRY["task_type_aliases"]
REQUIRED_ROLE_RULES = REGISTRY["required_role_rules"]
TASK_TYPE_CAPS = REGISTRY["task_type_caps"]
DEFAULT_CAPS = REGISTRY["default_caps"]


def canonical_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def canonical_task_type(task_type: str) -> str:
    return TASK_TYPE_ALIASES.get(task_type, task_type)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def load_plan(path: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        if path:
            text = Path(path).read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [{"type": "invalid_json", "message": str(exc)}]
    except OSError as exc:
        return None, [{"type": "read_error", "message": str(exc)}]
    if not isinstance(data, dict):
        return None, [{"type": "invalid_plan", "message": "plan must be a JSON object"}]
    return data, []


def normalize_caps(caps: Any) -> dict[str, int]:
    result = dict(DEFAULT_CAPS)
    if isinstance(caps, dict):
        for key in ("max_agents", "max_parallel"):
            value = caps.get(key)
            if isinstance(value, int):
                result[key] = value
    return result


def role_justified(role: str, justifications: Any) -> bool:
    if not isinstance(justifications, dict):
        return False
    value = justifications.get(role, "")
    return isinstance(value, str) and bool(value.strip())


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    raw_task_type = str(plan.get("task_type", "")).strip().lower()
    task_type = canonical_task_type(raw_task_type)
    raw_roles = [str(role) for role in as_list(plan.get("roles"))]
    roles = [canonical_role(role) for role in raw_roles]
    caps = normalize_caps(plan.get("caps"))
    parallel_roles = [canonical_role(str(role)) for role in as_list(plan.get("parallel_roles"))]
    required_roles = REQUIRED_ROLE_RULES.get(task_type, [])
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not raw_task_type:
        warnings.append({"type": "missing_task_type", "message": "task_type is missing or empty"})
    elif task_type not in REQUIRED_ROLE_RULES:
        warnings.append({"type": "unknown_task_type", "message": f"no required-role rule for task_type: {raw_task_type}"})

    for raw, role in zip(raw_roles, roles):
        if role not in KNOWN_ROLES:
            violations.append(violation("unknown_role", f"unknown role: {raw}", role=raw))

    seen: set[str] = set()
    duplicates: set[str] = set()
    for role in roles:
        if role in seen:
            duplicates.add(role)
        seen.add(role)
    for role in sorted(duplicates):
        violations.append(violation("duplicate_role", f"duplicate role: {role}", role=role))

    if "acceptance_gate" not in roles:
        violations.append(violation("missing_acceptance_gate", "acceptance_gate is required", role="acceptance_gate"))

    for role in sorted(CORE_ROLES):
        if role not in roles:
            violations.append(violation("missing_core_role", f"core role is required: {role}", role=role))

    for role in required_roles:
        if role not in roles:
            violations.append(violation("missing_required_role", f"{task_type} requires {role}", role=role, task_type=task_type))

    minimum_required_roles = sorted(CORE_ROLES | set(required_roles))
    required_role_count = len(minimum_required_roles)
    if required_role_count > caps["max_agents"]:
        violations.append(
            violation(
                "insufficient_role_cap_for_required_roles",
                f"{task_type or 'task'} requires {required_role_count} core/required roles but max_agents is {caps['max_agents']}; raise max_agents to at least {required_role_count}",
                required_role_count=required_role_count,
                max_agents=caps["max_agents"],
                missing_headroom=required_role_count - caps["max_agents"],
                suggested_cap=required_role_count,
                required_roles=minimum_required_roles,
            )
        )

    if len(roles) > caps["max_agents"]:
        violations.append(
            violation("role_cap_exceeded", f"role count {len(roles)} exceeds max_agents {caps['max_agents']}", actual=len(roles), limit=caps["max_agents"])
        )

    if len(parallel_roles) > caps["max_parallel"]:
        violations.append(
            violation(
                "parallel_cap_exceeded",
                f"parallel role count {len(parallel_roles)} exceeds max_parallel {caps['max_parallel']}",
                actual=len(parallel_roles),
                limit=caps["max_parallel"],
            )
        )

    justified_required = set(required_roles) | CORE_ROLES | {"plan_reviewer"}
    for role in roles:
        if role in KNOWN_ROLES and role not in justified_required and not role_justified(role, plan.get("role_justifications")):
            violations.append(violation("unjustified_role", f"optional/specialized role lacks justification: {role}", role=role))

    alias_notes = [{"requested": key, "used": value} for key, value in sorted(ROLE_ALIASES.items())]
    summary = {
        "role_count": len(roles),
        "parallel_count": len(parallel_roles),
        "violation_count": len(violations),
        "warning_count": len(warnings),
        "role_aliases": alias_notes,
        "required_role_count": required_role_count,
    }
    return {
        "passed": not violations,
        "task_type": task_type,
        "raw_task_type": raw_task_type,
        "roles": roles,
        "violations": violations,
        "warnings": warnings,
        "required_roles": required_roles,
        "caps": caps,
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a structured MAW conductor plan before execution.")
    parser.add_argument("--file", help="JSON conductor plan file; reads stdin when omitted")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan, load_errors = load_plan(args.file)
    if plan is None:
        result = {
            "passed": False,
            "task_type": "",
            "roles": [],
            "violations": load_errors,
            "warnings": [],
            "required_roles": [],
            "caps": DEFAULT_CAPS,
            "summary": {"role_count": 0, "parallel_count": 0, "violation_count": len(load_errors), "warning_count": 0, "role_aliases": []},
        }
    else:
        result = validate_plan(plan)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
