#!/usr/bin/env python3
"""Self-tests for curated MAW run research archives."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import archive_run


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_target_repo(path: Path) -> str:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "maw@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "MAW Test"], cwd=path, check=True)
    write(path / "target.txt", "target code\n")
    subprocess.run(["git", "add", "target.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=path, check=True, capture_output=True, text=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        run = tmp / "runs" / "2026-01-01_fixture"
        artifacts = run / "artifacts"
        target = tmp / "target"
        target.mkdir()
        target_commit = make_target_repo(target)

        write(run / "run.md", "Final verdict: SHIP\n")
        write(run / "memory.md", "token=abc123 should be redacted\n")
        write(run / "handoffs" / "01_planner__to__worker.md", "# handoff\n")
        write(artifacts / "conductor-plan.json", '{"task_type":"salvage"}\n')
        write(artifacts / "workflow-template.json", '{"name":"salvage-task"}\n')
        write(artifacts / "acceptance-result.json", '{"verdict":"SHIP"}\n')
        write(artifacts / "preserve-parity.json", '{"diff_count":0,"passed":true}\n')
        write(artifacts / "interaction-current-drag.json", '{"diff_count":0}\n')
        write(artifacts / "unselected-large.json", '{"copy":false}\n')
        write(artifacts / "code-graph.json", '{"graph":"' + ("x" * 2048) + '"}\n')
        write(run / "work" / "target-repo" / "foreign.js", "do not copy\n")

        result = archive_run.archive_run(run, archive_root=tmp / "research-archive", target_repo=target, maw_commit="abcmaw")
        archive_dir = Path(result["archive_dir"])
        manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
        root_manifest = json.loads((archive_dir.parent / "manifest.json").read_text(encoding="utf-8"))
        archived_paths = {entry["path"] for entry in manifest["files"]}
        stubs = {entry["path"]: entry for entry in manifest["excluded_stubs"]}

        checks = {
            "result_passed": result["passed"] is True,
            "selected_file_copied": "artifacts/preserve-parity.json" in archived_paths,
            "interaction_file_copied": "artifacts/interaction-current-drag.json" in archived_paths,
            "handoff_copied": "handoffs/01_planner__to__worker.md" in archived_paths,
            "unselected_artifact_not_copied": not (archive_dir / "artifacts" / "unselected-large.json").exists(),
            "code_graph_hash_only": "artifacts/code-graph.json" in stubs and not (archive_dir / "artifacts" / "code-graph.json").exists(),
            "target_commit_only": stubs.get("work/target-repo", {}).get("target_commit") == target_commit,
            "work_clone_not_copied": not (archive_dir / "work").exists(),
            "secret_redacted": "<REDACTED>" in (archive_dir / "memory.md").read_text(encoding="utf-8"),
            "executor_commits_recorded": manifest["executor_commits"] == {"maw": "abcmaw", "target": target_commit},
            "root_manifest_written": root_manifest["run_count"] == 1 and root_manifest["runs"][0]["run_id"] == run.name,
            "root_incident_index_written": (archive_dir.parent / "incident-index.md").is_file(),
        }
        for name, passed in checks.items():
            results.append({"name": name, "passed": bool(passed)})

    passed = all(item["passed"] for item in results)
    print(json.dumps({"passed": passed, "assertions": len(results), "ok": sum(1 for item in results if item["passed"]), "results": results}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
