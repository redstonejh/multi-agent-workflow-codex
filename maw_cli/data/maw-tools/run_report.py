#!/usr/bin/env python3
"""Write a one-page markdown summary for a MAW run."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import validate_handoffs


ACCEPTANCE_RESULT = "artifacts/acceptance-result.json"
RUN_SUMMARY = "artifacts/run-summary.md"
DEFAULT_TASK_TYPE = "standard-software-task"
WORKFLOW_TEMPLATE_RE = re.compile(r"(?m)^-\s*Workflow template:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_RE = re.compile(r"(?m)^-\s*Task type:\s*(?P<value>[a-zA-Z0-9_-]+)\s*$")
TASK_TYPE_ALIASES = {"generic": "standard-software-task"}
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
        "artifacts/refactor-structure.json",
        "artifacts/complexity-report.json",
        "artifacts/perf-budget.json",
        "artifacts/refactor-resistance.json",
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
        "artifacts/ml-validator.json",
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
        "artifacts/regression-resistance.json",
    ),
    "ml-training-task": (
        "artifacts/ml-validator.json",
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
        "artifacts/regression-resistance.json",
    ),
    "ml-validation-task": (
        "artifacts/ml-validator.json",
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
        "artifacts/regression-resistance.json",
    ),
    "multi-agent-research-task": ("artifacts/dependency-risk-report.json", "artifacts/aggregation.json"),
}


def load_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def normalize_task_type(task_type: str | None) -> str:
    value = (task_type or DEFAULT_TASK_TYPE).strip()
    return TASK_TYPE_ALIASES.get(value, value)


def infer_task_type(run_dir: Path, conductor_plan: Any) -> str:
    if isinstance(conductor_plan, dict) and isinstance(conductor_plan.get("task_type"), str):
        return normalize_task_type(conductor_plan["task_type"])
    try:
        text = (run_dir / "run.md").read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_TASK_TYPE
    for pattern in (WORKFLOW_TEMPLATE_RE, TASK_TYPE_RE):
        match = pattern.search(text)
        if match:
            return normalize_task_type(match.group("value"))
    return DEFAULT_TASK_TYPE


def artifact_pass_reason(data: Any, read_error: str | None) -> tuple[str, str]:
    if read_error:
        return "FAIL", read_error
    if not isinstance(data, dict):
        return "FAIL", "JSON is not an object"
    passed = data.get("passed")
    if isinstance(passed, bool):
        return ("PASS" if passed else "FAIL"), "passed field"
    verdict = data.get("verdict")
    if isinstance(verdict, str):
        if verdict in {"SHIP", "PASS", "APPROVE"}:
            return "PASS", f"verdict {verdict}"
        if verdict in {"NO-SHIP", "NEEDS-HUMAN", "FAIL", "REVISE"}:
            return "FAIL", f"verdict {verdict}"
        return "UNKNOWN", f"verdict {verdict}"
    status = data.get("status")
    if isinstance(status, str):
        lowered = status.lower()
        if lowered in {"pass", "passed", "ok"}:
            return "PASS", f"status {status}"
        if lowered in {"fail", "failed", "error", "invalid"}:
            return "FAIL", f"status {status}"
    return "UNKNOWN", "no pass/fail field"


def artifact_status(run_dir: Path, artifact: str) -> dict[str, str]:
    path = run_dir / artifact
    if not path.is_file():
        return {"artifact": artifact, "status": "MISSING", "reason": "missing"}
    if path.suffix.lower() in {".md", ".txt"}:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"artifact": artifact, "status": "FAIL", "reason": str(exc)}
        match = re.search(r"(?im)^\s*Verdict:\s*(?P<verdict>[A-Z-]+)\s*$", text)
        if match:
            verdict = match.group("verdict")
            if verdict in {"APPROVE", "PASS", "SHIP"}:
                return {"artifact": artifact, "status": "PASS", "reason": f"verdict {verdict}"}
            if verdict in {"REVISE", "FAIL", "NO-SHIP", "NEEDS-HUMAN"}:
                return {"artifact": artifact, "status": "FAIL", "reason": f"verdict {verdict}"}
            return {"artifact": artifact, "status": "UNKNOWN", "reason": f"verdict {verdict}"}
        return {"artifact": artifact, "status": "not recorded", "reason": "text artifact has no verdict"}
    data, error = load_json(path)
    status, reason = artifact_pass_reason(data, error)
    return {"artifact": artifact, "status": status, "reason": reason}


def handoff_pipeline(run_dir: Path) -> list[str]:
    pipeline: list[str] = []
    for path in sorted((run_dir / "handoffs").glob("*.md")):
        match = re.match(r"\d+_(?P<frm>.+)__to__(?P<to>.+)\.md$", path.name)
        if match:
            pipeline.append(f"{match.group('frm')} -> {match.group('to')}")
    return pipeline


def roles_from_plan(conductor_plan: Any) -> list[str]:
    if not isinstance(conductor_plan, dict):
        return []
    roles = conductor_plan.get("roles")
    return [str(role) for role in roles] if isinstance(roles, list) else []


def planned_check_names(conductor_plan: Any) -> list[str]:
    if not isinstance(conductor_plan, dict):
        return []
    checks = conductor_plan.get("deterministic_checks")
    if not isinstance(checks, list):
        return []
    result: list[str] = []
    for item in checks:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result.append(item["name"])
    return result


def planned_checks(conductor_plan: Any) -> list[dict[str, str]]:
    if not isinstance(conductor_plan, dict):
        return []
    checks = conductor_plan.get("deterministic_checks")
    if not isinstance(checks, list):
        return []
    result: list[dict[str, str]] = []
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        check = {"name": item["name"]}
        if isinstance(item.get("evidence"), str):
            check["evidence"] = item["evidence"]
        if isinstance(item.get("command"), str):
            check["command"] = item["command"]
        result.append(check)
    return result


def artifact_from_command(command: str) -> str | None:
    match = re.search(r"--output\s+(?P<artifact>artifacts/[^\s\"']+)", command)
    if match:
        return match.group("artifact")
    return None


def planned_check_artifact(check: dict[str, str]) -> str | None:
    evidence = check.get("evidence")
    if evidence:
        return evidence
    command_artifact = artifact_from_command(check.get("command", ""))
    if command_artifact:
        return command_artifact
    artifact_by_name = {
        "acceptance": ACCEPTANCE_RESULT,
        "acceptance-result": ACCEPTANCE_RESULT,
        "artifact-parse": "artifacts/artifact-parse-report.json",
        "checklist-validation": "artifacts/checklist-validation.json",
        "dependency-boundary": "artifacts/dependency-risk-report.json",
        "dependency-map": "artifacts/dependency-map.json",
        "dependency-risk-audit": "artifacts/dependency-risk-report.json",
        "handoff-validation": "artifacts/handoff-validation.json",
        "offline-fake-wilds-e2e": "artifacts/wilds-export-result.json",
        "plan-check": "artifacts/plan-check-result.json",
        "readme-check": "artifacts/readme-check-result.json",
        "run-report": "artifacts/run-report-result.json",
        "unit-tests": "artifacts/test-result.json",
        "verdict-check": "artifacts/verdict-check-result.json",
        "wilds-export-fixture": "artifacts/wilds-export-result.json",
        "wilds-harness-fixture": "artifacts/wilds-harness-result.json",
        "workflow-template-validation": "artifacts/workflow-template-validation.json",
    }
    return artifact_by_name.get(check.get("name", ""))


def gate_rows(run_dir: Path, conductor_plan: Any, plan_check: Any, plan_check_error: str | None, acceptance: Any, acceptance_error: str | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    plan_status, plan_reason = artifact_pass_reason(plan_check, plan_check_error)
    rows.append({"gate": "plan-check", "status": plan_status, "detail": plan_reason})

    handoffs = validate_handoffs.validate_run(run_dir)
    rows.append({"gate": "handoffs", "status": "PASS" if handoffs.get("passed") else "FAIL", "detail": f"{handoffs.get('handoffs', 0)} handoffs"})

    if isinstance(acceptance, dict):
        test = acceptance.get("test")
        if isinstance(test, dict):
            rows.append({"gate": "test", "status": "PASS" if test.get("passed") else "FAIL", "detail": "configured" if test.get("configured") else "not configured"})
        evidence = acceptance.get("evidence")
        if isinstance(evidence, dict):
            rows.append({"gate": "required-evidence", "status": "PASS" if evidence.get("passed") else "FAIL", "detail": f"{len(evidence.get('items', []))} artifacts"})
    acceptance_status, acceptance_reason = artifact_pass_reason(acceptance, acceptance_error)
    rows.append({"gate": "acceptance-result", "status": acceptance_status, "detail": acceptance_reason})

    seen = {row["gate"] for row in rows}
    for check in planned_checks(conductor_plan):
        name = check["name"]
        if name in seen:
            continue
        artifact = planned_check_artifact(check)
        if artifact:
            status = artifact_status(run_dir, artifact)
            rows.append({"gate": name, "status": status["status"], "detail": artifact})
        else:
            rows.append({"gate": name, "status": "not recorded", "detail": "planned check produced no artifact"})
    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(cell.replace("\n", " ") for cell in row) + " |" for row in rows)
    return lines


def build_summary(run_dir: Path) -> str:
    conductor_plan, _plan_error = load_json(run_dir / "artifacts" / "conductor-plan.json")
    plan_check, plan_check_error = load_json(run_dir / "artifacts" / "plan-check-result.json")
    acceptance, acceptance_error = load_json(run_dir / ACCEPTANCE_RESULT)
    task_type = infer_task_type(run_dir, conductor_plan)
    caps = conductor_plan.get("caps", {}) if isinstance(conductor_plan, dict) else {}
    roles = roles_from_plan(conductor_plan)
    pipeline = handoff_pipeline(run_dir) or [" -> ".join(roles) if roles else "not recorded"]
    required = REQUIRED_EVIDENCE.get(task_type, ())
    required_statuses = [artifact_status(run_dir, artifact) for artifact in required]
    verdict = acceptance.get("verdict", "UNKNOWN") if isinstance(acceptance, dict) else "UNKNOWN"

    lines = [
        "# Run Summary",
        "",
        f"- Run: `{run_dir.name}`",
        f"- Task type: `{task_type}`",
        f"- Final verdict: `{verdict}`",
        f"- Caps: `max_agents={caps.get('max_agents', 'unknown')}`, `max_parallel={caps.get('max_parallel', 'unknown')}`, `max_iters={caps.get('max_iters', 'unknown')}`",
        "",
        "## Role Pipeline",
    ]
    lines.extend(f"- {item}" for item in pipeline)
    lines.extend(["", "## Deterministic Gates"])
    lines.extend(markdown_table(["Gate", "Status", "Detail"], [[row["gate"], row["status"], row["detail"]] for row in gate_rows(run_dir, conductor_plan, plan_check, plan_check_error, acceptance, acceptance_error)]))
    lines.extend(["", "## Required Artifacts"])
    lines.extend(markdown_table(["Artifact", "Status", "Reason"], [[row["artifact"], row["status"], row["reason"]] for row in required_statuses]))
    lines.extend(["", "## Acceptance"])
    if isinstance(acceptance, dict):
        lines.append(f"- Verdict: `{verdict}`")
        violations = acceptance.get("violations", [])
        lines.append(f"- Violations: `{len(violations) if isinstance(violations, list) else 'unknown'}`")
    else:
        lines.append(f"- Acceptance artifact unreadable: `{acceptance_error or 'missing'}`")
    return "\n".join(lines) + "\n"


def write_run_summary(run_dir: Path) -> Path:
    path = run_dir / RUN_SUMMARY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_summary(run_dir), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write artifacts/run-summary.md for a MAW run.")
    parser.add_argument("run")
    args = parser.parse_args(argv)
    path = write_run_summary(Path(args.run))
    result = {"check": "run_report", "run": args.run, "summary": str(path), "passed": path.is_file()}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
