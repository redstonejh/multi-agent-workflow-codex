#!/usr/bin/env python3
"""Final deterministic acceptance check for a Codex MAW run."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import validate_handoffs


ACCEPTANCE_RESULT = "acceptance-result.json"
ML_VALIDATOR_ARTIFACT = "artifacts/ml-validator.json"
REGRESSION_RESISTANCE_ARTIFACT = "artifacts/regression-resistance.json"
DEFAULT_TASK_TYPE = "standard-software-task"
WORKFLOW_TEMPLATE_RE = re.compile(r"(?m)^-\s*Workflow template:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_RE = re.compile(r"(?m)^-\s*Task type:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_ALIASES = {
    "generic": "standard-software-task",
}
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "standard-software-task": ("artifacts/test-result.json",),
    "code": (
        "artifacts/test-result.json",
        "artifacts/checklist-validation.json",
        "artifacts/dependency-map.json",
        "artifacts/dependency-risk-report.json",
    ),
    "refactor-task": ("artifacts/behavior-baseline.json", "artifacts/behavior-diff.json", "artifacts/test-result.json"),
    "bug-investigation": (
        "artifacts/dependency-map.json",
        "artifacts/dependency-risk-report.json",
        "artifacts/regression-test.json",
    ),
    "frontend-ui-task": (
        "artifacts/change-verification.json",
        "artifacts/style-extraction.json",
        "artifacts/a11y-audit.json",
        "artifacts/contrast-check.json",
        "artifacts/perf-budget.json",
        "artifacts/markup-validation.json",
        "artifacts/link-check.json",
        "artifacts/style-drift-audit.json",
    ),
    "ml": (
        ML_VALIDATOR_ARTIFACT,
        "artifacts/leakage-audit.json",
        "artifacts/drift-report.json",
        "artifacts/data-quality-report.json",
        "artifacts/reproducibility-check.json",
        "artifacts/classification-metrics.json",
        "artifacts/baseline-comparison.json",
        "artifacts/fit-diagnosis.json",
        "artifacts/calibration-report.json",
        "artifacts/shuffled-label-check.json",
        "artifacts/multi-seed-stability.json",
        REGRESSION_RESISTANCE_ARTIFACT,
    ),
    "ml-training-task": (
        ML_VALIDATOR_ARTIFACT,
        "artifacts/leakage-audit.json",
        "artifacts/drift-report.json",
        "artifacts/data-quality-report.json",
        "artifacts/reproducibility-check.json",
        "artifacts/classification-metrics.json",
        "artifacts/baseline-comparison.json",
        "artifacts/fit-diagnosis.json",
        "artifacts/calibration-report.json",
        "artifacts/shuffled-label-check.json",
        "artifacts/multi-seed-stability.json",
        REGRESSION_RESISTANCE_ARTIFACT,
    ),
    "ml-validation-task": (
        ML_VALIDATOR_ARTIFACT,
        "artifacts/leakage-audit.json",
        "artifacts/drift-report.json",
        "artifacts/data-quality-report.json",
        "artifacts/classification-metrics.json",
        "artifacts/baseline-comparison.json",
        "artifacts/fit-diagnosis.json",
        "artifacts/calibration-report.json",
        "artifacts/reproducibility-check.json",
        "artifacts/shuffled-label-check.json",
        "artifacts/multi-seed-stability.json",
        REGRESSION_RESISTANCE_ARTIFACT,
    ),
    "multi-agent-research-task": ("artifacts/dependency-risk-report.json", "artifacts/aggregation.json"),
}


def run_test(command: str | None, cwd: str | None, timeout: float) -> dict:
    if not command:
        return {"configured": False, "passed": True}
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("checks.py")), "test", "--cmd", command, "--timeout", str(timeout), *([] if cwd is None else ["--cwd", cwd])],
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "stdout": proc.stdout, "stderr": proc.stderr}
    data["configured"] = True
    data["tool_exit_code"] = proc.returncode
    return data


def normalize_task_type(task_type: str | None) -> str:
    value = (task_type or DEFAULT_TASK_TYPE).strip()
    return TASK_TYPE_ALIASES.get(value, value)


def infer_task_type(run_dir: Path) -> str:
    run_md = run_dir / "run.md"
    try:
        text = run_md.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_TASK_TYPE
    for pattern in (WORKFLOW_TEMPLATE_RE, TASK_TYPE_RE):
        match = pattern.search(text)
        if match:
            return normalize_task_type(match.group("value"))
    return DEFAULT_TASK_TYPE


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def artifact_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "artifact JSON must be an object"
    passed = data.get("passed")
    if isinstance(passed, bool):
        return passed, "passed is true" if passed else "passed is false"

    acceptance = data.get("acceptance")
    if isinstance(acceptance, dict) and isinstance(acceptance.get("passed"), bool):
        return acceptance["passed"], "acceptance.passed is true" if acceptance["passed"] else "acceptance.passed is false"

    checks = data.get("checks")
    if isinstance(checks, list) and checks and all(isinstance(item, dict) and isinstance(item.get("passed"), bool) for item in checks):
        all_passed = all(item["passed"] for item in checks)
        return all_passed, "all checks passed" if all_passed else "one or more checks failed"

    status = data.get("status")
    if isinstance(status, str) and status.lower() in {"pass", "passed", "ok"}:
        return True, f"status is {status}"
    if isinstance(status, str) and status.lower() in {"fail", "failed", "invalid", "error"}:
        return False, f"status is {status}"

    ok = data.get("ok")
    if isinstance(ok, bool):
        return ok, "ok is true" if ok else "ok is false"

    return False, "artifact does not report pass/fail"


def ml_validator_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "ml-validator JSON must be an object"
    if data.get("check") != "ml_validator":
        return False, "check must be ml_validator"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    required = data.get("required_evidence")
    if required != ["leakage", "drift", "baseline", "multi_seed", "shuffled_label"]:
        return False, "required_evidence must list leakage, drift, baseline, multi_seed, shuffled_label"
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        return False, "evidence must be an object"
    for name in required:
        item = evidence.get(name)
        if not isinstance(item, dict):
            return False, f"missing evidence item: {name}"
        if not isinstance(item.get("artifact"), str) or not item["artifact"]:
            return False, f"evidence.{name}.artifact must be a non-empty string"
        if not isinstance(item.get("passed"), bool):
            return False, f"evidence.{name}.passed must be a boolean"
    checks = data.get("checks")
    if not isinstance(checks, list) or len(checks) != len(required):
        return False, "checks must contain one item for each required evidence item"
    if not all(isinstance(item, dict) and item.get("passed") is True for item in checks):
        return False, "one or more validator evidence checks failed"
    return bool(data["passed"]), "ml validator schema passed" if data["passed"] else "ml validator reports failed"


def regression_resistance_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "regression-resistance JSON must be an object"
    if data.get("check") != "regression_resistance":
        return False, "check must be regression_resistance"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    clean = data.get("clean")
    if not isinstance(clean, dict) or clean.get("passed") is not True:
        return False, "clean validation must pass before mutation testing"
    expected = {
        "leaky_feature",
        "shuffled_labels",
        "train_test_overlap",
        "preprocessing_fit_full_data",
        "missing_metric",
        "weak_baseline_ci",
        "unstable_multi_seed",
        "bad_calibration_stats",
        "insignificant_shuffled_label",
        "content_duplicate_leakage",
        "group_entity_leakage",
        "temporal_leakage",
        "high_feature_target_correlation",
        "distribution_drift",
        "hard_imbalanced_majority",
        "hard_content_duplicate",
        "hard_temporal_leak",
    }
    mutations = data.get("mutations")
    if not isinstance(mutations, list):
        return False, "mutations must be a list"
    names = {item.get("name") for item in mutations if isinstance(item, dict)}
    if names != expected:
        return False, "mutations must cover all required ML leakage, drift, and statistical planted failures"
    for item in mutations:
        if not isinstance(item, dict):
            return False, "mutation item must be an object"
        if item.get("caught") is not True:
            return False, f"mutation was not caught: {item.get('name')}"
        if item.get("mutant_passed") is not False:
            return False, f"mutant validation must fail: {item.get('name')}"
        failed_checks = item.get("failed_checks")
        if not isinstance(failed_checks, list) or not failed_checks:
            return False, f"mutation must record failed checks: {item.get('name')}"
    return bool(data["passed"]), "regression resistance schema passed" if data["passed"] else "regression resistance reports failed"


def required_artifact_reports_pass(artifact: str, data: Any) -> tuple[bool, str]:
    if artifact == ML_VALIDATOR_ARTIFACT:
        return ml_validator_reports_pass(data)
    if artifact == REGRESSION_RESISTANCE_ARTIFACT:
        return regression_resistance_reports_pass(data)
    return artifact_reports_pass(data)


def resolve_source_path(run_dir: Path, source_path: str) -> Path | None:
    path = Path(source_path)
    candidates = [path] if path.is_absolute() else [Path.cwd() / path, run_dir / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def behavior_baseline_freshness_violations(run_dir: Path, artifact: str, path: Path, data: Any, task_type: str) -> list[dict[str, Any]]:
    if task_type != "refactor-task" or artifact != "artifacts/behavior-baseline.json":
        return []
    if not isinstance(data, dict):
        return []

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return [
            violation(
                "missing_behavior_baseline_metadata",
                "behavior baseline is missing metadata",
                artifact=artifact,
                path=str(path),
                task_type=task_type,
            )
        ]

    captured = metadata.get("captured_at_epoch")
    if not isinstance(captured, (int, float)):
        return [
            violation(
                "missing_behavior_baseline_timestamp",
                "behavior baseline is missing metadata.captured_at_epoch",
                artifact=artifact,
                path=str(path),
                task_type=task_type,
            )
        ]

    source_paths = metadata.get("source_paths")
    if not isinstance(source_paths, list) or not source_paths:
        return [
            violation(
                "missing_behavior_source_paths",
                "behavior baseline metadata.source_paths must list refactored source files",
                artifact=artifact,
                path=str(path),
                task_type=task_type,
            )
        ]

    violations: list[dict[str, Any]] = []
    for raw_source in source_paths:
        source = str(raw_source)
        resolved = resolve_source_path(run_dir, source)
        if resolved is None:
            violations.append(
                violation(
                    "missing_behavior_source",
                    f"behavior baseline source path does not exist: {source}",
                    artifact=artifact,
                    path=str(path),
                    source_path=source,
                    task_type=task_type,
                )
            )
            continue

        source_mtime = resolved.stat().st_mtime
        if source_mtime <= float(captured):
            violations.append(
                violation(
                    "late_behavior_baseline",
                    "behavior baseline was captured after a source edit or the covered source was not edited after baseline capture",
                    artifact=artifact,
                    path=str(path),
                    source_path=source,
                    resolved_source_path=str(resolved),
                    captured_at_epoch=float(captured),
                    source_mtime=source_mtime,
                    task_type=task_type,
                )
            )
    return violations


def check_required_evidence(run_dir: Path, task_type: str) -> dict[str, Any]:
    if task_type not in REQUIRED_EVIDENCE:
        item = violation(
            "unknown_task_type_evidence",
            f"no required evidence map for task type: {task_type}",
            task_type=task_type,
        )
        return {
            "task_type": task_type,
            "required": [],
            "items": [],
            "passed": False,
            "violations": [item],
        }

    required = list(REQUIRED_EVIDENCE[task_type])
    items: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for artifact in required:
        path = run_dir / artifact
        item: dict[str, Any] = {"artifact": artifact, "path": str(path)}
        if not path.is_file():
            item.update({"passed": False, "reason": "missing"})
            violations.append(
                violation(
                    "missing_required_evidence",
                    f"missing required evidence artifact: {artifact}",
                    artifact=artifact,
                    path=str(path),
                    task_type=task_type,
                )
            )
            items.append(item)
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            item.update({"passed": False, "reason": str(exc)})
            violations.append(
                violation(
                    "failing_required_evidence",
                    f"required evidence artifact did not pass: {artifact}",
                    artifact=artifact,
                    path=str(path),
                    task_type=task_type,
                    reason=str(exc),
                )
            )
            items.append(item)
            continue

        passed, reason = required_artifact_reports_pass(artifact, data)
        item.update({"passed": passed, "reason": reason})
        if not passed:
            violations.append(
                violation(
                    "failing_required_evidence",
                    f"required evidence artifact did not pass: {artifact}",
                    artifact=artifact,
                    path=str(path),
                    task_type=task_type,
                    reason=reason,
                )
            )
        freshness_violations = behavior_baseline_freshness_violations(run_dir, artifact, path, data, task_type)
        if freshness_violations:
            item.update({"passed": False, "reason": freshness_violations[0]["type"]})
            violations.extend(freshness_violations)
        items.append(item)

    return {
        "task_type": task_type,
        "required": required,
        "items": items,
        "passed": not violations,
        "violations": violations,
    }


def acceptance_violations(handoffs: dict, test: dict, evidence: dict) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not handoffs.get("passed"):
        result.append(violation("handoffs_invalid", "handoff validation failed"))
    if not test.get("passed"):
        result.append(violation("tests_failed", "test command failed"))
    result.extend(evidence.get("violations", []))
    return result


def verdict(handoffs: dict, test: dict, evidence: dict) -> str:
    if not handoffs.get("passed"):
        return "NO-SHIP"
    if not test.get("passed"):
        return "NO-SHIP"
    if not evidence.get("passed"):
        return "NO-SHIP"
    return "SHIP"


def acceptance_artifact_path(run_dir: Path) -> Path:
    return run_dir / "artifacts" / ACCEPTANCE_RESULT


def write_acceptance_artifact(run_dir: Path, result: dict) -> Path:
    path = acceptance_artifact_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final deterministic MAW acceptance checks.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--test-cmd")
    parser.add_argument("--test-cwd")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)

    run_dir = Path(args.run)
    handoffs = validate_handoffs.validate_run(run_dir)
    test = run_test(args.test_cmd, args.test_cwd, args.timeout)
    task_type = infer_task_type(run_dir)
    evidence = check_required_evidence(run_dir, task_type)
    violations = acceptance_violations(handoffs, test, evidence)
    result = {
        "run": str(run_dir),
        "task_type": task_type,
        "handoffs": handoffs,
        "test": test,
        "evidence": evidence,
        "violations": violations,
        "verdict": verdict(handoffs, test, evidence),
    }
    write_acceptance_artifact(run_dir, result)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "SHIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
