#!/usr/bin/env python3
"""Final deterministic acceptance check for a Codex MAW run."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import validate_handoffs
import run_report
import verdict_check
import anti_gaming_check
import salvage_check
import archive_run


ACCEPTANCE_RESULT = "acceptance-result.json"
ML_VALIDATOR_ARTIFACT = "artifacts/ml-validator.json"
REGRESSION_RESISTANCE_ARTIFACT = "artifacts/regression-resistance.json"
REFACTOR_RESISTANCE_ARTIFACT = "artifacts/refactor-resistance.json"
REFACTOR_STRUCTURE_ARTIFACT = "artifacts/refactor-structure.json"
REFACTOR_COMPLEXITY_ARTIFACT = "artifacts/complexity-report.json"
REFACTOR_PERF_ARTIFACT = "artifacts/perf-budget.json"
SALVAGE_RESISTANCE_ARTIFACT = "artifacts/salvage-resistance.json"
SALVAGE_RESULT_ARTIFACT = "artifacts/salvage-result.json"
DEFAULT_TASK_TYPE = "standard-software-task"
WORKFLOW_TEMPLATE_RE = re.compile(r"(?m)^-\s*Workflow template:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_RE = re.compile(r"(?m)^-\s*Task type:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_ALIASES = {
    "generic": "standard-software-task",
    "salvage": "salvage-task",
}
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "standard-software-task": ("artifacts/test-result.json",),
    "code": (
        "artifacts/test-result.json",
        "artifacts/artifact-parse-report.json",
        "artifacts/checklist-validation.json",
        "artifacts/dependency-map.json",
        "artifacts/dependency-risk-report.json",
    ),
    "refactor-task": (
        "artifacts/behavior-baseline.json",
        "artifacts/behavior-diff.json",
        "artifacts/refactor-coverage.json",
        "artifacts/api-surface-diff.json",
        REFACTOR_STRUCTURE_ARTIFACT,
        REFACTOR_COMPLEXITY_ARTIFACT,
        REFACTOR_PERF_ARTIFACT,
        REFACTOR_RESISTANCE_ARTIFACT,
        "artifacts/test-result.json",
    ),
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
    "salvage-task": (
        "artifacts/preserved-surface.json",
        "artifacts/topology.json",
        "artifacts/test-triage.json",
        "artifacts/characterization-baseline.json",
        "artifacts/code-graph.json",
        "artifacts/hidden-deps.json",
        "artifacts/cross-lang-couplings.json",
        "artifacts/dead-code.json",
        "artifacts/duplication.json",
        "artifacts/preserve-parity.json",
        SALVAGE_RESISTANCE_ARTIFACT,
        SALVAGE_RESULT_ARTIFACT,
    ),
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


def refactor_resistance_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "refactor-resistance JSON must be an object"
    if data.get("check") != "refactor_resistance":
        return False, "check must be refactor_resistance"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    clean = data.get("clean")
    if not isinstance(clean, dict) or clean.get("passed") is not True:
        return False, "clean behavior diff must pass before mutation resistance is trusted"
    mutations = data.get("mutations")
    if not isinstance(mutations, list) or not mutations:
        return False, "mutations must be a non-empty list"
    for item in mutations:
        if not isinstance(item, dict):
            return False, "mutation item must be an object"
        if item.get("planted") is not True:
            return False, f"mutation was not planted: {item.get('name')}"
        if item.get("caught") is not True:
            return False, f"mutation was not caught: {item.get('name')}"
        if item.get("mutant_passed") is not False:
            return False, f"mutant behavior diff must fail: {item.get('name')}"
        failed_checks = item.get("failed_checks")
        if not isinstance(failed_checks, list) or not failed_checks:
            return False, f"mutation must record failed checks: {item.get('name')}"
    summary = data.get("summary")
    if not isinstance(summary, dict) or summary.get("caught") != summary.get("total") or summary.get("total") != len(mutations):
        return False, "summary must report every planted mutation caught"
    return bool(data["passed"]), "refactor resistance schema passed" if data["passed"] else "refactor resistance reports failed"


def refactor_structure_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "refactor-structure JSON must be an object"
    if data.get("check") != "refactor_structure":
        return False, "check must be refactor_structure"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if data.get("refactor_type") not in {"rename", "extract-function", "inline", "move-module", "dedupe"}:
        return False, "refactor_type must be one of the supported structural refactor types"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    violations = data.get("violations")
    if not isinstance(violations, list):
        return False, "violations must be a list"
    if data["passed"] and violations:
        return False, "passed structure artifact must not include violations"
    return bool(data["passed"]), "refactor structure schema passed" if data["passed"] else "refactor structure reports failed"


def refactor_complexity_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "complexity-report JSON must be an object"
    if data.get("check") != "refactor_complexity":
        return False, "check must be refactor_complexity"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    if not isinstance(data.get("functions"), list):
        return False, "functions must be a list"
    if not isinstance(data.get("violations"), list):
        return False, "violations must be a list"
    if data["passed"] and data["violations"]:
        return False, "passed complexity artifact must not include violations"
    return bool(data["passed"]), "refactor complexity schema passed" if data["passed"] else "refactor complexity reports failed"


def refactor_perf_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "perf-budget JSON must be an object"
    if data.get("check") != "refactor_perf_budget":
        return False, "check must be refactor_perf_budget"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    if data.get("status") not in {"passed", "failed", "advisory", "invalid"}:
        return False, "status must be passed, failed, advisory, or invalid"
    if not isinstance(data.get("probes"), list):
        return False, "probes must be a list"
    if not isinstance(data.get("violations"), list):
        return False, "violations must be a list"
    if data["passed"] and data["violations"]:
        return False, "passed perf artifact must not include violations"
    return bool(data["passed"]), "refactor perf budget schema passed" if data["passed"] else "refactor perf budget reports failed"


def salvage_resistance_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "salvage-resistance JSON must be an object"
    if data.get("check") != "salvage_resistance":
        return False, "check must be salvage_resistance"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if not isinstance(data.get("passed"), bool):
        return False, "passed must be a boolean"
    mutations = data.get("mutations")
    if not isinstance(mutations, list):
        return False, "mutations must be a list"
    expected = {
        "reintroduced_hidden_dependency",
        "resurrected_dead_reference",
        "reduplicated_function",
        "server_preserved_surface_behavior_break",
        "client_preserved_surface_behavior_break",
        "broken_cross_language_coupling",
        "surface_shrink_gaming",
    }
    names = {item.get("name") for item in mutations if isinstance(item, dict)}
    if not expected <= names:
        return False, "mutations must cover hidden dependency, dead reference, duplicate, server/client behavior break, cross-language coupling, and surface-shrink planted failures"
    for item in mutations:
        if not isinstance(item, dict):
            return False, "mutation item must be an object"
        if item.get("planted") is not True:
            return False, f"mutation was not planted: {item.get('name')}"
        if item.get("caught") is not True:
            return False, f"mutation was not caught: {item.get('name')}"
        if item.get("mutant_passed") is not False:
            return False, f"mutant gate must fail: {item.get('name')}"
        if not isinstance(item.get("failed_checks"), list) or not item.get("failed_checks"):
            return False, f"mutation must record failed checks: {item.get('name')}"
    summary = data.get("summary")
    if not isinstance(summary, dict) or summary.get("caught") != summary.get("total") or summary.get("total") != len(mutations):
        return False, "summary must report every planted mutation caught"
    return bool(data["passed"]), "salvage resistance schema passed" if data["passed"] else "salvage resistance reports failed"


def preserved_surface_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "preserved-surface JSON must be an object"
    entrypoints = data.get("entrypoints")
    if not isinstance(entrypoints, list) or not all(isinstance(item, str) and item.strip() for item in entrypoints):
        return False, "entrypoints must be a non-empty list of strings"
    before = data.get("entrypoints_before")
    if before is not None and (not isinstance(before, list) or not all(isinstance(item, str) and item.strip() for item in before)):
        return False, "entrypoints_before must be a list of strings when present"
    if before and len(set(entrypoints)) < len(set(before)):
        return False, "preserved surface shrank"
    return True, "preserved surface schema passed"


def salvage_result_reports_pass(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "salvage-result JSON must be an object"
    if data.get("check") != "salvage_result":
        return False, "check must be salvage_result"
    if data.get("schema_version") != 1:
        return False, "schema_version must be 1"
    if data.get("passed") is not True:
        return False, "salvage result reports failed"
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        return False, "gates must be a non-empty list"
    if not all(isinstance(item, dict) and item.get("passed") is True for item in gates):
        return False, "one or more salvage gates failed"
    freeze = data.get("freeze")
    if not isinstance(freeze, dict) or freeze.get("passed") is not True:
        return False, "preserved-surface freeze check failed"
    return True, "salvage result schema passed"


def required_artifact_reports_pass(artifact: str, data: Any) -> tuple[bool, str]:
    if artifact == "artifacts/preserved-surface.json":
        return preserved_surface_reports_pass(data)
    if artifact == ML_VALIDATOR_ARTIFACT:
        return ml_validator_reports_pass(data)
    if artifact == REGRESSION_RESISTANCE_ARTIFACT:
        return regression_resistance_reports_pass(data)
    if artifact == REFACTOR_RESISTANCE_ARTIFACT:
        return refactor_resistance_reports_pass(data)
    if artifact == REFACTOR_STRUCTURE_ARTIFACT:
        return refactor_structure_reports_pass(data)
    if artifact == REFACTOR_COMPLEXITY_ARTIFACT:
        return refactor_complexity_reports_pass(data)
    if artifact == REFACTOR_PERF_ARTIFACT:
        return refactor_perf_reports_pass(data)
    if artifact == SALVAGE_RESISTANCE_ARTIFACT:
        return salvage_resistance_reports_pass(data)
    if artifact == SALVAGE_RESULT_ARTIFACT:
        return salvage_result_reports_pass(data)
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


def acceptance_violations(handoffs: dict, test: dict, evidence: dict, anti_gaming: dict | None = None, salvage_gates: dict | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not handoffs.get("passed"):
        result.append(violation("handoffs_invalid", "handoff validation failed"))
    if not test.get("passed"):
        result.append(violation("tests_failed", "test command failed"))
    result.extend(evidence.get("violations", []))
    if anti_gaming is not None and not anti_gaming.get("passed"):
        for item in anti_gaming.get("violations", []):
            if isinstance(item, dict):
                extra = {key: value for key, value in item.items() if key not in {"type", "message"}}
                result.append(
                    violation(
                        "anti_gaming_gate_failed",
                        item.get("message", "anti-gaming hard gate failed"),
                        anti_gaming_type=item.get("type"),
                        **extra,
                    )
                )
    if salvage_gates is not None and not salvage_gates.get("passed"):
        for item in salvage_gates.get("violations", []):
            if isinstance(item, dict):
                extra = {key: value for key, value in item.items() if key not in {"type", "message"}}
                result.append(
                    violation(
                        "salvage_gate_failed",
                        item.get("message", "salvage hard gate failed"),
                        salvage_type=item.get("type"),
                        **extra,
                    )
                )
    return result


def verdict(handoffs: dict, test: dict, evidence: dict, anti_gaming: dict | None = None, salvage_gates: dict | None = None) -> str:
    if not handoffs.get("passed"):
        return "NO-SHIP"
    if not test.get("passed"):
        return "NO-SHIP"
    if not evidence.get("passed"):
        return "NO-SHIP"
    if anti_gaming is not None and not anti_gaming.get("passed"):
        return "NO-SHIP"
    if salvage_gates is not None and not salvage_gates.get("passed"):
        return "NO-SHIP"
    return "SHIP"


def acceptance_artifact_path(run_dir: Path) -> Path:
    return run_dir / "artifacts" / ACCEPTANCE_RESULT


def write_acceptance_artifact(run_dir: Path, result: dict) -> Path:
    path = acceptance_artifact_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return path


def write_json_artifact(path: Path, data: dict[str, Any], overwrite: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite or not path.is_file():
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_run_declares_verdict(run_dir: Path, final_verdict: str) -> None:
    run_md = run_dir / "run.md"
    try:
        text = run_md.read_text(encoding="utf-8")
    except OSError:
        return
    marker = "## Final result summary"
    summary = f"{marker}\nFinal verdict: {final_verdict}\n"
    if marker in text:
        text = re.sub(r"(?s)## Final result summary\n.*$", summary.rstrip(), text).rstrip() + "\n"
    else:
        text = text.rstrip() + "\n\n" + summary
    run_md.write_text(text, encoding="utf-8")


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
    artifacts = run_dir / "artifacts"
    write_json_artifact(artifacts / "handoff-validation.json", handoffs, overwrite=False)
    task_type = infer_task_type(run_dir)
    evidence = check_required_evidence(run_dir, task_type)
    anti_gaming = anti_gaming_check.check_run(run_dir)
    salvage_gates = salvage_check.check_run(run_dir)
    write_json_artifact(artifacts / "anti-gaming-hard-gates.json", anti_gaming)
    write_json_artifact(artifacts / "salvage-hard-gates.json", salvage_gates)
    violations = acceptance_violations(handoffs, test, evidence, anti_gaming, salvage_gates)
    final_verdict = verdict(handoffs, test, evidence, anti_gaming, salvage_gates)
    result = {
        "run": str(run_dir),
        "task_type": task_type,
        "handoffs": handoffs,
        "test": test,
        "evidence": evidence,
        "anti_gaming": anti_gaming,
        "salvage_gates": salvage_gates,
        "violations": violations,
        "verdict": final_verdict,
    }
    if args.test_cmd:
        write_json_artifact(artifacts / "test-result.json", test, overwrite=False)
    write_acceptance_artifact(run_dir, result)
    ensure_run_declares_verdict(run_dir, final_verdict)
    verdict_result = verdict_check.check_run(run_dir)
    write_json_artifact(artifacts / "verdict-check-result.json", verdict_result)
    summary_path = run_report.write_run_summary(run_dir)
    report_result = {"check": "run_report", "run": str(run_dir), "summary": str(summary_path), "passed": summary_path.is_file()}
    write_json_artifact(artifacts / "run-report-result.json", report_result)
    try:
        archive_result = archive_run.archive_run(
            run_dir,
            archive_root=Path(os.environ["MAW_RESEARCH_ARCHIVE_DIR"]) if os.environ.get("MAW_RESEARCH_ARCHIVE_DIR") else None,
            target_repo=Path(os.environ["MAW_TARGET_REPO"]) if os.environ.get("MAW_TARGET_REPO") else None,
            maw_commit=os.environ.get("MAW_EXECUTOR_COMMIT"),
        )
    except Exception as exc:
        archive_result = {
            "check": "research_archive_export",
            "schema_version": 1,
            "passed": False,
            "error": str(exc),
        }
    write_json_artifact(artifacts / "research-archive-result.json", archive_result)
    result["run_summary"] = str(summary_path)
    result["research_archive"] = archive_result
    write_acceptance_artifact(run_dir, result)
    run_report.write_run_summary(run_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "SHIP" else 1


if __name__ == "__main__":
    raise SystemExit(main())
