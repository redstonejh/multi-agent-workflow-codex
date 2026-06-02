"""Deterministic checks for toy ML problem runs."""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any


def metric_at_least(metrics: dict[str, float], name: str, minimum: float) -> dict[str, Any]:
    value = metrics.get(name)
    passed = value is not None and value >= minimum
    return {"check": f"{name}_at_least", "metric": name, "value": value, "minimum": minimum, "passed": passed}


def metric_at_most(metrics: dict[str, float], name: str, maximum: float) -> dict[str, Any]:
    value = metrics.get(name)
    passed = value is not None and value <= maximum
    return {"check": f"{name}_at_most", "metric": name, "value": value, "maximum": maximum, "passed": passed}


def no_split_overlap(train_ids: list[int], test_ids: list[int]) -> dict[str, Any]:
    overlap = sorted(set(train_ids) & set(test_ids))
    return {"check": "no_split_overlap", "overlap": overlap, "passed": not overlap}


def split_ratio(train_ids: list[int], test_ids: list[int], expected: float, tolerance: float = 0.05) -> dict[str, Any]:
    total = len(train_ids) + len(test_ids)
    actual = len(train_ids) / total if total else math.nan
    passed = total > 0 and abs(actual - expected) <= tolerance
    return {
        "check": "split_ratio",
        "train_count": len(train_ids),
        "test_count": len(test_ids),
        "expected_train_ratio": expected,
        "actual_train_ratio": round(actual, 6) if total else None,
        "tolerance": tolerance,
        "passed": passed,
    }


def seed_matches(actual: int, expected: int) -> dict[str, Any]:
    return {"check": "seed_matches", "actual": actual, "expected": expected, "passed": actual == expected}


def no_feature_target_leakage(feature_names: list[str], target_name: str = "target") -> dict[str, Any]:
    lowered = {name.lower() for name in feature_names}
    leaked = sorted(name for name in lowered if name in {target_name.lower(), "label", "y"})
    return {"check": "no_feature_target_leakage", "leaked_features": leaked, "passed": not leaked}


def labels_not_shuffled(result: dict[str, Any]) -> dict[str, Any]:
    shuffled = bool(result.get("labels_shuffled", False))
    return {"check": "labels_not_shuffled", "labels_shuffled": shuffled, "passed": not shuffled}


def preprocessing_fit_on_train_only(result: dict[str, Any]) -> dict[str, Any]:
    preprocessing = result.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return {"check": "preprocessing_fit_on_train_only", "fit_scope": "not_declared", "passed": True}
    fit_scope = str(preprocessing.get("fit_scope", "train"))
    return {"check": "preprocessing_fit_on_train_only", "fit_scope": fit_scope, "passed": fit_scope == "train"}


def baseline_comparison(
    metrics: dict[str, float],
    model_metric: str = "model_score",
    baseline_metric: str = "baseline_score",
    min_improvement: float = 0.0,
    direction: str = "higher",
) -> dict[str, Any]:
    missing = _missing(metrics, [model_metric, baseline_metric])
    if missing:
        return {
            "check": "baseline_comparison",
            "passed": False,
            "status": "invalid",
            "missing_metrics": missing,
            "reasons": [f"missing required metrics: {', '.join(missing)}"],
        }
    model = float(metrics[model_metric])
    baseline = float(metrics[baseline_metric])
    if direction == "higher":
        improvement = model - baseline
    elif direction == "lower":
        improvement = baseline - model
    else:
        return {
            "check": "baseline_comparison",
            "passed": False,
            "status": "invalid",
            "reasons": [f"unknown direction: {direction}"],
        }
    passed = improvement >= min_improvement
    return {
        "check": "baseline_comparison",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "model_metric": model_metric,
        "baseline_metric": baseline_metric,
        "model_value": model,
        "baseline_value": baseline,
        "direction": direction,
        "improvement": round(improvement, 6),
        "min_improvement": min_improvement,
        "reasons": [] if passed else [f"improvement {improvement:.6f} is below {min_improvement:.6f}"],
    }


def expected_calibration_error(confidences: list[float], correct: list[bool], bins: int = 10) -> dict[str, Any]:
    if len(confidences) != len(correct) or not confidences:
        return {
            "check": "expected_calibration_error",
            "passed": False,
            "status": "invalid",
            "reasons": ["confidences and correct must be non-empty arrays of equal length"],
        }
    if bins <= 0:
        return {"check": "expected_calibration_error", "passed": False, "status": "invalid", "reasons": ["bins must be positive"]}
    if any(confidence < 0.0 or confidence > 1.0 for confidence in confidences):
        return {"check": "expected_calibration_error", "passed": False, "status": "invalid", "reasons": ["confidences must be in [0, 1]"]}

    total = len(confidences)
    ece = 0.0
    bin_summaries: list[dict[str, Any]] = []
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        selected = [
            item_index
            for item_index, confidence in enumerate(confidences)
            if (confidence >= lower and (confidence < upper or (index == bins - 1 and confidence <= upper)))
        ]
        if not selected:
            continue
        avg_confidence = sum(confidences[item] for item in selected) / len(selected)
        accuracy = sum(1.0 if correct[item] else 0.0 for item in selected) / len(selected)
        contribution = (len(selected) / total) * abs(accuracy - avg_confidence)
        ece += contribution
        bin_summaries.append(
            {
                "lower": round(lower, 6),
                "upper": round(upper, 6),
                "count": len(selected),
                "avg_confidence": round(avg_confidence, 6),
                "accuracy": round(accuracy, 6),
                "contribution": round(contribution, 6),
            }
        )
    return {
        "check": "expected_calibration_error",
        "passed": True,
        "status": "computed",
        "ece": round(ece, 6),
        "bins": bins,
        "bin_summaries": bin_summaries,
    }


def calibration_check(data: dict[str, Any], max_ece: float = 0.08, bins: int = 10) -> dict[str, Any]:
    confidences = data.get("confidences")
    correct = data.get("correct")
    if not isinstance(confidences, list) or not isinstance(correct, list):
        return {
            "check": "calibration",
            "passed": False,
            "status": "invalid",
            "reasons": ["required arrays: confidences, correct"],
        }
    result = expected_calibration_error([float(item) for item in confidences], [bool(item) for item in correct], bins)
    if not result["passed"]:
        result["check"] = "calibration"
        return result
    passed = result["ece"] <= max_ece
    result.update({
        "check": "calibration",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "max_ece": max_ece,
        "reasons": [] if passed else [f"ECE {result['ece']:.6f} exceeds {max_ece:.6f}"],
    })
    return result


def reproducibility_check(data: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if "seed" in data and "expected_seed" in data:
        checks.append(seed_matches(int(data["seed"]), int(data["expected_seed"])))
    else:
        checks.append({"check": "seed_present", "passed": False, "reasons": ["seed and expected_seed are required"]})
    if "deterministic" in data:
        checks.append({"check": "deterministic_flag", "passed": bool(data["deterministic"])})
    else:
        checks.append({"check": "deterministic_flag", "passed": False, "reasons": ["deterministic flag is required"]})
    if "config_hash" in data and "expected_config_hash" in data:
        checks.append({
            "check": "config_hash_matches",
            "actual": data["config_hash"],
            "expected": data["expected_config_hash"],
            "passed": data["config_hash"] == data["expected_config_hash"],
        })
    return {"check": "reproducibility", "passed": all(check["passed"] for check in checks), "checks": checks}


def data_quality_check(data: dict[str, Any], max_missing_rate: float = 0.0, max_duplicate_rate: float = 0.0) -> dict[str, Any]:
    row_count = int(data.get("row_count", 0))
    missing_values = data.get("missing_values", {})
    duplicate_rows = int(data.get("duplicate_rows", 0))
    if row_count <= 0 or not isinstance(missing_values, dict):
        return {
            "check": "data_quality",
            "passed": False,
            "status": "invalid",
            "reasons": ["row_count must be positive and missing_values must be an object"],
        }
    total_missing = sum(int(value) for value in missing_values.values())
    missing_rate = total_missing / row_count
    duplicate_rate = duplicate_rows / row_count
    reasons = []
    if missing_rate > max_missing_rate:
        reasons.append(f"missing_rate {missing_rate:.6f} exceeds {max_missing_rate:.6f}")
    if duplicate_rate > max_duplicate_rate:
        reasons.append(f"duplicate_rate {duplicate_rate:.6f} exceeds {max_duplicate_rate:.6f}")
    return {
        "check": "data_quality",
        "passed": not reasons,
        "status": "pass" if not reasons else "fail",
        "row_count": row_count,
        "total_missing": total_missing,
        "missing_rate": round(missing_rate, 6),
        "duplicate_rows": duplicate_rows,
        "duplicate_rate": round(duplicate_rate, 6),
        "thresholds": {"max_missing_rate": max_missing_rate, "max_duplicate_rate": max_duplicate_rate},
        "reasons": reasons,
    }


def _float_list(values: Any, name: str) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} must be a non-empty JSON array")
    scores = [float(value) for value in values]
    if any(not math.isfinite(score) for score in scores):
        raise ValueError(f"{name} must contain only finite numbers")
    return scores


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _population_variance(values: list[float]) -> float:
    if not values:
        return math.nan
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _default_chance_score(problem_type: str, direction: str, class_count: int) -> float:
    if problem_type == "classification":
        return 1.0 / class_count
    if problem_type == "regression":
        return 0.0 if direction == "higher" else 1.0
    raise ValueError(f"unknown problem_type: {problem_type}")


def shuffled_label_check(
    problem_type: str,
    real_score: float,
    shuffled_scores: list[float],
    class_count: int = 2,
    chance_score: float | None = None,
    tolerance: float = 0.05,
    min_real_margin: float = 0.0,
    direction: str = "higher",
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "problem_type": problem_type,
        "direction": direction,
        "real_score": real_score,
        "shuffled_scores": shuffled_scores,
    }
    thresholds: dict[str, Any] = {
        "tolerance": tolerance,
        "min_real_margin": min_real_margin,
    }
    reasons: list[str] = []

    if direction not in {"higher", "lower"}:
        return {
            "check": "shuffled_label",
            "passed": False,
            "status": "invalid",
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": [f"unknown direction: {direction}"],
        }
    if class_count <= 0:
        return {
            "check": "shuffled_label",
            "passed": False,
            "status": "invalid",
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": ["class_count must be positive"],
        }
    if tolerance < 0:
        reasons.append("tolerance must be non-negative")
    if min_real_margin < 0:
        reasons.append("min_real_margin must be non-negative")
    if chance_score is not None and not math.isfinite(float(chance_score)):
        reasons.append("chance_score must be finite")
    if not math.isfinite(tolerance):
        reasons.append("tolerance must be finite")
    if not math.isfinite(min_real_margin):
        reasons.append("min_real_margin must be finite")
    if not math.isfinite(real_score):
        reasons.append("real_score must be finite")
    if not shuffled_scores:
        reasons.append("shuffled_scores must be non-empty")
    if any(not math.isfinite(score) for score in shuffled_scores):
        reasons.append("shuffled_scores must contain only finite numbers")
    if reasons:
        return {
            "check": "shuffled_label",
            "passed": False,
            "status": "invalid",
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": reasons,
        }

    chance = float(chance_score) if chance_score is not None else _default_chance_score(problem_type, direction, class_count)
    shuffled_mean = _mean(shuffled_scores)
    shuffled_variance = _population_variance(shuffled_scores)
    metrics.update(
        {
            "chance_score": chance,
            "shuffled_mean": round(shuffled_mean, 6),
            "shuffled_variance": round(shuffled_variance, 6),
            "shuffled_std": round(math.sqrt(shuffled_variance), 6),
            "shuffled_min": min(shuffled_scores),
            "shuffled_max": max(shuffled_scores),
        }
    )

    if direction == "higher":
        real_threshold = chance + min_real_margin
        shuffled_threshold = chance + tolerance
        real_ok = real_score >= real_threshold
        shuffled_ok = max(shuffled_scores) <= shuffled_threshold
        thresholds.update(
            {
                "chance_score": chance,
                "class_count": class_count if problem_type == "classification" else None,
                "real_minimum": real_threshold,
                "shuffled_maximum": shuffled_threshold,
            }
        )
        if not real_ok:
            reasons.append(f"real_score {real_score:.6f} is below required {real_threshold:.6f}")
        if not shuffled_ok:
            reasons.append(f"shuffled score max {max(shuffled_scores):.6f} exceeds allowed {shuffled_threshold:.6f}")
    else:
        real_threshold = chance - min_real_margin
        shuffled_threshold = chance - tolerance
        real_ok = real_score <= real_threshold
        shuffled_ok = min(shuffled_scores) >= shuffled_threshold
        thresholds.update(
            {
                "chance_score": chance,
                "class_count": class_count if problem_type == "classification" else None,
                "real_maximum": real_threshold,
                "shuffled_minimum": shuffled_threshold,
            }
        )
        if not real_ok:
            reasons.append(f"real_score {real_score:.6f} is above required {real_threshold:.6f}")
        if not shuffled_ok:
            reasons.append(f"shuffled score min {min(shuffled_scores):.6f} is below allowed {shuffled_threshold:.6f}")

    passed = real_ok and shuffled_ok
    return {
        "check": "shuffled_label",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "metrics": metrics,
        "thresholds": thresholds,
        "reasons": [] if passed else reasons,
    }


def multi_seed_check(
    scores: list[float],
    min_score: float = 0.0,
    max_score: float | None = None,
    max_variance: float = 0.0004,
    min_seeds: int = 2,
    direction: str = "higher",
    metric_name: str = "score",
) -> dict[str, Any]:
    thresholds: dict[str, Any] = {
        "direction": direction,
        "max_variance": max_variance,
        "min_seeds": min_seeds,
    }
    reasons: list[str] = []
    if direction not in {"higher", "lower"}:
        reasons.append(f"unknown direction: {direction}")
    if max_variance < 0:
        reasons.append("max_variance must be non-negative")
    if not math.isfinite(max_variance):
        reasons.append("max_variance must be finite")
    if not math.isfinite(min_score):
        reasons.append("min_score must be finite")
    if max_score is not None and not math.isfinite(max_score):
        reasons.append("max_score must be finite")
    if min_seeds <= 0:
        reasons.append("min_seeds must be positive")
    if len(scores) < min_seeds:
        reasons.append(f"seed count {len(scores)} is below required {min_seeds}")
    if any(not math.isfinite(score) for score in scores):
        reasons.append("scores must contain only finite numbers")
    if direction == "lower" and max_score is None:
        reasons.append("max_score is required when direction is lower")

    if direction == "higher":
        thresholds["min_score"] = min_score
    else:
        thresholds["max_score"] = max_score

    if reasons:
        return {
            "check": "multi_seed",
            "passed": False,
            "status": "invalid",
            "metrics": {"metric_name": metric_name, "scores": scores, "seed_count": len(scores)},
            "thresholds": thresholds,
            "reasons": reasons,
        }

    mean = _mean(scores)
    variance = _population_variance(scores)
    std = math.sqrt(variance)
    metrics = {
        "metric_name": metric_name,
        "scores": scores,
        "seed_count": len(scores),
        "mean": round(mean, 6),
        "variance": round(variance, 6),
        "std": round(std, 6),
        "min": min(scores),
        "max": max(scores),
    }

    if direction == "higher":
        floor_ok = all(score >= min_score for score in scores)
        if not floor_ok:
            reasons.append(f"one or more seeds are below min_score {min_score:.6f}")
    else:
        ceiling = float(max_score)
        floor_ok = all(score <= ceiling for score in scores)
        if not floor_ok:
            reasons.append(f"one or more seeds exceed max_score {ceiling:.6f}")

    variance_ok = variance <= max_variance
    if not variance_ok:
        reasons.append(f"variance {variance:.6f} exceeds {max_variance:.6f}")

    passed = floor_ok and variance_ok
    return {
        "check": "multi_seed",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "metrics": metrics,
        "thresholds": thresholds,
        "reasons": [] if passed else reasons,
    }


def _missing(metrics: dict[str, float], names: list[str]) -> list[str]:
    return [name for name in names if name not in metrics or metrics[name] is None]


def classification_fit_diagnosis(
    metrics: dict[str, float],
    high_train_score: float = 0.9,
    max_generalization_gap: float = 0.12,
    target_score: float = 0.7,
) -> dict[str, Any]:
    required = ["train_score", "validation_score", "test_score"]
    missing = _missing(metrics, required)
    thresholds = {
        "high_train_score": high_train_score,
        "max_generalization_gap": max_generalization_gap,
        "target_score": target_score,
    }
    if missing:
        return {
            "check": "fit_diagnosis",
            "problem_type": "classification",
            "status": "invalid",
            "passed": False,
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": [f"missing required metrics: {', '.join(missing)}"],
            "missing_metrics": missing,
        }

    train = float(metrics["train_score"])
    validation = float(metrics["validation_score"])
    test = float(metrics["test_score"])
    worst_holdout = min(validation, test)
    gap = train - worst_holdout
    reasons: list[str] = []
    status = "healthy"

    if train >= high_train_score and gap > max_generalization_gap:
        status = "overfit"
        reasons.append(
            f"train_score {train:.6f} is high but holdout gap {gap:.6f} exceeds {max_generalization_gap:.6f}"
        )
    elif train < target_score and validation < target_score and test < target_score:
        status = "underfit"
        reasons.append(
            f"train/validation/test scores are all below target_score {target_score:.6f}"
        )

    return {
        "check": "fit_diagnosis",
        "problem_type": "classification",
        "status": status,
        "passed": status == "healthy",
        "metrics": {
            "train_score": train,
            "validation_score": validation,
            "test_score": test,
            "worst_holdout_score": worst_holdout,
            "generalization_gap": round(gap, 6),
        },
        "thresholds": thresholds,
        "reasons": reasons,
    }


def regression_fit_diagnosis(
    metrics: dict[str, float],
    max_error_ratio: float = 1.75,
    poor_error: float = 1.0,
) -> dict[str, Any]:
    required = ["train_error", "validation_error", "test_error"]
    missing = _missing(metrics, required)
    thresholds = {
        "max_error_ratio": max_error_ratio,
        "poor_error": poor_error,
    }
    if missing:
        return {
            "check": "fit_diagnosis",
            "problem_type": "regression",
            "status": "invalid",
            "passed": False,
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": [f"missing required metrics: {', '.join(missing)}"],
            "missing_metrics": missing,
        }

    train = float(metrics["train_error"])
    validation = float(metrics["validation_error"])
    test = float(metrics["test_error"])
    if train <= 0:
        return {
            "check": "fit_diagnosis",
            "problem_type": "regression",
            "status": "invalid",
            "passed": False,
            "metrics": metrics,
            "thresholds": thresholds,
            "reasons": ["train_error must be positive"],
        }

    worst_holdout = max(validation, test)
    ratio = worst_holdout / train
    reasons: list[str] = []
    status = "healthy"

    if ratio > max_error_ratio:
        status = "overfit"
        reasons.append(
            f"worst holdout error ratio {ratio:.6f} exceeds {max_error_ratio:.6f}"
        )
    elif train > poor_error and validation > poor_error and test > poor_error:
        status = "underfit"
        reasons.append(
            f"train/validation/test errors all exceed poor_error {poor_error:.6f}"
        )

    return {
        "check": "fit_diagnosis",
        "problem_type": "regression",
        "status": status,
        "passed": status == "healthy",
        "metrics": {
            "train_error": train,
            "validation_error": validation,
            "test_error": test,
            "worst_holdout_error": worst_holdout,
            "holdout_train_error_ratio": round(ratio, 6),
        },
        "thresholds": thresholds,
        "reasons": reasons,
    }


def fit_diagnosis(problem_type: str, metrics: dict[str, float], thresholds: dict[str, float] | None = None) -> dict[str, Any]:
    thresholds = thresholds or {}
    if problem_type == "classification":
        return classification_fit_diagnosis(
            metrics,
            high_train_score=float(thresholds.get("high_train_score", 0.9)),
            max_generalization_gap=float(thresholds.get("max_generalization_gap", 0.12)),
            target_score=float(thresholds.get("target_score", 0.7)),
        )
    if problem_type == "regression":
        return regression_fit_diagnosis(
            metrics,
            max_error_ratio=float(thresholds.get("max_error_ratio", 1.75)),
            poor_error=float(thresholds.get("poor_error", 1.0)),
        )
    return {
        "check": "fit_diagnosis",
        "problem_type": problem_type,
        "status": "invalid",
        "passed": False,
        "metrics": metrics,
        "thresholds": thresholds,
        "reasons": [f"unknown problem_type: {problem_type}"],
    }


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    checks = [
        seed_matches(int(result["seed"]), int(result["expected_seed"])),
        no_split_overlap(result["split"]["train_ids"], result["split"]["test_ids"]),
        split_ratio(result["split"]["train_ids"], result["split"]["test_ids"], float(result["split"]["expected_train_ratio"])),
        no_feature_target_leakage(result["features"], result.get("target", "target")),
        labels_not_shuffled(result),
        preprocessing_fit_on_train_only(result),
    ]
    for check in result.get("metric_checks", []):
        if check["direction"] == "at_least":
            checks.append(metric_at_least(result["metrics"], check["name"], float(check["threshold"])))
        elif check["direction"] == "at_most":
            checks.append(metric_at_most(result["metrics"], check["name"], float(check["threshold"])))
        else:
            checks.append({"check": check["name"], "passed": False, "error": f"unknown direction {check['direction']}"})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


VALIDATOR_EVIDENCE = {
    "leakage": "artifacts/leakage-audit.json",
    "baseline": "artifacts/baseline-comparison.json",
    "multi_seed": "artifacts/multi-seed-stability.json",
    "shuffled_label": "artifacts/shuffled-label-check.json",
}


def artifact_passed(data: Any) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "artifact JSON must be an object"
    if isinstance(data.get("passed"), bool):
        return bool(data["passed"]), "passed is true" if data["passed"] else "passed is false"
    acceptance = data.get("acceptance")
    if isinstance(acceptance, dict) and isinstance(acceptance.get("passed"), bool):
        return bool(acceptance["passed"]), "acceptance.passed is true" if acceptance["passed"] else "acceptance.passed is false"
    checks = data.get("checks")
    if isinstance(checks, list) and checks and all(isinstance(item, dict) and isinstance(item.get("passed"), bool) for item in checks):
        passed = all(bool(item["passed"]) for item in checks)
        return passed, "all checks passed" if passed else "one or more checks failed"
    if isinstance(data.get("ok"), bool):
        return bool(data["ok"]), "ok is true" if data["ok"] else "ok is false"
    status = data.get("status")
    if isinstance(status, str) and status.lower() in {"pass", "passed", "ok"}:
        return True, f"status is {status}"
    if isinstance(status, str) and status.lower() in {"fail", "failed", "invalid", "error"}:
        return False, f"status is {status}"
    return False, "artifact does not report pass/fail"


def ml_validator_artifact(evidence: dict[str, tuple[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    normalized: dict[str, dict[str, Any]] = {}
    for name, expected_artifact in VALIDATOR_EVIDENCE.items():
        artifact, data = evidence[name]
        passed, reason = artifact_passed(data)
        item = {
            "check": name,
            "artifact": artifact,
            "expected_artifact": expected_artifact,
            "passed": passed,
            "reason": reason,
        }
        checks.append(item)
        normalized[name] = {
            "artifact": artifact,
            "expected_artifact": expected_artifact,
            "passed": passed,
            "reason": reason,
        }
    return {
        "check": "ml_validator",
        "schema_version": 1,
        "passed": all(item["passed"] for item in checks),
        "required_evidence": list(VALIDATOR_EVIDENCE),
        "evidence": normalized,
        "checks": checks,
    }


MUTATION_NAMES = ("leaky_feature", "shuffled_labels", "train_test_overlap", "preprocessing_fit_full_data")


def plant_mutation(result: dict[str, Any], mutation: str) -> dict[str, Any]:
    planted = copy.deepcopy(result)
    if mutation == "leaky_feature":
        features = list(planted.get("features", []))
        target = str(planted.get("target", "target"))
        if target not in features:
            features.append(target)
        planted["features"] = features
    elif mutation == "shuffled_labels":
        planted["labels_shuffled"] = True
    elif mutation == "train_test_overlap":
        train_ids = planted["split"]["train_ids"]
        if train_ids:
            planted["split"]["test_ids"] = [train_ids[0], *list(planted["split"]["test_ids"])]
    elif mutation == "preprocessing_fit_full_data":
        planted["preprocessing"] = {"fit_scope": "full_data"}
    else:
        raise ValueError(f"unknown mutation: {mutation}")
    return planted


def regression_resistance_artifact(result: dict[str, Any]) -> dict[str, Any]:
    clean = validate_result(result)
    mutations: list[dict[str, Any]] = []
    for mutation in MUTATION_NAMES:
        mutant = plant_mutation(result, mutation)
        validation = validate_result(mutant)
        failed_checks = [check["check"] for check in validation["checks"] if not check["passed"]]
        caught = clean["passed"] and not validation["passed"]
        mutations.append(
            {
                "name": mutation,
                "planted": True,
                "clean_passed": clean["passed"],
                "mutant_passed": validation["passed"],
                "caught": caught,
                "failed_checks": failed_checks,
            }
        )
    caught_count = sum(1 for item in mutations if item["caught"])
    return {
        "check": "regression_resistance",
        "schema_version": 1,
        "passed": clean["passed"] and caught_count == len(mutations),
        "clean": clean,
        "mutations": mutations,
        "summary": {"total": len(mutations), "caught": caught_count},
    }


def load_fit_metrics(args: argparse.Namespace) -> dict[str, float]:
    if args.metrics_json:
        data = json.loads(args.metrics_json)
    elif args.metrics_file:
        data = json.loads(Path(args.metrics_file).read_text(encoding="utf-8"))
    else:
        raise ValueError("provide --metrics-json or --metrics-file")
    if not isinstance(data, dict):
        raise ValueError("metrics must be a JSON object")
    return {str(key): float(value) for key, value in data.items()}


def cmd_validate(args: argparse.Namespace) -> int:
    result = json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    validation = validate_result(result)
    print(json.dumps(validation, indent=2))
    return 0 if validation["passed"] else 1


def cmd_fit_diagnosis(args: argparse.Namespace) -> int:
    try:
        metrics = load_fit_metrics(args)
    except (ValueError, json.JSONDecodeError) as exc:
        diagnosis = {
            "check": "fit_diagnosis",
            "problem_type": args.problem_type,
            "status": "invalid",
            "passed": False,
            "metrics": {},
            "thresholds": {},
            "reasons": [str(exc)],
        }
    else:
        thresholds = {
            key: value
            for key, value in {
                "high_train_score": args.high_train_score,
                "max_generalization_gap": args.max_generalization_gap,
                "target_score": args.target_score,
                "max_error_ratio": args.max_error_ratio,
                "poor_error": args.poor_error,
            }.items()
            if value is not None
        }
        diagnosis = fit_diagnosis(args.problem_type, metrics, thresholds)

    text = json.dumps(diagnosis, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if diagnosis["passed"] else 1


def load_json_arg(inline: str | None, file: str | None) -> dict[str, Any]:
    if inline:
        data = json.loads(inline)
    elif file:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    else:
        raise ValueError("provide inline JSON or a JSON file")
    if not isinstance(data, dict):
        raise ValueError("input JSON must be an object")
    return data


def write_result(result: dict[str, Any], output: str | None) -> int:
    text = json.dumps(result, indent=2)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["passed"] else 1


def cmd_baseline(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.metrics_json, args.metrics_file)
        metrics = {str(key): float(value) for key, value in data.items()}
        result = baseline_comparison(metrics, args.model_metric, args.baseline_metric, args.min_improvement, args.direction)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "baseline_comparison", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_calibration(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = calibration_check(data, args.max_ece, args.bins)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "calibration", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_reproducibility(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = reproducibility_check(data)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "reproducibility", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_data_quality(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = data_quality_check(data, args.max_missing_rate, args.max_duplicate_rate)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "data_quality", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_shuffled_label(args: argparse.Namespace) -> int:
    try:
        if args.data_json or args.data_file:
            data = load_json_arg(args.data_json, args.data_file)
            problem_type = str(data["problem_type"])
            real_score = float(data["real_score"])
            shuffled_scores = _float_list(data["shuffled_scores"], "shuffled_scores")
            class_count = int(data.get("class_count", args.class_count))
            chance_score = data.get("chance_score", args.chance_score)
            tolerance = float(data.get("tolerance", args.tolerance))
            min_real_margin = float(data.get("min_real_margin", args.min_real_margin))
            direction = str(data.get("direction", args.direction))
        else:
            if args.problem_type is None or args.real_score is None or args.shuffled_scores_json is None:
                raise ValueError("provide --problem-type, --real-score, and --shuffled-scores-json or a data JSON object")
            problem_type = args.problem_type
            real_score = args.real_score
            shuffled_scores = _float_list(json.loads(args.shuffled_scores_json), "shuffled_scores")
            class_count = args.class_count
            chance_score = args.chance_score
            tolerance = args.tolerance
            min_real_margin = args.min_real_margin
            direction = args.direction

        result = shuffled_label_check(
            problem_type=problem_type,
            real_score=real_score,
            shuffled_scores=shuffled_scores,
            class_count=class_count,
            chance_score=None if chance_score is None else float(chance_score),
            tolerance=tolerance,
            min_real_margin=min_real_margin,
            direction=direction,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {"check": "shuffled_label", "passed": False, "status": "invalid", "metrics": {}, "thresholds": {}, "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_multi_seed(args: argparse.Namespace) -> int:
    try:
        if args.data_json or args.data_file:
            data = load_json_arg(args.data_json, args.data_file)
            scores = _float_list(data["scores"], "scores")
            min_score = float(data.get("min_score", args.min_score))
            max_score_value = data.get("max_score", args.max_score)
            max_score = None if max_score_value is None else float(max_score_value)
            max_variance = float(data.get("max_variance", args.max_variance))
            min_seeds = int(data.get("min_seeds", args.min_seeds))
            direction = str(data.get("direction", args.direction))
            metric_name = str(data.get("metric_name", args.metric_name))
        else:
            if args.scores_json is None:
                raise ValueError("provide --scores-json or a data JSON object")
            scores = _float_list(json.loads(args.scores_json), "scores")
            min_score = args.min_score
            max_score = args.max_score
            max_variance = args.max_variance
            min_seeds = args.min_seeds
            direction = args.direction
            metric_name = args.metric_name

        result = multi_seed_check(
            scores=scores,
            min_score=min_score,
            max_score=max_score,
            max_variance=max_variance,
            min_seeds=min_seeds,
            direction=direction,
            metric_name=metric_name,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {"check": "multi_seed", "passed": False, "status": "invalid", "metrics": {}, "thresholds": {}, "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_validator(args: argparse.Namespace) -> int:
    try:
        evidence = {
            "leakage": (args.leakage_file, json.loads(Path(args.leakage_file).read_text(encoding="utf-8"))),
            "baseline": (args.baseline_file, json.loads(Path(args.baseline_file).read_text(encoding="utf-8"))),
            "multi_seed": (args.multi_seed_file, json.loads(Path(args.multi_seed_file).read_text(encoding="utf-8"))),
            "shuffled_label": (args.shuffled_label_file, json.loads(Path(args.shuffled_label_file).read_text(encoding="utf-8"))),
        }
        result = ml_validator_artifact(evidence)
    except (OSError, json.JSONDecodeError) as exc:
        result = {
            "check": "ml_validator",
            "schema_version": 1,
            "passed": False,
            "required_evidence": list(VALIDATOR_EVIDENCE),
            "evidence": {},
            "checks": [],
            "reasons": [str(exc)],
        }
    return write_result(result, args.output)


def cmd_regression_resistance(args: argparse.Namespace) -> int:
    try:
        result_data = json.loads(Path(args.result_file).read_text(encoding="utf-8"))
        if not isinstance(result_data, dict):
            raise ValueError("result JSON must be an object")
        result = regression_resistance_artifact(result_data)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {
            "check": "regression_resistance",
            "schema_version": 1,
            "passed": False,
            "clean": {"passed": False, "checks": []},
            "mutations": [],
            "summary": {"total": 0, "caught": 0},
            "reasons": [str(exc)],
        }
    return write_result(result, args.output)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {
        "validate",
        "fit-diagnosis",
        "baseline",
        "calibration",
        "reproducibility",
        "data-quality",
        "shuffled-label",
        "multi-seed",
        "validator",
        "regression-resistance",
        "-h",
        "--help",
    }
    if argv and argv[0] not in commands:
        argv = ["validate", *argv]

    parser = argparse.ArgumentParser(description="Validate toy ML problem result JSON.")
    sub = parser.add_subparsers(dest="command")

    validate = sub.add_parser("validate", help="validate a toy ML result JSON file")
    validate.add_argument("result_json")
    validate.set_defaults(func=cmd_validate)

    fit = sub.add_parser("fit-diagnosis", help="diagnose overfitting or underfitting")
    fit.add_argument("--problem-type", required=True, choices=["classification", "regression"])
    fit.add_argument("--metrics-json")
    fit.add_argument("--metrics-file")
    fit.add_argument("--output")
    fit.add_argument("--high-train-score", type=float)
    fit.add_argument("--max-generalization-gap", type=float)
    fit.add_argument("--target-score", type=float)
    fit.add_argument("--max-error-ratio", type=float)
    fit.add_argument("--poor-error", type=float)
    fit.set_defaults(func=cmd_fit_diagnosis)

    baseline = sub.add_parser("baseline", help="compare a model metric with a baseline metric")
    baseline.add_argument("--metrics-json")
    baseline.add_argument("--metrics-file")
    baseline.add_argument("--model-metric", default="model_score")
    baseline.add_argument("--baseline-metric", default="baseline_score")
    baseline.add_argument("--min-improvement", type=float, default=0.0)
    baseline.add_argument("--direction", choices=["higher", "lower"], default="higher")
    baseline.add_argument("--output")
    baseline.set_defaults(func=cmd_baseline)

    calibration = sub.add_parser("calibration", help="compute and validate expected calibration error")
    calibration.add_argument("--data-json")
    calibration.add_argument("--data-file")
    calibration.add_argument("--max-ece", type=float, default=0.08)
    calibration.add_argument("--bins", type=int, default=10)
    calibration.add_argument("--output")
    calibration.set_defaults(func=cmd_calibration)

    reproducibility = sub.add_parser("reproducibility", help="validate seed and deterministic run metadata")
    reproducibility.add_argument("--data-json")
    reproducibility.add_argument("--data-file")
    reproducibility.add_argument("--output")
    reproducibility.set_defaults(func=cmd_reproducibility)

    quality = sub.add_parser("data-quality", help="validate basic missingness and duplicate-rate thresholds")
    quality.add_argument("--data-json")
    quality.add_argument("--data-file")
    quality.add_argument("--max-missing-rate", type=float, default=0.0)
    quality.add_argument("--max-duplicate-rate", type=float, default=0.0)
    quality.add_argument("--output")
    quality.set_defaults(func=cmd_data_quality)

    shuffled = sub.add_parser("shuffled-label", help="verify shuffled-label performance collapses to chance or baseline")
    shuffled.add_argument("--data-json")
    shuffled.add_argument("--data-file")
    shuffled.add_argument("--problem-type", choices=["classification", "regression"])
    shuffled.add_argument("--real-score", type=float)
    shuffled.add_argument("--shuffled-scores-json")
    shuffled.add_argument("--class-count", type=int, default=2)
    shuffled.add_argument("--chance-score", type=float)
    shuffled.add_argument("--tolerance", type=float, default=0.05)
    shuffled.add_argument("--min-real-margin", type=float, default=0.0)
    shuffled.add_argument("--direction", choices=["higher", "lower"], default="higher")
    shuffled.add_argument("--output")
    shuffled.set_defaults(func=cmd_shuffled_label)

    multi_seed = sub.add_parser("multi-seed", help="verify metric stability across multiple random seeds")
    multi_seed.add_argument("--data-json")
    multi_seed.add_argument("--data-file")
    multi_seed.add_argument("--scores-json")
    multi_seed.add_argument("--min-score", type=float, default=0.0)
    multi_seed.add_argument("--max-score", type=float)
    multi_seed.add_argument("--max-variance", type=float, default=0.0004)
    multi_seed.add_argument("--min-seeds", type=int, default=2)
    multi_seed.add_argument("--direction", choices=["higher", "lower"], default="higher")
    multi_seed.add_argument("--metric-name", default="score")
    multi_seed.add_argument("--output")
    multi_seed.set_defaults(func=cmd_multi_seed)

    validator = sub.add_parser("validator", help="aggregate required ML invariant evidence into a validator artifact")
    validator.add_argument("--leakage-file", default="artifacts/leakage-audit.json")
    validator.add_argument("--baseline-file", default="artifacts/baseline-comparison.json")
    validator.add_argument("--multi-seed-file", default="artifacts/multi-seed-stability.json")
    validator.add_argument("--shuffled-label-file", default="artifacts/shuffled-label-check.json")
    validator.add_argument("--output")
    validator.set_defaults(func=cmd_validator)

    resistance = sub.add_parser("regression-resistance", help="plant ML regressions and require validation tests to fail")
    resistance.add_argument("--result-file", required=True)
    resistance.add_argument("--output")
    resistance.set_defaults(func=cmd_regression_resistance)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
