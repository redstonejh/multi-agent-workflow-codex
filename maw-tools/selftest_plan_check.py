#!/usr/bin/env python3
"""Self-test the MAW pre-execution plan gate."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


PLAN_CHECK = Path(__file__).with_name("plan_check.py")


def run_plan(plan: dict) -> tuple[int, dict, str, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        path = handle.name
    try:
        proc = subprocess.run([sys.executable, str(PLAN_CHECK), "--file", path], capture_output=True, text=True)
        return proc.returncode, json.loads(proc.stdout), proc.stdout, proc.stderr
    finally:
        Path(path).unlink(missing_ok=True)


def base_plan(task_type: str, roles: list[str], max_agents: int = 8, max_parallel: int = 3) -> dict:
    return {
        "task_type": task_type,
        "roles": roles,
        "parallel_roles": ["planner", "worker"],
        "caps": {"max_agents": max_agents, "max_parallel": max_parallel},
        "role_justifications": {"dependency_mapper": "Map hidden coupling before code changes."},
    }


def has_violation(data: dict, kind: str) -> bool:
    return any(item.get("type") == kind for item in data["violations"])


def main() -> int:
    cases = [
        (
            "default_generic_core_green",
            {
                "task_type": "generic",
                "roles": ["conductor", "planner", "worker", "critic", "acceptance_gate"],
            },
            True,
            None,
        ),
        (
            "ml_default_cap_insufficient_red",
            {
                "task_type": "ml",
                "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
            },
            False,
            "insufficient_role_cap_for_required_roles",
        ),
        (
            "missing_ml_validator_red",
            base_plan("ml", ["conductor", "planner", "worker", "baseline_enforcer", "critic", "acceptance_gate"]),
            False,
            "missing_required_role",
        ),
        (
            "corrected_ml_green",
            base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"]),
            True,
            None,
        ),
        (
            "frontend_default_cap_insufficient_red",
            {
                "task_type": "frontend",
                "roles": ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "critic", "acceptance_gate"],
            },
            False,
            "insufficient_role_cap_for_required_roles",
        ),
        (
            "required_role_rules_fire",
            base_plan("frontend", ["conductor", "planner", "worker", "a11y_auditor", "critic", "acceptance_gate"]),
            False,
            "missing_required_role",
        ),
        (
            "duplicate_roles_fail",
            base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "critic", "acceptance_gate"]),
            False,
            "duplicate_role",
        ),
        (
            "unknown_roles_fail",
            base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "mystery_agent", "acceptance_gate"]),
            False,
            "unknown_role",
        ),
        (
            "missing_acceptance_gate_fails",
            base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic"]),
            False,
            "missing_acceptance_gate",
        ),
        (
            "missing_core_role_fails",
            base_plan("ml", ["conductor", "planner", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"]),
            False,
            "missing_core_role",
        ),
        (
            "role_caps_enforced",
            base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"], max_agents=3),
            False,
            "role_cap_exceeded",
        ),
        (
            "parallel_caps_enforced",
            {
                **base_plan("ml", ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"], max_parallel=1),
                "parallel_roles": ["planner", "leakage_auditor"],
            },
            False,
            "parallel_cap_exceeded",
        ),
        (
            "frontend_required_roles_enforced",
            base_plan("frontend", ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "critic", "acceptance_gate"]),
            True,
            None,
        ),
        (
            "code_required_roles_enforced",
            base_plan("code", ["conductor", "planner", "worker", "critic", "dependency_mapper", "acceptance_gate"], max_agents=6),
            True,
            None,
        ),
        (
            "unjustified_optional_role_fails",
            {
                "task_type": "frontend",
                "roles": ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "ux_critic", "critic", "acceptance_gate"],
                "caps": {"max_agents": 8, "max_parallel": 3},
            },
            False,
            "unjustified_role",
        ),
    ]
    results: list[dict] = []
    for name, plan, expected_passed, expected_violation in cases:
        code, data, stdout, stderr = run_plan(plan)
        passed = data["passed"] is expected_passed and ((code == 0) is expected_passed)
        if expected_violation:
            passed = passed and has_violation(data, expected_violation)
        results.append(
            {
                "name": name,
                "passed": passed,
                "expected_passed": expected_passed,
                "expected_violation": expected_violation,
                "exit_code": code,
                "tool_passed": data["passed"],
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
            }
        )

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "assertions": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
