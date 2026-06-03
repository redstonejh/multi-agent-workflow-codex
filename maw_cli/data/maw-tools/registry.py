#!/usr/bin/env python3
"""Load MAW capability-pack manifests into core lookup tables."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_packs_dir() -> Path:
    return repo_root() / "packs"


def load_manifest(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a JSON object: {path}")
    return data


def discover_manifest_paths(packs_dir: str | Path | None = None) -> list[Path]:
    root = Path(packs_dir) if packs_dir is not None else default_packs_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("*/manifest.json"))


def load_manifests(packs_dir: str | Path | None = None) -> list[dict[str, Any]]:
    return [load_manifest(path) for path in discover_manifest_paths(packs_dir)]


def as_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field} items must be non-empty strings")
        result.append(item)
    return result


def as_string_map(value: Any, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str) or not key or not item:
            raise ValueError(f"{field} entries must map non-empty strings to non-empty strings")
        result[key] = item
    return result


def as_caps(value: Any, field: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    result: dict[str, int] = {}
    for key in ("max_agents", "max_parallel", "max_iters"):
        item = value.get(key)
        if item is None:
            continue
        if not isinstance(item, int):
            raise ValueError(f"{field}.{key} must be an integer")
        result[key] = item
    for key in ("max_agents", "max_parallel"):
        if key not in result:
            raise ValueError(f"{field}.{key} is required")
    return result


def required_roles_by_task(manifest: dict[str, Any]) -> dict[str, list[str]]:
    required = manifest.get("required_roles", [])
    if isinstance(required, list):
        roles = as_string_list(required, "required_roles")
        return {task_type: list(roles) for task_type in as_string_list(manifest.get("task_types", []), "task_types")}
    if isinstance(required, dict):
        result: dict[str, list[str]] = {}
        for task_type, roles in required.items():
            if not isinstance(task_type, str) or not task_type:
                raise ValueError("required_roles task type keys must be non-empty strings")
            result[task_type] = as_string_list(roles, f"required_roles.{task_type}")
        return result
    raise ValueError("required_roles must be a list or object")


def required_evidence_by_task(manifest: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    evidence = manifest.get("required_evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("required_evidence must be a list")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise ValueError(f"required_evidence[{index}] must be an object")
        artifact = item.get("artifact")
        check = item.get("check")
        schema = item.get("schema")
        if not all(isinstance(value, str) and value for value in (artifact, check, schema)):
            raise ValueError(f"required_evidence[{index}] requires artifact, check, and schema strings")
        normalized.append({"artifact": artifact, "check": check, "schema": schema})
    return {task_type: list(normalized) for task_type in as_string_list(manifest.get("task_types", []), "task_types")}


def merge_manifests(manifests: list[dict[str, Any]]) -> dict[str, Any]:
    core_roles: set[str] = set()
    roles: set[str] = set()
    role_aliases: dict[str, str] = {}
    task_type_aliases: dict[str, str] = {}
    required_role_rules: dict[str, list[str]] = {}
    task_type_caps: dict[str, dict[str, int]] = {}
    required_evidence: dict[str, list[dict[str, str]]] = {}
    default_caps: dict[str, int] | None = None

    for manifest in manifests:
        manifest_id = manifest.get("id", "<unknown>")
        roles.update(as_string_list(manifest.get("roles", []), f"{manifest_id}.roles"))
        core_roles.update(as_string_list(manifest.get("core_roles", []), f"{manifest_id}.core_roles"))
        role_aliases.update(as_string_map(manifest.get("role_aliases", {}), f"{manifest_id}.role_aliases"))
        task_type_aliases.update(as_string_map(manifest.get("task_type_aliases", {}), f"{manifest_id}.task_type_aliases"))

        caps = as_caps(manifest.get("caps", {}), f"{manifest_id}.caps")
        if default_caps is None:
            default_caps = dict(caps)
        for task_type in as_string_list(manifest.get("task_types", []), f"{manifest_id}.task_types"):
            task_type_caps[task_type] = dict(caps)

        task_caps = manifest.get("task_type_caps", {})
        if task_caps is not None:
            if not isinstance(task_caps, dict):
                raise ValueError(f"{manifest_id}.task_type_caps must be an object")
            for task_type, value in task_caps.items():
                if not isinstance(task_type, str) or not task_type:
                    raise ValueError(f"{manifest_id}.task_type_caps keys must be non-empty strings")
                task_type_caps[task_type] = as_caps(value, f"{manifest_id}.task_type_caps.{task_type}")

        required_role_rules.update(required_roles_by_task(manifest))
        required_evidence.update(required_evidence_by_task(manifest))

    return {
        "core_roles": set(core_roles),
        "known_roles": set(roles) | set(core_roles),
        "role_aliases": dict(role_aliases),
        "task_type_aliases": dict(task_type_aliases),
        "required_role_rules": {key: list(value) for key, value in required_role_rules.items()},
        "task_type_caps": {key: dict(value) for key, value in task_type_caps.items()},
        "default_caps": dict(default_caps or {"max_agents": 5, "max_parallel": 3}),
        "required_evidence": {key: list(value) for key, value in required_evidence.items()},
    }


def load_registry(packs_dir: str | Path | None = None) -> dict[str, Any]:
    return merge_manifests(load_manifests(packs_dir))
