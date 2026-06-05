"""Export a curated, tamper-evident MAW run archive."""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_FILES = {"run.md", "memory.md"}
ARTIFACT_FILES = {
    "conductor-plan.json",
    "workflow-template.json",
    "salvage-result.json",
    "acceptance-result.json",
    "verdict-check-result.json",
    "salvage-resistance.json",
    "preserve-parity.json",
    "dead-code.json",
    "duplication.json",
    "stale-code.json",
    "test-triage.json",
    "hidden-deps.json",
    "interdependency-dossier.json",
}
ARTIFACT_GLOBS = ("interaction-current-*.json",)
HASH_ONLY_NAMES = {"code-graph.json", "code-graph-current.json"}
EXCLUDED_DIRS = {"work", "node_modules", "build", "dist", ".git"}
SECRET_NAME_RE = re.compile(r"(?i)(^|[._-])(env|secret|token|credential|credentials|key)([._-]|$)")
SECRET_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|credential|authorization|bearer)\s*[:=]\s*([^\s,;\"']+)"
)


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def repo_commit(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    value = proc.stdout.strip()
    return value or None


def default_archive_root(run_dir: Path) -> Path:
    runs_dir = run_dir.parent
    repo_root = runs_dir.parent if runs_dir.name == "runs" else Path.cwd()
    return repo_root.parent / "research-archive"


def rel_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def should_redact_path(path: Path) -> bool:
    return any(SECRET_NAME_RE.search(part) for part in path.parts)


def redact_text(text: str) -> tuple[str, int]:
    redactions = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal redactions
        redactions += 1
        return f"{match.group(1)}=<REDACTED>"

    return SECRET_VALUE_RE.sub(repl, text), redactions


def read_redacted_bytes(path: Path) -> tuple[bytes, int]:
    raw = path.read_bytes()
    if should_redact_path(path):
        return b"<REDACTED: secret-bearing path excluded from archive>\n", 1
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, 0
    redacted, count = redact_text(text)
    return redacted.encode("utf-8"), count


def write_redacted_copy(src: Path, dst: Path) -> dict[str, Any]:
    data, redactions = read_redacted_bytes(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return {
        "path": dst.as_posix(),
        "source_path": str(src),
        "size": len(data),
        "sha256": sha256_bytes(data),
        "redactions": redactions,
    }


def selected_files(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in sorted(ROOT_FILES):
        path = run_dir / name
        if path.is_file():
            files.append(path)
    artifacts = run_dir / "artifacts"
    for name in sorted(ARTIFACT_FILES):
        path = artifacts / name
        if path.is_file():
            files.append(path)
    for pattern in ARTIFACT_GLOBS:
        files.extend(sorted(artifacts.glob(pattern)))
    handoffs = run_dir / "handoffs"
    if handoffs.is_dir():
        files.extend(sorted(handoffs.glob("*.md")))
    return files


def hash_only_files(run_dir: Path) -> list[Path]:
    found: list[Path] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(run_dir).parts):
            continue
        if path.name in HASH_ONLY_NAMES:
            found.append(path)
    return sorted(found)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def nested_get(data: dict[str, Any], path: list[str]) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def metric_from_artifact(name: str, data: dict[str, Any]) -> str:
    if name == "preserve-parity.json":
        return f"diff_count={data.get('diff_count', 'unknown')}"
    if name == "salvage-result.json":
        return f"verdict={data.get('verdict', 'unknown')}, passed={data.get('passed', 'unknown')}"
    if name == "acceptance-result.json":
        return f"verdict={data.get('verdict', 'unknown')}"
    if name == "salvage-resistance.json":
        caught = nested_get(data, ["summary", "caught"]) or data.get("caught")
        planted = nested_get(data, ["summary", "planted"]) or data.get("planted")
        return f"caught={caught if caught is not None else 'unknown'}, planted={planted if planted is not None else 'unknown'}"
    if name == "dead-code.json":
        violations = data.get("violations")
        return f"violations={len(violations) if isinstance(violations, list) else 'unknown'}"
    if name == "duplication.json":
        return f"passed={data.get('passed', 'unknown')}"
    if name == "stale-code.json":
        return f"passed={data.get('passed', 'unknown')}"
    if name == "test-triage.json":
        active = data.get("active_tests") or data.get("active") or nested_get(data, ["summary", "active"])
        scrapped = data.get("scrapped_tests") or data.get("scrapped") or nested_get(data, ["summary", "scrapped"])
        return f"active={active if active is not None else 'unknown'}, scrapped={scrapped if scrapped is not None else 'unknown'}"
    if name == "hidden-deps.json":
        return f"passed={data.get('passed', 'unknown')}"
    if name == "interdependency-dossier.json":
        count = data.get("count") or nested_get(data, ["summary", "count"])
        return f"couplings={count if count is not None else 'unknown'}"
    if name.startswith("interaction-current-"):
        return f"diff_count={data.get('diff_count', 'unknown')}"
    return "archived"


def taxonomy_for(name: str) -> str:
    if name.startswith("interaction-current-") or name == "preserve-parity.json":
        return "behavior-parity"
    if name in {"salvage-result.json", "acceptance-result.json", "verdict-check-result.json"}:
        return "verdict-gate"
    if name == "salvage-resistance.json":
        return "resistance"
    if name in {"dead-code.json", "duplication.json", "stale-code.json"}:
        return "static-cleanliness"
    if name == "test-triage.json":
        return "test-triage"
    if name in {"hidden-deps.json", "interdependency-dossier.json"}:
        return "dependency-proof"
    if name in {"conductor-plan.json", "workflow-template.json"}:
        return "workflow-plan"
    return "logbook"


def write_incident_index(archive_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Migration Run Incident Index",
        "",
        f"Capture timestamp: `{manifest['capture_timestamp']}`",
        "",
        "| Run | Taxonomy | Evidence | Key Metric | Executor Commits |",
        "|---|---|---|---|---|",
    ]
    commits = manifest.get("executor_commits", {})
    commit_text = ", ".join(f"{k}={v}" for k, v in commits.items() if v) or "unknown"
    for entry in manifest["files"]:
        name = Path(entry["path"]).name
        taxonomy = taxonomy_for(name)
        metric = entry.get("metric") or "archived"
        lines.append(f"| `{manifest['run_id']}` | {taxonomy} | `{entry['path']}` | {metric} | {commit_text} |")
    for stub in manifest["excluded_stubs"]:
        if "size" in stub and "sha256" in stub:
            metric = f"size={stub['size']}, sha256={stub['sha256']}"
        elif stub.get("target_commit"):
            metric = f"target_commit={stub['target_commit']}"
        else:
            metric = stub.get("reason", "excluded")
        lines.append(
            f"| `{manifest['run_id']}` | hash-only-exclusion | `{stub['path']}` | {metric} | {commit_text} |"
        )
    (archive_dir / "incident-index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive_root_index(archive_root: Path) -> None:
    manifests: list[dict[str, Any]] = []
    for path in sorted(archive_root.glob("*/manifest.json")):
        data = load_json(path)
        if data:
            data["_archive_manifest"] = path.relative_to(archive_root).as_posix()
            manifests.append(data)
    lines = [
        "# Research Archive Incident Index",
        "",
        "| Run | Taxonomy | Evidence | Key Metric | Executor Commits |",
        "|---|---|---|---|---|",
    ]
    for manifest in manifests:
        run_id = manifest.get("run_id", "unknown")
        commits = manifest.get("executor_commits", {})
        commit_text = ", ".join(f"{k}={v}" for k, v in commits.items() if v) or "unknown"
        run_prefix = Path(manifest["_archive_manifest"]).parent.as_posix()
        for entry in manifest.get("files", []):
            name = Path(entry.get("path", "")).name
            taxonomy = taxonomy_for(name)
            metric = entry.get("metric") or "archived"
            evidence = f"{run_prefix}/{entry.get('path', '')}"
            lines.append(f"| `{run_id}` | {taxonomy} | `{evidence}` | {metric} | {commit_text} |")
        for stub in manifest.get("excluded_stubs", []):
            if "size" in stub and "sha256" in stub:
                metric = f"size={stub['size']}, sha256={stub['sha256']}"
            elif stub.get("target_commit"):
                metric = f"target_commit={stub['target_commit']}"
            else:
                metric = stub.get("reason", "excluded")
            evidence = f"{run_prefix}/{stub.get('path', '')}"
            lines.append(f"| `{run_id}` | hash-only-exclusion | `{evidence}` | {metric} | {commit_text} |")
    (archive_root / "incident-index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_archive_root_manifest(archive_root: Path) -> Path:
    capture_timestamp = utc_now()
    runs: list[dict[str, Any]] = []
    for manifest_path in sorted(archive_root.glob("*/manifest.json")):
        manifest = load_json(manifest_path)
        if not manifest:
            continue
        run_dir = manifest_path.parent
        index_path = run_dir / "incident-index.md"
        run_entry = {
            "run_id": manifest.get("run_id", run_dir.name),
            "archive_path": run_dir.relative_to(archive_root).as_posix(),
            "manifest": {
                "path": manifest_path.relative_to(archive_root).as_posix(),
                "size": manifest_path.stat().st_size,
                "sha256": file_sha256(manifest_path),
            },
            "incident_index": {
                "path": index_path.relative_to(archive_root).as_posix(),
                "size": index_path.stat().st_size if index_path.is_file() else 0,
                "sha256": file_sha256(index_path) if index_path.is_file() else None,
            },
            "executor_commits": manifest.get("executor_commits", {}),
            "files_archived": len(manifest.get("files", [])),
            "excluded_stubs": len(manifest.get("excluded_stubs", [])),
        }
        runs.append(run_entry)
    root_index = archive_root / "incident-index.md"
    root_manifest = {
        "schema_version": 1,
        "capture_timestamp": capture_timestamp,
        "archive_root": str(archive_root),
        "run_count": len(runs),
        "runs": runs,
        "incident_index": {
            "path": root_index.name,
            "size": root_index.stat().st_size if root_index.is_file() else 0,
            "sha256": file_sha256(root_index) if root_index.is_file() else None,
        },
    }
    path = archive_root / "manifest.json"
    path.write_text(json.dumps(root_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def archive_run(
    run_dir: Path,
    archive_root: Path | None = None,
    target_repo: Path | None = None,
    maw_commit: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run folder not found: {run_dir}")
    archive_root = (archive_root or default_archive_root(run_dir)).resolve()
    archive_dir = archive_root / run_dir.name
    if archive_dir.exists():
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    capture_timestamp = utc_now()
    repo_root = run_dir.parent.parent if run_dir.parent.name == "runs" else Path.cwd()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "source_run_dir": str(run_dir),
        "capture_timestamp": capture_timestamp,
        "executor_commits": {
            "maw": maw_commit or os.environ.get("MAW_EXECUTOR_COMMIT") or repo_commit(repo_root),
            "target": repo_commit(target_repo.resolve()) if target_repo else None,
        },
        "files": [],
        "excluded_stubs": [],
    }
    copied_sources: set[Path] = set()
    for src in selected_files(run_dir):
        rel = rel_posix(src, run_dir)
        dst = archive_dir / rel
        entry = write_redacted_copy(src, dst)
        entry["path"] = rel
        if src.suffix == ".json":
            entry["metric"] = metric_from_artifact(src.name, load_json(dst))
        manifest["files"].append(entry)
        copied_sources.add(src.resolve())
    for src in hash_only_files(run_dir):
        resolved = src.resolve()
        if resolved in copied_sources:
            continue
        rel = rel_posix(src, run_dir)
        manifest["excluded_stubs"].append(
            {
                "path": rel,
                "source_path": str(src),
                "size": src.stat().st_size,
                "sha256": file_sha256(src),
                "reason": "hash-only large graph artifact",
            }
        )
    if target_repo:
        manifest["excluded_stubs"].append(
            {
                "path": "work/target-repo",
                "source_path": str(target_repo.resolve()),
                "target_commit": manifest["executor_commits"]["target"],
                "reason": "foreign target repository excluded; commit hash recorded only",
            }
        )
    manifest_path = archive_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = file_sha256(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_incident_index(archive_dir, manifest)
    write_archive_root_index(archive_root)
    root_manifest_path = write_archive_root_manifest(archive_root)
    return {
        "check": "research_archive_export",
        "schema_version": 1,
        "passed": True,
        "run": str(run_dir),
        "archive_dir": str(archive_dir),
        "manifest": str(manifest_path),
        "archive_root_manifest": str(root_manifest_path),
        "files_archived": len(manifest["files"]),
        "hash_only_stubs": len(manifest["excluded_stubs"]),
        "capture_timestamp": capture_timestamp,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a curated, tamper-evident MAW run archive.")
    parser.add_argument("run")
    parser.add_argument("--archive-root")
    parser.add_argument("--target-repo")
    parser.add_argument("--maw-commit")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        result = archive_run(
            Path(args.run),
            archive_root=Path(args.archive_root) if args.archive_root else None,
            target_repo=Path(args.target_repo) if args.target_repo else None,
            maw_commit=args.maw_commit,
        )
    except Exception as exc:  # pragma: no cover - CLI safety net
        result = {"check": "research_archive_export", "schema_version": 1, "passed": False, "error": str(exc)}
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
