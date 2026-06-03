#!/usr/bin/env python3
"""Hard anti-gaming gates for closed-loop WILDS evaluation runs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PROTOCOL = "artifacts/evaluation-protocol.json"
PROTOCOL_SHA = "artifacts/evaluation-protocol.sha256"
ROLE_ACCESS_LEDGER = "artifacts/role-access-ledger.json"
CANDIDATE_LEDGER = "artifacts/candidate-ledger.json"
VAL_QUERY_LEDGER = "artifacts/val-query-ledger.json"
FINAL_REPORT_JSON = "artifacts/final-evaluation-report.json"
PREDICTION_DISTRIBUTION = "artifacts/prediction-distribution-check.json"

ITERATING_ROLES = {
    "worker",
    "critic",
    "leakage_auditor",
    "data_quality_auditor",
    "baseline_enforcer",
    "overfitting_checker",
    "calibration_checker",
    "reproducibility_checker",
    "dependency_mapper",
}
TEST_SCORE_ACTIONS = {"score", "scored", "evaluate", "evaluated", "final_score", "sealed_test_score"}


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def load_json(path: Path) -> tuple[Any | None, list[dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [violation("missing_artifact", f"missing artifact: {path}", artifact=str(path))]
    except (OSError, json.JSONDecodeError) as exc:
        return None, [violation("invalid_artifact", f"invalid artifact: {path}: {exc}", artifact=str(path))]
    if not isinstance(data, dict):
        return None, [violation("invalid_artifact", f"artifact must be a JSON object: {path}", artifact=str(path))]
    return data, []


def protocol_opted_in(run_dir: Path) -> bool:
    protocol, errors = load_json(run_dir / PROTOCOL)
    if errors or not isinstance(protocol, dict):
        return False
    return bool(protocol.get("anti_gaming") is True or protocol.get("check") == "wilds_anti_gaming_protocol")


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_protocol_hash(run_dir: Path) -> tuple[str | None, list[dict[str, Any]]]:
    path = run_dir / PROTOCOL_SHA
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None, [violation("missing_protocol_hash", f"missing protocol hash: {path}", artifact=str(path))]
    except OSError as exc:
        return None, [violation("protocol_hash_read_error", f"could not read protocol hash: {exc}", artifact=str(path))]
    value = text.split()[0] if text else ""
    if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        return None, [violation("invalid_protocol_hash", "protocol hash must be a SHA-256 hex digest", artifact=str(path))]
    return value.lower(), []


def check_protocol_hash(run_dir: Path) -> list[dict[str, Any]]:
    protocol_path = run_dir / PROTOCOL
    if not protocol_path.is_file():
        return [violation("missing_protocol", f"missing evaluation protocol: {protocol_path}", artifact=str(protocol_path))]
    expected, errors = expected_protocol_hash(run_dir)
    if errors:
        return errors
    actual = sha256_bytes(protocol_path)
    if actual != expected:
        return [
            violation(
                "protocol_hash_mismatch",
                "evaluation-protocol.json changed after pre-registration",
                artifact=str(protocol_path),
                expected=expected,
                actual=actual,
            )
        ]
    return []


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def event_split(event: dict[str, Any]) -> str:
    return str(event.get("split", event.get("dataset_split", ""))).lower()


def event_role(event: dict[str, Any]) -> str:
    return str(event.get("role", "")).lower()


def event_action(event: dict[str, Any]) -> str:
    return str(event.get("action", "")).lower()


def event_phase(event: dict[str, Any]) -> str:
    return str(event.get("phase", "")).lower()


def check_sealed_split(run_dir: Path) -> list[dict[str, Any]]:
    ledger, errors = load_json(run_dir / ROLE_ACCESS_LEDGER)
    if errors:
        return errors
    assert isinstance(ledger, dict)
    result: list[dict[str, Any]] = []
    if ledger.get("sealed_test_unreachable_from_iteration") is not True:
        result.append(
            violation(
                "sealed_test_not_structurally_unreachable",
                "role-access ledger must prove the test split is unreachable from iterating code",
                artifact=ROLE_ACCESS_LEDGER,
            )
        )
    events = [event for event in as_list(ledger.get("events")) if isinstance(event, dict)]
    test_events = [event for event in events if event_split(event) == "test"]
    for event in test_events:
        role = event_role(event)
        phase = event_phase(event)
        if role in ITERATING_ROLES or role != "acceptance_gate" or phase not in {"acceptance", "final", "sealed_test"}:
            result.append(
                violation(
                    "sealed_test_access_before_acceptance",
                    "test split was reachable before one-time acceptance scoring",
                    artifact=ROLE_ACCESS_LEDGER,
                    event=event,
                )
            )
    score_events = [event for event in test_events if event_action(event) in TEST_SCORE_ACTIONS]
    if len(score_events) != 1:
        result.append(
            violation(
                "sealed_test_score_count_invalid",
                "sealed test must be scored exactly once",
                artifact=ROLE_ACCESS_LEDGER,
                score_count=len(score_events),
            )
        )
    elif event_role(score_events[0]) != "acceptance_gate":
        result.append(
            violation(
                "sealed_test_scored_by_non_acceptance_role",
                "sealed test score must be produced by acceptance_gate",
                artifact=ROLE_ACCESS_LEDGER,
                event=score_events[0],
            )
        )
    return result


def protocol_threshold(protocol: dict[str, Any], name: str, default: float) -> float:
    thresholds = protocol.get("thresholds")
    if isinstance(thresholds, dict) and isinstance(thresholds.get(name), (int, float)):
        return float(thresholds[name])
    return default


def protocol_budget(protocol: dict[str, Any]) -> int | None:
    budget = protocol.get("iteration_budget")
    if isinstance(budget, dict):
        for key in ("max_val_queries", "max_iterations", "max_iters"):
            value = budget.get(key)
            if isinstance(value, int):
                return value
    for key in ("max_val_queries", "max_iterations", "max_iters"):
        value = protocol.get(key)
        if isinstance(value, int):
            return value
    return None


def check_candidate_ledger(run_dir: Path, protocol: dict[str, Any]) -> list[dict[str, Any]]:
    ledger, errors = load_json(run_dir / CANDIDATE_LEDGER)
    if errors:
        return errors
    assert isinstance(ledger, dict)
    min_lcb_gain = protocol_threshold(protocol, "min_worst_group_lcb_gain", 0.0)
    result: list[dict[str, Any]] = []
    candidates = [item for item in as_list(ledger.get("candidates")) if isinstance(item, dict)]
    for index, candidate in enumerate(candidates):
        if candidate.get("banked") is not True:
            continue
        gates = candidate.get("orthogonal_gates")
        if not isinstance(gates, dict):
            result.append(violation("banked_candidate_missing_gates", "banked candidate lacks orthogonal gate results", candidate_index=index))
            continue
        failed = [name for name, gate in gates.items() if not (isinstance(gate, dict) and gate.get("passed") is True)]
        if failed:
            result.append(
                violation(
                    "banked_candidate_failed_gate",
                    "banked candidate did not clear all orthogonal gates",
                    candidate_index=index,
                    failed_gates=failed,
                )
            )
        lcb_gain = candidate.get("worst_group_lcb_gain")
        if not isinstance(lcb_gain, (int, float)) or float(lcb_gain) < min_lcb_gain:
            result.append(
                violation(
                    "banked_gain_below_lcb_threshold",
                    "banked gain did not clear the pre-registered worst-group lower confidence bound threshold",
                    candidate_index=index,
                    value=lcb_gain,
                    threshold=min_lcb_gain,
                )
            )
        if candidate.get("gain_inside_bootstrap_ci") is True or candidate.get("ci_overlap") is True:
            result.append(
                violation(
                    "banked_sub_ci_gain",
                    "gain inside the bootstrap CI counts as zero and cannot be banked",
                    candidate_index=index,
                )
            )
    return result


def check_prediction_distribution(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / PREDICTION_DISTRIBUTION
    if not path.exists():
        return []
    data, errors = load_json(path)
    if errors:
        return errors
    assert isinstance(data, dict)
    if data.get("passed") is not True:
        return [
            violation(
                "prediction_distribution_degenerate",
                "prediction distribution degeneracy check failed",
                artifact=PREDICTION_DISTRIBUTION,
                reason=data.get("reason", data.get("problems", "")),
            )
        ]
    return []


def check_val_budget(run_dir: Path, protocol: dict[str, Any]) -> list[dict[str, Any]]:
    max_queries = protocol_budget(protocol)
    if max_queries is None:
        return [violation("missing_val_query_budget", "evaluation protocol must declare a validation query budget", artifact=PROTOCOL)]
    ledger, errors = load_json(run_dir / VAL_QUERY_LEDGER)
    if errors:
        return errors
    assert isinstance(ledger, dict)
    queries = as_list(ledger.get("queries"))
    query_count = ledger.get("query_count", len(queries))
    if not isinstance(query_count, int):
        query_count = len(queries)
    if query_count > max_queries:
        return [
            violation(
                "val_query_budget_overrun",
                "validation query budget was exceeded",
                artifact=VAL_QUERY_LEDGER,
                query_count=query_count,
                max_queries=max_queries,
            )
        ]
    return []


def check_generalization_gap(run_dir: Path, protocol: dict[str, Any]) -> list[dict[str, Any]]:
    report, errors = load_json(run_dir / FINAL_REPORT_JSON)
    if errors:
        return errors
    assert isinstance(report, dict)
    gap = report.get("val_to_test_generalization_gap", report.get("val_to_test_gap"))
    threshold = protocol_threshold(protocol, "max_generalization_gap", 0.05)
    if not isinstance(gap, (int, float)):
        return [violation("missing_generalization_gap", "final report must include val-to-test generalization gap", artifact=FINAL_REPORT_JSON)]
    if abs(float(gap)) > threshold:
        return [
            violation(
                "generalization_gap_over_bound",
                "val-to-test generalization gap exceeds the pre-registered bound",
                artifact=FINAL_REPORT_JSON,
                value=float(gap),
                threshold=threshold,
            )
        ]
    return []


def check_run(run_dir: Path) -> dict[str, Any]:
    if not protocol_opted_in(run_dir):
        return {
            "check": "anti_gaming_hard_gates",
            "applicable": False,
            "passed": True,
            "violations": [],
            "reason": "no anti-gaming evaluation protocol",
        }

    protocol, protocol_errors = load_json(run_dir / PROTOCOL)
    violations = list(protocol_errors)
    if not isinstance(protocol, dict):
        protocol = {}
    if not protocol_errors:
        violations.extend(check_protocol_hash(run_dir))
        violations.extend(check_sealed_split(run_dir))
        violations.extend(check_candidate_ledger(run_dir, protocol))
        violations.extend(check_prediction_distribution(run_dir))
        violations.extend(check_val_budget(run_dir, protocol))
        violations.extend(check_generalization_gap(run_dir, protocol))

    return {
        "check": "anti_gaming_hard_gates",
        "applicable": True,
        "passed": not violations,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hard anti-gaming gates for closed-loop WILDS evaluation.")
    parser.add_argument("run")
    args = parser.parse_args(argv)
    result = check_run(Path(args.run))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
