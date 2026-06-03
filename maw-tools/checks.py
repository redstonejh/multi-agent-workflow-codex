#!/usr/bin/env python3
"""Deterministic checks for Codex MAW."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


def emit(data: dict) -> None:
    print(json.dumps(data, indent=2))


def tail(text: str, limit: int = 2000) -> str:
    return text if len(text) <= limit else "...(truncated)...\n" + text[-limit:]


def cmd_test(args: argparse.Namespace) -> int:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            args.cmd,
            shell=True,
            cwd=args.cwd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timed_out = True

    passed = exit_code == 0 and not timed_out
    emit({
        "check": "test",
        "command": args.cmd,
        "cwd": args.cwd or ".",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "passed": passed,
        "duration_sec": round(time.monotonic() - started, 3),
        "stdout_tail": tail(stdout),
        "stderr_tail": tail(stderr),
    })
    return 0 if passed else 1


def load_numbers(args: argparse.Namespace) -> list[float]:
    raw = list(args.numbers or [])
    if args.file:
        raw.extend(Path(args.file).read_text(encoding="utf-8").split())
    return [float(item) for item in raw]


def cmd_stats(args: argparse.Namespace) -> int:
    numbers = load_numbers(args)
    if not numbers:
        print("error: no numbers provided", file=sys.stderr)
        return 2
    emit({
        "check": "stats",
        "count": len(numbers),
        "mean": statistics.fmean(numbers),
        "median": statistics.median(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "stdev": statistics.stdev(numbers) if len(numbers) > 1 else 0.0,
        "passed": True,
    })
    return 0


def cmd_gap(args: argparse.Namespace) -> int:
    gap = args.train - args.test
    passed = gap <= args.tol
    emit({
        "check": "gap",
        "train_score": args.train,
        "test_score": args.test,
        "gap": round(gap, 6),
        "tolerance": args.tol,
        "passed": passed,
    })
    return 0 if passed else 1


def load_json(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("input JSON must be an object")
    return data


def validate_dependency_map(data: dict) -> dict:
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return {"check": "dependency_map", "passed": False, "errors": ["nodes must be a non-empty list"]}

    errors: list[str] = []
    nodes: dict[str, list[str]] = {}
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            errors.append(f"nodes[{index}] must be an object")
            continue
        node_id = raw.get("id")
        depends_on = raw.get("depends_on", [])
        if not isinstance(node_id, str) or not node_id:
            errors.append(f"nodes[{index}].id must be a non-empty string")
            continue
        if node_id in nodes:
            errors.append(f"duplicate node id: {node_id}")
        if not isinstance(depends_on, list) or not all(isinstance(dep, str) for dep in depends_on):
            errors.append(f"node {node_id}: depends_on must be a list of strings")
            depends_on = []
        nodes[node_id] = list(depends_on)

    for node_id, deps in nodes.items():
        for dep in deps:
            if dep not in nodes:
                errors.append(f"node {node_id}: unknown dependency {dep}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in visiting:
            errors.append(f"cycle detected at {node_id}")
            return
        visiting.add(node_id)
        for dep in nodes.get(node_id, []):
            if dep in nodes:
                visit(dep)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in list(nodes):
        visit(node_id)

    return {
        "check": "dependency_map",
        "node_count": len(nodes),
        "passed": not errors,
        "errors": errors,
    }


def cmd_dependency_map(args: argparse.Namespace) -> int:
    try:
        result = validate_dependency_map(load_json(args.file))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        result = {"check": "dependency_map", "passed": False, "errors": [str(exc)]}
    emit(result)
    return 0 if result["passed"] else 1


def validate_aggregation(data: dict) -> dict:
    required_lanes = data.get("required_lanes")
    findings = data.get("findings")
    if not isinstance(required_lanes, list) or not all(isinstance(item, str) for item in required_lanes):
        return {"check": "aggregation", "passed": False, "errors": ["required_lanes must be a list of strings"]}
    if not isinstance(findings, list):
        return {"check": "aggregation", "passed": False, "errors": ["findings must be a list"]}

    lanes_with_findings: set[str] = set()
    errors: list[str] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        lane = finding.get("lane")
        summary = finding.get("summary")
        if not isinstance(lane, str) or not lane:
            errors.append(f"findings[{index}].lane must be a non-empty string")
            continue
        if lane not in required_lanes:
            errors.append(f"findings[{index}].lane is not required: {lane}")
        if not isinstance(summary, str) or not summary.strip():
            errors.append(f"findings[{index}].summary must be non-empty")
        lanes_with_findings.add(lane)

    missing = sorted(set(required_lanes) - lanes_with_findings)
    errors.extend(f"missing finding for lane: {lane}" for lane in missing)
    return {
        "check": "aggregation",
        "required_lanes": required_lanes,
        "covered_lanes": sorted(lanes_with_findings),
        "passed": not errors,
        "errors": errors,
    }


def cmd_aggregation(args: argparse.Namespace) -> int:
    try:
        result = validate_aggregation(load_json(args.file))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        result = {"check": "aggregation", "passed": False, "errors": [str(exc)]}
    emit(result)
    return 0 if result["passed"] else 1


def cmd_artifacts_parse(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    items: list[dict[str, object]] = []
    errors: list[str] = []
    for artifact in args.artifacts:
        rel = artifact.replace("\\", "/")
        path = run_dir / rel
        item: dict[str, object] = {"artifact": rel, "path": str(path)}
        if not path.is_file():
            item.update({"passed": False, "reason": "missing"})
            errors.append(f"{rel}: missing")
            items.append(item)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            item.update({"passed": False, "reason": str(exc)})
            errors.append(f"{rel}: {exc}")
            items.append(item)
            continue
        item.update({"passed": isinstance(data, dict), "reason": "parsed JSON object" if isinstance(data, dict) else "JSON must be an object"})
        if not isinstance(data, dict):
            errors.append(f"{rel}: JSON must be an object")
        items.append(item)
    result = {"check": "artifacts_parse", "passed": not errors, "items": items, "errors": errors}
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    emit(result)
    return 0 if result["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic Codex MAW checks.")
    sub = parser.add_subparsers(dest="command", required=True)

    test = sub.add_parser("test")
    test.add_argument("--cmd", required=True)
    test.add_argument("--cwd")
    test.add_argument("--timeout", type=float, default=600)
    test.set_defaults(func=cmd_test)

    stats = sub.add_parser("stats")
    stats.add_argument("numbers", nargs="*")
    stats.add_argument("--file")
    stats.set_defaults(func=cmd_stats)

    gap = sub.add_parser("gap")
    gap.add_argument("--train", type=float, required=True)
    gap.add_argument("--test", type=float, required=True)
    gap.add_argument("--tol", type=float, default=0.05)
    gap.set_defaults(func=cmd_gap)

    dep = sub.add_parser("dependency-map")
    dep.add_argument("--file", required=True)
    dep.set_defaults(func=cmd_dependency_map)

    aggregate = sub.add_parser("aggregation")
    aggregate.add_argument("--file", required=True)
    aggregate.set_defaults(func=cmd_aggregation)

    artifacts = sub.add_parser("artifacts-parse")
    artifacts.add_argument("--run", required=True)
    artifacts.add_argument("--artifacts", nargs="+", required=True)
    artifacts.add_argument("--output")
    artifacts.set_defaults(func=cmd_artifacts_parse)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
