#!/usr/bin/env python3
"""Validate that a MAW run used real delegated role sub-agents."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROOF_ARTIFACT = "artifacts/delegation-proof.json"


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def proof_path(run_dir: Path) -> Path:
    return run_dir / PROOF_ARTIFACT


def _role_entries(data: dict[str, Any]) -> dict[str, Any]:
    roles = data.get("roles")
    if isinstance(roles, dict):
        return roles
    if isinstance(roles, list):
        entries: dict[str, Any] = {}
        for item in roles:
            if isinstance(item, dict) and isinstance(item.get("role"), str):
                entries[item["role"]] = item
        return entries
    return {}


def _selected_roles(data: dict[str, Any], entries: dict[str, Any]) -> list[str]:
    selected = data.get("selected_roles")
    if isinstance(selected, list):
        return [str(role) for role in selected if str(role).strip()]

    fallback = data.get("roles_selected")
    if isinstance(fallback, list):
        return [str(role) for role in fallback if str(role).strip()]

    return list(entries)


def _agent_id(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    for key in ("agent_id", "session_id", "context_id", "subagent_id"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _prompt_path(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    value = entry.get("role_prompt_path") or entry.get("prompt_path")
    return value.strip() if isinstance(value, str) else ""


def validate_proof(data: Any) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    if not isinstance(data, dict):
        return {
            "check": "delegation_proof",
            "passed": False,
            "violations": [violation("invalid_delegation_proof", "delegation proof must be a JSON object")],
        }

    capability = data.get("delegation_capability") or data.get("capability")
    if not isinstance(capability, dict) or capability.get("available") is not True:
        violations.append(
            violation(
                "delegation_capability_unavailable",
                "delegation proof must record an available sub-agent/delegation capability",
            )
        )
    primitive = capability.get("primitive") if isinstance(capability, dict) else None
    if not isinstance(primitive, str) or not primitive.strip():
        violations.append(
            violation(
                "missing_delegation_primitive",
                "delegation proof must name the runtime delegation primitive",
            )
        )

    entries = _role_entries(data)
    selected = _selected_roles(data, entries)
    if not selected:
        violations.append(violation("missing_selected_roles", "delegation proof must list selected roles"))

    ids: dict[str, str] = {}
    for role in selected:
        entry = entries.get(role)
        if not isinstance(entry, dict):
            violations.append(violation("missing_role_delegation", f"missing delegation entry for role: {role}", role=role))
            continue

        agent_id = _agent_id(entry)
        if not agent_id:
            violations.append(violation("missing_role_agent_id", f"missing independent sub-agent/session id for role: {role}", role=role))
        else:
            ids[role] = agent_id

        prompt_path = _prompt_path(entry)
        expected = f".codex/agents/{role}.md"
        if prompt_path.replace("\\", "/") != expected:
            violations.append(
                violation(
                    "invalid_role_prompt_path",
                    f"delegation entry for role {role} must reference {expected}",
                    role=role,
                    prompt_path=prompt_path,
                    expected=expected,
                )
            )

    if len(selected) > 1 and len(set(ids.values())) <= 1:
        violations.append(
            violation(
                "shared_agent_context",
                "selected roles must not all share one sub-agent/session id",
                selected_roles=selected,
            )
        )
    if len(ids) != len(set(ids.values())):
        duplicate_ids = sorted({agent_id for agent_id in ids.values() if list(ids.values()).count(agent_id) > 1})
        violations.append(
            violation(
                "duplicate_agent_context",
                "each selected role must have a distinct sub-agent/session id",
                duplicate_agent_ids=duplicate_ids,
            )
        )

    return {
        "check": "delegation_proof",
        "schema_version": 1,
        "selected_roles": selected,
        "role_count": len(selected),
        "passed": not violations,
        "violations": violations,
    }


def check_run(run_dir: Path) -> dict[str, Any]:
    path = proof_path(run_dir)
    if not path.is_file():
        return {
            "check": "delegation_proof",
            "schema_version": 1,
            "artifact": str(path),
            "passed": False,
            "violations": [
                violation(
                    "missing_delegation_proof",
                    f"missing required delegation proof artifact: {PROOF_ARTIFACT}",
                    artifact=PROOF_ARTIFACT,
                )
            ],
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "check": "delegation_proof",
            "schema_version": 1,
            "artifact": str(path),
            "passed": False,
            "violations": [violation("invalid_delegation_proof_json", "delegation proof is not valid JSON", error=str(exc))],
        }
    result = validate_proof(data)
    result["artifact"] = str(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate MAW role delegation proof.")
    parser.add_argument("run_dir")
    args = parser.parse_args(argv)
    result = check_run(Path(args.run_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
