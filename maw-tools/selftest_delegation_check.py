#!/usr/bin/env python3
"""Self-tests for delegation_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
DELEGATION_CHECK = TOOLS / "delegation_check.py"


def write_proof(run_dir: Path, agent_ids: dict[str, str]) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    roles = {
        role: {
            "agent_id": agent_id,
            "role_prompt_path": f".codex/agents/{role}.md",
        }
        for role, agent_id in agent_ids.items()
    }
    (artifacts / "delegation-proof.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "delegation_capability": {"available": True, "primitive": "selftest.spawn"},
                "selected_roles": list(agent_ids),
                "roles": roles,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_check(run_dir: Path) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(DELEGATION_CHECK), str(run_dir)], capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def main() -> int:
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        missing = root / "missing"
        missing.mkdir()
        code, data = run_check(missing)
        results.append({"name": "missing_proof_fails", "passed": code != 0 and data["passed"] is False})

        shared = root / "shared"
        write_proof(shared, {"conductor": "agent-1", "planner": "agent-1"})
        code, data = run_check(shared)
        results.append({"name": "shared_context_fails", "passed": code != 0 and data["passed"] is False})

        good = root / "good"
        write_proof(good, {"conductor": "agent-1", "planner": "agent-2", "worker": "agent-3"})
        code, data = run_check(good)
        results.append({"name": "distinct_contexts_pass", "passed": code == 0 and data["passed"] is True})

    passed = all(item["passed"] for item in results)
    print(json.dumps({"check": "selftest_delegation_check", "passed": passed, "results": results}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
