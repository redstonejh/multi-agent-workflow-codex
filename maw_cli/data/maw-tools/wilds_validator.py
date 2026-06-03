#!/usr/bin/env python3
"""Validator signals for WILDS benchmark score artifacts.

This tool is intentionally stdlib-only. It reads the score JSON produced by
``maw wilds-benchmark`` or ``maw wilds-export --score-output`` and optional
prediction rows containing probabilities plus labels for calibration.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLDS = {
    "max_worst_group_gap": 0.20,
    "max_expected_calibration_error": 0.10,
    "max_brier_score": 0.25,
    "min_majority_margin": 0.02,
}


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_jsonl_or_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                item = json.loads(stripped)
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{line_number} must be a JSON object")
                rows.append(item)
        return rows
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("predictions", [])
    else:
        raise ValueError(f"{path} must contain a list or predictions list")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} predictions must be a list of JSON objects")
    return list(rows)


def as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def metric_value(score: dict[str, Any], names: tuple[str, ...]) -> float | None:
    candidates: list[Any] = []
    metrics = score.get("metrics")
    if isinstance(metrics, dict):
        candidates.extend(metrics.get(name) for name in names)
    for container in (score, score.get("splits") if isinstance(score.get("splits"), dict) else None):
        if isinstance(container, dict):
            candidates.extend(container.get(name) for name in names)
    for candidate in candidates:
        value = as_float(candidate)
        if value is not None:
            return value
    return None


def field(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def probability_for_row(row: dict[str, Any]) -> float | None:
    for name in ("probability", "prob", "score", "confidence"):
        value = as_float(row.get(name))
        if value is not None:
            return value
    probabilities = row.get("probabilities")
    if isinstance(probabilities, dict):
        prediction = field(row, ("prediction", "pred", "y_pred"))
        if prediction is not None:
            value = as_float(probabilities.get(str(prediction)))
            if value is not None:
                return value
        floats = [value for value in (as_float(item) for item in probabilities.values()) if value is not None]
        return max(floats) if floats else None
    if isinstance(probabilities, list):
        floats = [value for value in (as_float(item) for item in probabilities) if value is not None]
        return max(floats) if floats else None
    return None


def label_pair(row: dict[str, Any]) -> tuple[str | None, str | None]:
    actual = field(row, ("label", "target", "y", "true_label", "y_true"))
    predicted = field(row, ("prediction", "pred", "y_pred"))
    return (str(actual) if actual is not None else None, str(predicted) if predicted is not None else None)


def calibration(rows: list[dict[str, Any]], bins: int) -> dict[str, Any]:
    usable: list[tuple[float, bool]] = []
    missing_probability = 0
    missing_label = 0
    for row in rows:
        probability = probability_for_row(row)
        actual, predicted = label_pair(row)
        if probability is None:
            missing_probability += 1
            continue
        if actual is None or predicted is None:
            missing_label += 1
            continue
        probability = min(max(probability, 0.0), 1.0)
        usable.append((probability, actual == predicted))

    if not usable:
        return {
            "available": False,
            "examples": 0,
            "missing_probability": missing_probability,
            "missing_label": missing_label,
        }

    bins = max(1, bins)
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        in_bin = [(probability, correct) for probability, correct in usable if lower <= probability < upper or (index == bins - 1 and probability == 1.0)]
        if not in_bin:
            continue
        confidence = sum(item[0] for item in in_bin) / len(in_bin)
        accuracy = sum(1 for _probability, correct in in_bin if correct) / len(in_bin)
        ece += (len(in_bin) / len(usable)) * abs(confidence - accuracy)
    brier = sum((probability - (1.0 if correct else 0.0)) ** 2 for probability, correct in usable) / len(usable)
    return {
        "available": True,
        "examples": len(usable),
        "expected_calibration_error": ece,
        "brier_score": brier,
        "missing_probability": missing_probability,
        "missing_label": missing_label,
    }


def signal(name: str, passed: bool, value: Any, threshold: Any, diagnosis: str, recommendation: str, instruction: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "value": value,
        "threshold": threshold,
        "diagnosis": diagnosis if not passed else "",
        "recommendation": recommendation if not passed else "",
        "worker_instruction": instruction if not passed else "",
    }


def validate(score: dict[str, Any], predictions: list[dict[str, Any]] | None, thresholds: dict[str, float], majority_accuracy: float, calibration_bins: int) -> dict[str, Any]:
    signals: list[dict[str, Any]] = []

    acc_avg = metric_value(score, ("acc_avg", "accuracy", "acc"))
    acc_wg = metric_value(score, ("acc_wg", "worst_group_accuracy", "worst_group_acc"))
    if acc_avg is None or acc_wg is None:
        signals.append(
            signal(
                "worst_group_gap",
                False,
                None,
                {"max": thresholds["max_worst_group_gap"]},
                "score.json does not expose average and worst-group accuracy.",
                "Record WILDS dataset.eval metrics with acc_avg and acc_wg before accepting subgroup robustness.",
                "Re-run scoring with dataset.eval metrics preserved, then retry validation.",
            )
        )
    else:
        gap = max(0.0, acc_avg - acc_wg)
        signals.append(
            signal(
                "worst_group_gap",
                gap <= thresholds["max_worst_group_gap"],
                gap,
                {"max": thresholds["max_worst_group_gap"], "acc_avg": acc_avg, "acc_wg": acc_wg},
                "Worst-group accuracy is too far below average accuracy, indicating possible spurious-correlation sensitivity.",
                "Try group-balanced sampling, group reweighting, richer text features, or a stronger model family.",
                "Train or select a candidate that explicitly improves worst-group accuracy before re-scoring.",
            )
        )

    if predictions is None:
        cal = {"available": False, "examples": 0, "missing_probability": 0, "missing_label": 0}
    else:
        cal = calibration(predictions, calibration_bins)
    cal_passed = bool(cal.get("available")) and as_float(cal.get("expected_calibration_error")) is not None and as_float(cal.get("brier_score")) is not None
    if cal_passed:
        cal_passed = bool(cal["expected_calibration_error"] <= thresholds["max_expected_calibration_error"] and cal["brier_score"] <= thresholds["max_brier_score"])
    signals.append(
        signal(
            "calibration",
            cal_passed,
            cal,
            {"max_expected_calibration_error": thresholds["max_expected_calibration_error"], "max_brier_score": thresholds["max_brier_score"]},
            "Prediction probabilities are missing or poorly calibrated.",
            "Emit probabilities and try calibration-aware training, Platt scaling, isotonic calibration, or stronger validation data.",
            "Produce prediction rows with prediction, label, and probability fields, then re-run the validator.",
        )
    )

    if acc_avg is None:
        margin = None
        baseline_passed = False
    else:
        margin = acc_avg - majority_accuracy
        baseline_passed = margin >= thresholds["min_majority_margin"]
    signals.append(
        signal(
            "baseline_vs_majority",
            baseline_passed,
            margin,
            {"majority_accuracy": majority_accuracy, "min_margin": thresholds["min_majority_margin"]},
            "Model accuracy does not clear the majority-class baseline by the configured margin.",
            "Audit labels, improve features, tune the model, or use a stronger baseline before accepting the result.",
            "Compare against an explicit majority baseline and improve average accuracy by at least the configured margin.",
        )
    )

    reproducibility = score.get("reproducibility") if isinstance(score.get("reproducibility"), dict) else {}
    reproducible = bool(reproducibility.get("deterministic") is True and (reproducibility.get("evaluated_at_utc") or reproducibility.get("exported_at_utc")))
    signals.append(
        signal(
            "reproducibility",
            reproducible,
            reproducibility,
            {"deterministic": True, "timestamp_required": True},
            "Score artifact lacks deterministic reproducibility metadata.",
            "Record deterministic split alignment, command inputs, and an evaluation timestamp.",
            "Re-run the scorer so score.json includes reproducibility.deterministic=true and an evaluation timestamp.",
        )
    )

    tripped = [item for item in signals if not item["passed"]]
    return {
        "check": "wilds_validator",
        "schema_version": 1,
        "passed": not tripped,
        "thresholds": thresholds,
        "majority_accuracy": majority_accuracy,
        "signals": signals,
        "tripped": [item["name"] for item in tripped],
        "worker_instructions": [item["worker_instruction"] for item in tripped if item["worker_instruction"]],
        "recommendations": [item["recommendation"] for item in tripped if item["recommendation"]],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Derive WILDS validator signals from score.json.")
    parser.add_argument("--score", required=True, help="score JSON produced by WILDS benchmark")
    parser.add_argument("--predictions", help="optional JSON/JSONL predictions with probability and label fields")
    parser.add_argument("--output", help="write validator JSON")
    parser.add_argument("--majority-accuracy", type=float, default=0.5)
    parser.add_argument("--max-worst-group-gap", type=float, default=DEFAULT_THRESHOLDS["max_worst_group_gap"])
    parser.add_argument("--max-expected-calibration-error", type=float, default=DEFAULT_THRESHOLDS["max_expected_calibration_error"])
    parser.add_argument("--max-brier-score", type=float, default=DEFAULT_THRESHOLDS["max_brier_score"])
    parser.add_argument("--min-majority-margin", type=float, default=DEFAULT_THRESHOLDS["min_majority_margin"])
    parser.add_argument("--calibration-bins", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        thresholds = {
            "max_worst_group_gap": args.max_worst_group_gap,
            "max_expected_calibration_error": args.max_expected_calibration_error,
            "max_brier_score": args.max_brier_score,
            "min_majority_margin": args.min_majority_margin,
        }
        predictions = load_jsonl_or_rows(Path(args.predictions)) if args.predictions else None
        result = validate(load_json(Path(args.score)), predictions, thresholds, args.majority_accuracy, args.calibration_bins)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"check": "wilds_validator", "schema_version": 1, "passed": False, "problems": [{"type": "input_error", "message": str(exc)}]}
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
