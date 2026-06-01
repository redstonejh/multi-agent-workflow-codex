"""Deterministic checks for toy ML problem runs."""
from __future__ import annotations

import argparse
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
    ]
    for check in result.get("metric_checks", []):
        if check["direction"] == "at_least":
            checks.append(metric_at_least(result["metrics"], check["name"], float(check["threshold"])))
        elif check["direction"] == "at_most":
            checks.append(metric_at_most(result["metrics"], check["name"], float(check["threshold"])))
        else:
            checks.append({"check": check["name"], "passed": False, "error": f"unknown direction {check['direction']}"})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    commands = {"validate", "fit-diagnosis", "baseline", "calibration", "reproducibility", "data-quality", "-h", "--help"}
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

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
