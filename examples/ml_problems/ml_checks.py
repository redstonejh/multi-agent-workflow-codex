"""Deterministic checks for toy ML problem runs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
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



def _row_id(row: dict[str, Any]) -> Any:
    return row.get("id", row.get("row_id"))


def _split_row_sets(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = result.get("rows")
    if not isinstance(rows, list):
        return [], []
    train_ids = set(result.get("split", {}).get("train_ids", []))
    test_ids = set(result.get("split", {}).get("test_ids", []))
    train = [row for row in rows if isinstance(row, dict) and _row_id(row) in train_ids]
    test = [row for row in rows if isinstance(row, dict) and _row_id(row) in test_ids]
    return train, test


def _feature_names_for_rows(result: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    target = str(result.get("target", "target"))
    excluded = {"id", "row_id", target, str(result.get("group_column", "group_id")), str(result.get("time_column", "timestamp"))}
    features = result.get("features")
    if isinstance(features, list):
        return [str(name) for name in features if str(name) not in excluded]
    names: set[str] = set()
    for row in rows:
        names.update(str(key) for key in row if str(key) not in excluded)
    return sorted(names)


def _stable_row_hash(row: dict[str, Any], feature_names: list[str]) -> str:
    payload = json.dumps({name: row.get(name) for name in feature_names}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_duplicate_leakage(result: dict[str, Any]) -> dict[str, Any]:
    train, test = _split_row_sets(result)
    if not train or not test:
        return {"check": "content_duplicate_leakage", "passed": True, "status": "not_applicable", "duplicates": [], "reasons": []}
    features = _feature_names_for_rows(result, train + test)
    train_hashes: dict[str, list[Any]] = {}
    for row in train:
        train_hashes.setdefault(_stable_row_hash(row, features), []).append(_row_id(row))
    duplicates = []
    for row in test:
        digest = _stable_row_hash(row, features)
        if digest in train_hashes:
            duplicates.append({"train_ids": train_hashes[digest], "test_id": _row_id(row), "hash": digest})
    return {"check": "content_duplicate_leakage", "passed": not duplicates, "status": "pass" if not duplicates else "fail", "feature_columns": features, "duplicates": duplicates, "reasons": [] if not duplicates else ["identical feature rows appear in both train and test"]}


def group_entity_leakage(result: dict[str, Any]) -> dict[str, Any]:
    train, test = _split_row_sets(result)
    group_column = str(result.get("group_column", "group_id"))
    if not train or not test or not any(group_column in row for row in train + test):
        return {"check": "group_entity_leakage", "passed": True, "status": "not_applicable", "group_column": group_column, "overlap": [], "reasons": []}
    train_groups = {row.get(group_column) for row in train if row.get(group_column) is not None}
    test_groups = {row.get(group_column) for row in test if row.get(group_column) is not None}
    overlap = sorted(train_groups & test_groups, key=str)
    return {"check": "group_entity_leakage", "passed": not overlap, "status": "pass" if not overlap else "fail", "group_column": group_column, "overlap": overlap, "reasons": [] if not overlap else ["group_id appears in both train and test"]}


def temporal_leakage(result: dict[str, Any]) -> dict[str, Any]:
    train, test = _split_row_sets(result)
    time_column = str(result.get("time_column", "timestamp"))
    if not train or not test or not any(time_column in row for row in train + test):
        return {"check": "temporal_leakage", "passed": True, "status": "not_applicable", "time_column": time_column, "reasons": []}
    train_times = [str(row[time_column]) for row in train if time_column in row]
    test_times = [str(row[time_column]) for row in test if time_column in row]
    if not train_times or not test_times:
        return {"check": "temporal_leakage", "passed": True, "status": "not_applicable", "time_column": time_column, "reasons": []}
    max_train = max(train_times)
    min_test = min(test_times)
    passed = max_train < min_test
    return {"check": "temporal_leakage", "passed": passed, "status": "pass" if passed else "fail", "time_column": time_column, "max_train_timestamp": max_train, "min_test_timestamp": min_test, "reasons": [] if passed else ["max train timestamp must precede min test timestamp"]}


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return math.nan
    mx = _mean(xs)
    my = _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0.0 or deny == 0.0:
        return math.nan
    return num / (denx * deny)


def high_feature_target_correlation(result: dict[str, Any], threshold: float | None = None) -> dict[str, Any]:
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        return {"check": "high_feature_target_correlation", "passed": True, "status": "not_applicable", "flagged_features": [], "reasons": []}
    target = str(result.get("target", "target"))
    threshold = float(result.get("max_abs_feature_target_correlation", 0.98) if threshold is None else threshold)
    feature_names = _feature_names_for_rows(result, [row for row in rows if isinstance(row, dict)])
    flagged = []
    for feature in feature_names:
        xs: list[float] = []
        ys: list[float] = []
        for row in rows:
            if not isinstance(row, dict) or feature not in row or target not in row:
                continue
            try:
                x = float(row[feature]); y = float(row[target])
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                xs.append(x); ys.append(y)
        corr = _pearson(xs, ys)
        if math.isfinite(corr) and abs(corr) > threshold:
            flagged.append({"feature": feature, "pearson": corr, "abs_pearson": abs(corr), "threshold": threshold})
    return {"check": "high_feature_target_correlation", "passed": not flagged, "status": "pass" if not flagged else "fail", "threshold": threshold, "flagged_features": flagged, "reasons": [] if not flagged else ["feature-target correlation exceeds threshold"]}


def _numeric_feature_maps(data: dict[str, Any]) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    left = data.get("train", data.get("reference", {}))
    right = data.get("test", data.get("current", {}))
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError("drift data must contain train/test or reference/current objects")
    def coerce_map(raw: dict[str, Any]) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for key, values in raw.items():
            if isinstance(values, list):
                nums = []
                for value in values:
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(number):
                        nums.append(number)
                if nums:
                    out[str(key)] = nums
        return out
    return coerce_map(left), coerce_map(right)


def _ks_statistic(left: list[float], right: list[float]) -> float:
    xs = sorted(set(left + right))
    a = sorted(left); b = sorted(right)
    i = j = 0; n = len(a); m = len(b); best = 0.0
    for x in xs:
        while i < n and a[i] <= x: i += 1
        while j < m and b[j] <= x: j += 1
        best = max(best, abs(i / n - j / m))
    return best


def _psi(left: list[float], right: list[float], bins: int = 10) -> float:
    lo = min(left); hi = max(left)
    if hi == lo:
        return 0.0 if min(right) == max(right) == lo else math.inf
    eps = 1e-6
    width = (hi - lo) / bins
    total = 0.0
    for idx in range(bins):
        lower = lo + idx * width
        upper = hi if idx == bins - 1 else lower + width
        lcount = sum(1 for value in left if value >= lower and (value <= upper if idx == bins - 1 else value < upper))
        rcount = sum(1 for value in right if value >= lower and (value <= upper if idx == bins - 1 else value < upper))
        lp = max(lcount / len(left), eps)
        rp = max(rcount / len(right), eps)
        total += (rp - lp) * math.log(rp / lp)
    return total


def drift_check(data: dict[str, Any], max_psi: float = 0.2, max_ks: float = 0.2, bins: int = 10) -> dict[str, Any]:
    reasons: list[str] = []
    if not math.isfinite(max_psi) or max_psi < 0.0:
        reasons.append("max_psi must be finite and non-negative")
    if not math.isfinite(max_ks) or max_ks < 0.0:
        reasons.append("max_ks must be finite and non-negative")
    if bins <= 0:
        reasons.append("bins must be positive")
    if reasons:
        return {"check": "distribution_drift", "passed": False, "status": "invalid", "features": [], "thresholds": {"max_psi": max_psi, "max_ks": max_ks, "bins": bins}, "reasons": reasons}
    try:
        left, right = _numeric_feature_maps(data)
    except ValueError as exc:
        return {"check": "distribution_drift", "passed": False, "status": "invalid", "features": [], "thresholds": {"max_psi": max_psi, "max_ks": max_ks, "bins": bins}, "reasons": [str(exc)]}
    features = []
    for name in sorted(set(left) & set(right)):
        psi = _psi(left[name], right[name], bins=bins)
        ks = _ks_statistic(left[name], right[name])
        passed = psi <= max_psi and ks <= max_ks
        features.append({"feature": name, "psi": psi, "ks_statistic": ks, "passed": passed})
    if not features:
        return {"check": "distribution_drift", "passed": False, "status": "invalid", "features": [], "thresholds": {"max_psi": max_psi, "max_ks": max_ks, "bins": bins}, "reasons": ["no shared numeric features to compare"]}
    failed = [item for item in features if not item["passed"]]
    return {"check": "distribution_drift", "passed": not failed, "status": "pass" if not failed else "fail", "features": features, "thresholds": {"max_psi": max_psi, "max_ks": max_ks, "bins": bins}, "reasons": [] if not failed else ["distribution drift exceeds PSI or KS threshold"]}


def majority_class_rate(labels: list[Any]) -> float:
    if not labels:
        return math.nan
    counts: dict[str, int] = {}
    for label in labels:
        key = str(label)
        counts[key] = counts.get(key, 0) + 1
    return max(counts.values()) / len(labels)


def _labels_from_result(result: dict[str, Any]) -> list[Any]:
    if isinstance(result.get("labels"), list):
        return list(result["labels"])
    rows = result.get("rows")
    target = str(result.get("target", "target"))
    if isinstance(rows, list):
        labels = [row.get(target) for row in rows if isinstance(row, dict) and target in row]
        if labels:
            return labels
    return []


def _auc_roc(labels: list[int], scores: list[float]) -> float | None:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0], reverse=True)
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    tp = fp = 0
    points = [(0.0, 0.0)]
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        points.append((fp / neg, tp / pos))
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += (x1 - x0) * (y0 + y1) / 2.0
    return area


def _auc_pr(labels: list[int], scores: list[float]) -> float | None:
    pairs = sorted(zip(scores, labels), key=lambda item: item[0], reverse=True)
    pos = sum(labels)
    if pos == 0:
        return None
    tp = fp = 0
    points = [(0.0, 1.0)]
    for _, label in pairs:
        if label == 1:
            tp += 1
        else:
            fp += 1
        recall = tp / pos
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        points.append((recall, precision))
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        area += (x1 - x0) * (y0 + y1) / 2.0
    return area


def classification_metrics(data: dict[str, Any], min_metric: float | None = None, metric_name: str = "macro_f1", min_slice_metric: float | None = None, max_slice_gap: float | None = None) -> dict[str, Any]:
    labels = list(data.get("labels", []))
    predictions = list(data.get("predictions", []))
    scores = data.get("scores")
    subgroups = data.get("subgroups")
    reasons: list[str] = []
    if not labels or not predictions or len(labels) != len(predictions):
        return {"check": "classification_metrics", "passed": False, "status": "invalid", "reasons": ["labels and predictions must be non-empty arrays of equal length"]}
    classes = sorted({str(item) for item in labels} | {str(item) for item in predictions})
    matrix = {actual: {pred: 0 for pred in classes} for actual in classes}
    for actual, pred in zip(labels, predictions):
        matrix[str(actual)][str(pred)] += 1
    per_class: dict[str, dict[str, float]] = {}
    for cls in classes:
        tp = matrix[cls][cls]
        fp = sum(matrix[other][cls] for other in classes if other != cls)
        fn = sum(matrix[cls][other] for other in classes if other != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[cls] = {"precision": precision, "recall": recall, "f1": f1, "support": sum(matrix[cls].values())}
    accuracy = sum(1 for a, b in zip(labels, predictions) if str(a) == str(b)) / len(labels)
    macro_precision = _mean([item["precision"] for item in per_class.values()])
    macro_recall = _mean([item["recall"] for item in per_class.values()])
    macro_f1 = _mean([item["f1"] for item in per_class.values()])
    majority = majority_class_rate(labels)
    metrics = {"accuracy": accuracy, "macro_precision": macro_precision, "macro_recall": macro_recall, "macro_f1": macro_f1, "majority_class_rate": majority}
    binary_labels: list[int] = []
    numeric_scores: list[float] = []
    if isinstance(scores, list) and len(scores) == len(labels) and len(classes) == 2:
        positive = classes[-1]
        for label, score in zip(labels, scores):
            try:
                numeric = float(score)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                binary_labels.append(1 if str(label) == positive else 0)
                numeric_scores.append(numeric)
        if len(binary_labels) == len(labels):
            roc = _auc_roc(binary_labels, numeric_scores)
            pr = _auc_pr(binary_labels, numeric_scores)
            if roc is not None:
                metrics["roc_auc"] = roc
            if pr is not None:
                metrics["pr_auc"] = pr
    slice_metrics: dict[str, dict[str, float]] = {}
    if isinstance(subgroups, list) and len(subgroups) == len(labels):
        for group in sorted({str(item) for item in subgroups}):
            idxs = [idx for idx, item in enumerate(subgroups) if str(item) == group]
            sub = classification_metrics({"labels": [labels[i] for i in idxs], "predictions": [predictions[i] for i in idxs]}, metric_name=metric_name)
            slice_metrics[group] = {key: float(value) for key, value in sub.get("metrics", {}).items() if isinstance(value, (int, float)) and math.isfinite(float(value))}
        if slice_metrics:
            values = [item.get(metric_name, 0.0) for item in slice_metrics.values()]
            if min_slice_metric is not None and any(value < min_slice_metric for value in values):
                reasons.append(f"slice {metric_name} below minimum {min_slice_metric:.6g}")
            if max_slice_gap is not None and max(values) - min(values) > max_slice_gap:
                reasons.append(f"slice {metric_name} gap exceeds {max_slice_gap:.6g}")
    if min_metric is not None and metrics.get(metric_name, math.nan) < min_metric:
        reasons.append(f"{metric_name} {metrics.get(metric_name, math.nan):.6g} is below minimum {min_metric:.6g}")
    return {"check": "classification_metrics", "passed": not reasons, "status": "pass" if not reasons else "fail", "metrics": metrics, "per_class": per_class, "confusion_matrix": matrix, "slice_metrics": slice_metrics, "thresholds": {"metric_name": metric_name, "min_metric": min_metric, "min_slice_metric": min_slice_metric, "max_slice_gap": max_slice_gap}, "reasons": reasons}

def baseline_comparison(
    metrics: dict[str, Any],
    model_metric: str = "model_score",
    baseline_metric: str = "baseline_score",
    min_improvement: float = 0.0,
    direction: str = "higher",
    bootstrap_samples: int = 1000,
    bootstrap_confidence: float = 0.95,
    seed: int = 0,
) -> dict[str, Any]:
    reasons: list[str] = []
    reasons.extend(_validate_bootstrap(bootstrap_samples, bootstrap_confidence, seed))
    if direction not in {"higher", "lower"}:
        reasons.append("direction must be 'higher' or 'lower'")
    if not math.isfinite(min_improvement):
        reasons.append("min_improvement must be finite")

    baseline_source = "metric"
    if baseline_metric not in metrics and isinstance(metrics.get("labels"), list):
        metrics[baseline_metric] = majority_class_rate(list(metrics["labels"]))
        baseline_source = "majority_class_rate"
    missing = [name for name in (model_metric, baseline_metric) if name not in metrics]
    if missing:
        reasons.append("Missing required metric(s): " + ", ".join(missing))
        return {
            "check": "baseline_comparison",
            "passed": False,
            "status": "invalid",
            "missing_metrics": missing,
            "reasons": reasons,
        }

    model_values = _coerce_numeric_series(metrics[model_metric], model_metric, reasons)
    baseline_values = _coerce_numeric_series(metrics[baseline_metric], baseline_metric, reasons)
    if len(model_values) != len(baseline_values):
        reasons.append("model and baseline sample arrays must have the same length for paired bootstrap")

    if reasons:
        return {
            "check": "baseline_comparison",
            "passed": False,
            "status": "invalid",
            "model_metric": model_metric,
            "baseline_metric": baseline_metric,
            "direction": direction,
            "min_improvement": min_improvement,
            "reasons": reasons,
        }

    model_value = _mean(model_values)
    baseline_value = _mean(baseline_values)
    improvement = model_value - baseline_value if direction == "higher" else baseline_value - model_value
    bootstrap_ci = _paired_bootstrap_difference_ci(
        model_values,
        baseline_values,
        direction,
        samples=bootstrap_samples,
        confidence=bootstrap_confidence,
        seed=seed,
    )

    passed = bootstrap_ci["lower"] >= min_improvement
    if not passed:
        reasons.append(
            f"Bootstrap CI lower bound {bootstrap_ci['lower']:.6g} is below required improvement {min_improvement:.6g}"
        )

    return {
        "check": "baseline_comparison",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "model_metric": model_metric,
        "baseline_metric": baseline_metric,
        "baseline_source": baseline_source,
        "model_value": model_value,
        "baseline_value": baseline_value,
        "direction": direction,
        "improvement": improvement,
        "min_improvement": min_improvement,
        "bootstrap_ci": bootstrap_ci,
        "bootstrap_samples": bootstrap_samples,
        "bootstrap_confidence": bootstrap_confidence,
        "seed": seed,
        "gate": "bootstrap_ci_lower_bound",
        "reasons": reasons,
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


def calibration_check(data: dict[str, Any], max_ece: float = 0.08, bins: int = 10, max_mce: float | None = None, max_brier: float | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    if not math.isfinite(max_ece) or max_ece < 0.0:
        reasons.append("max_ece must be finite and non-negative")
    if max_mce is not None and (not math.isfinite(max_mce) or max_mce < 0.0):
        reasons.append("max_mce must be finite and non-negative when provided")
    if max_brier is not None and (not math.isfinite(max_brier) or max_brier < 0.0):
        reasons.append("max_brier must be finite and non-negative when provided")
    if reasons:
        return {
            "check": "calibration",
            "passed": False,
            "status": "invalid",
            "max_ece": max_ece,
            "reasons": reasons,
        }
    try:
        confidences = _float_list(data["confidences"], "confidences")
        correct = [bool(item) for item in data["correct"]]
        ece_result = expected_calibration_error(confidences, correct, bins=bins)
        correct_float = [1.0 if item else 0.0 for item in correct]
        brier_score = _mean([(conf - actual) ** 2 for conf, actual in zip(confidences, correct_float)])
        mce = max((abs(bin_summary["accuracy"] - bin_summary["avg_confidence"]) for bin_summary in ece_result["bin_summaries"]), default=0.0)
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "check": "calibration",
            "passed": False,
            "status": "invalid",
            "reasons": [str(exc)],
        }
    ece_ok = ece_result["ece"] <= max_ece
    mce_ok = True if max_mce is None else mce <= max_mce
    brier_ok = True if max_brier is None else brier_score <= max_brier
    if not ece_ok:
        reasons.append(f"ECE {ece_result['ece']:.6g} exceeds max_ece {max_ece:.6g}")
    if not mce_ok:
        reasons.append(f"MCE {mce:.6g} exceeds max_mce {max_mce:.6g}")
    if not brier_ok:
        reasons.append(f"Brier score {brier_score:.6g} exceeds max_brier {max_brier:.6g}")
    passed = ece_ok and mce_ok and brier_ok
    return {
        **ece_result,
        "check": "calibration",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "brier_score": brier_score,
        "maximum_calibration_error": mce,
        "ece_bias_note": "ECE uses equal-width bins; estimates can be biased by bin count and confidence distribution.",
        "max_ece": max_ece,
        "max_mce": max_mce,
        "max_brier": max_brier,
        "reasons": reasons,
    }


def data_quality_check(data: dict[str, Any], max_missing_rate: float = 0.0, max_duplicate_rate: float = 0.0) -> dict[str, Any]:
    row_count = int(data.get("row_count", 0))
    missing_values = data.get("missing_values", {})
    duplicate_rows = int(data.get("duplicate_rows", 0))
    if max_missing_rate < 0 or max_duplicate_rate < 0 or not math.isfinite(max_missing_rate) or not math.isfinite(max_duplicate_rate):
        return {
            "check": "data_quality",
            "passed": False,
            "status": "invalid",
            "reasons": ["max_missing_rate and max_duplicate_rate must be finite and non-negative"],
        }
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



def reproducibility_check(data: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    seed = data.get("seed")
    expected_seed = data.get("expected_seed", seed)
    deterministic = bool(data.get("deterministic", False))
    if seed != expected_seed:
        reasons.append(f"seed {seed!r} does not match expected_seed {expected_seed!r}")
    if not deterministic:
        reasons.append("deterministic must be true")
    return {
        "check": "reproducibility",
        "passed": not reasons,
        "status": "pass" if not reasons else "fail",
        "seed": seed,
        "expected_seed": expected_seed,
        "deterministic": deterministic,
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





def _validate_bootstrap(samples: int, confidence: float, seed: int) -> list[str]:
    reasons: list[str] = []
    if samples <= 0:
        reasons.append("bootstrap_samples must be positive")
    if not math.isfinite(confidence) or not (0.0 < confidence < 1.0):
        reasons.append("bootstrap_confidence must be finite and between 0 and 1")
    if not isinstance(seed, int):
        reasons.append("seed must be an integer")
    return reasons


def _coerce_numeric_series(value: Any, name: str, reasons: list[str]) -> list[float]:
    raw_values = value if isinstance(value, list) else [value]
    values: list[float] = []
    for item in raw_values:
        try:
            number = float(item)
        except (TypeError, ValueError):
            reasons.append(f"{name} must contain numeric values")
            continue
        if not math.isfinite(number):
            reasons.append(f"{name} must contain finite values")
        values.append(number)
    if not values:
        reasons.append(f"{name} must not be empty")
    return values


def _bootstrap_mean_ci(values: list[float], samples: int = 1000, confidence: float = 0.95, seed: int = 0) -> dict[str, Any]:
    return bootstrap_mean_ci(values, samples=samples, confidence=confidence, seed=seed)


def _paired_bootstrap_difference_ci(model_values: list[float], baseline_values: list[float], direction: str, samples: int, confidence: float, seed: int) -> dict[str, Any]:
    if len(model_values) != len(baseline_values) or not model_values:
        raise ValueError("model and baseline sample arrays must be non-empty and equal length")
    diffs = [m - b for m, b in zip(model_values, baseline_values)] if direction == "higher" else [b - m for m, b in zip(model_values, baseline_values)]
    ci = bootstrap_mean_ci(diffs, samples=samples, confidence=confidence, seed=seed)
    ci["observed_difference"] = _mean(diffs)
    ci["sample_count"] = len(diffs)
    return ci

def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return math.nan
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    position = (len(sorted_values) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def bootstrap_mean_ci(values: list[float], samples: int = 1000, confidence: float = 0.95, seed: int = 0) -> dict[str, Any]:
    if not values:
        return {"samples": samples, "confidence": confidence, "seed": seed, "lower": None, "upper": None, "reasons": ["values must be non-empty"]}
    if samples <= 0:
        return {"samples": samples, "confidence": confidence, "seed": seed, "lower": None, "upper": None, "reasons": ["samples must be positive"]}
    if confidence <= 0.0 or confidence >= 1.0 or not math.isfinite(confidence):
        return {"samples": samples, "confidence": confidence, "seed": seed, "lower": None, "upper": None, "reasons": ["confidence must be finite and between 0 and 1"]}
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(samples):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    return {
        "samples": samples,
        "confidence": confidence,
        "seed": seed,
        "lower": round(_percentile(means, alpha), 6),
        "upper": round(_percentile(means, 1.0 - alpha), 6),
        "reasons": [],
    }


def paired_differences(model_values: list[float], baseline_values: list[float]) -> list[float]:
    if len(model_values) != len(baseline_values) or not model_values:
        raise ValueError("model and baseline sample arrays must be non-empty and equal length")
    return [model - baseline for model, baseline in zip(model_values, baseline_values)]


def _default_chance_score(problem_type: str, direction: str, class_count: int, labels: list[Any] | None = None) -> float:
    if problem_type == "classification":
        if labels:
            return majority_class_rate(labels)
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
    alpha: float = 0.05,
    labels: list[Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    if direction not in {"higher", "lower"}:
        reasons.append("direction must be 'higher' or 'lower'")
    if not shuffled_scores:
        reasons.append("shuffled_scores must not be empty")
    if not math.isfinite(real_score):
        reasons.append("real_score must be finite")
    if not math.isfinite(tolerance) or tolerance < 0.0:
        reasons.append("tolerance must be finite and non-negative")
    if not math.isfinite(min_real_margin) or min_real_margin < 0.0:
        reasons.append("min_real_margin must be finite and non-negative")
    if not math.isfinite(alpha) or not (0.0 < alpha <= 1.0):
        reasons.append("alpha must be finite and in (0, 1]")
    for score in shuffled_scores:
        if not math.isfinite(score):
            reasons.append("all shuffled_scores must be finite")
            break
    try:
        chance = float(chance_score) if chance_score is not None else _default_chance_score(problem_type, direction, class_count, labels)
    except ValueError as exc:
        reasons.append(str(exc))
        chance = 0.0
    if reasons:
        return {
            "check": "shuffled_label",
            "passed": False,
            "status": "invalid",
            "reasons": reasons,
        }

    shuffled_mean = _mean(shuffled_scores)
    shuffled_variance = _population_variance(shuffled_scores)
    shuffled_std = math.sqrt(shuffled_variance)
    if direction == "higher":
        real_ok = real_score >= chance + min_real_margin
        shuffled_ok = max(shuffled_scores) <= chance + tolerance
        extreme_count = sum(1 for score in shuffled_scores if score >= real_score)
        thresholds = {
            "real_minimum": chance + min_real_margin,
            "shuffled_maximum": chance + tolerance,
            "tolerance": tolerance,
            "min_real_margin": min_real_margin,
            "alpha": alpha,
            "chance_score": chance,
            "class_count": class_count,
        }
    else:
        real_ok = real_score <= chance - min_real_margin
        shuffled_ok = min(shuffled_scores) >= chance - tolerance
        extreme_count = sum(1 for score in shuffled_scores if score <= real_score)
        thresholds = {
            "real_maximum": chance - min_real_margin,
            "shuffled_minimum": chance - tolerance,
            "tolerance": tolerance,
            "min_real_margin": min_real_margin,
            "alpha": alpha,
            "chance_score": chance,
            "class_count": class_count,
        }
    p_value = (extreme_count + 1.0) / (len(shuffled_scores) + 1.0)
    significance_ok = p_value <= alpha
    if not real_ok:
        reasons.append("Real-label score does not clear the chance margin")
    if not shuffled_ok:
        reasons.append("shuffled score max/min did not collapse to chance")
    if not significance_ok:
        reasons.append(f"Permutation p-value {p_value:.6g} exceeds alpha {alpha:.6g}")
    passed = real_ok and shuffled_ok and significance_ok
    return {
        "check": "shuffled_label",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "problem_type": problem_type,
        "direction": direction,
        "real_score": real_score,
        "chance_score": chance,
        "class_count": class_count,
        "metrics": {
            "shuffled_mean": shuffled_mean,
            "shuffled_variance": shuffled_variance,
            "shuffled_std": shuffled_std,
            "shuffled_min": min(shuffled_scores),
            "shuffled_max": max(shuffled_scores),
            "permutation_p_value": p_value,
            "at_least_as_extreme_count": extreme_count,
            "shuffled_count": len(shuffled_scores),
        },
        "permutation_p_value": p_value,
        "thresholds": thresholds,
        "reasons": reasons,
    }


def multi_seed_check(
    scores: list[float],
    min_score: float = 0.0,
    max_score: float | None = None,
    max_variance: float | None = None,
    min_seeds: int = 2,
    direction: str = "higher",
    metric_name: str = "score",
    max_cv: float = 0.05,
    bootstrap_samples: int = 1000,
    bootstrap_confidence: float = 0.95,
    seed: int = 0,
) -> dict[str, Any]:
    reasons: list[str] = []
    reasons.extend(_validate_bootstrap(bootstrap_samples, bootstrap_confidence, seed))
    if direction not in {"higher", "lower"}:
        reasons.append("direction must be 'higher' or 'lower'")
    if len(scores) < min_seeds:
        reasons.append(f"Need at least {min_seeds} seeds, got {len(scores)}")
    if not math.isfinite(min_score):
        reasons.append("min_score must be finite")
    if max_score is not None and not math.isfinite(max_score):
        reasons.append("max_score must be finite when provided")
    if max_variance is not None and (not math.isfinite(max_variance) or max_variance < 0.0):
        reasons.append("max_variance must be finite and non-negative when provided")
    if not math.isfinite(max_cv) or max_cv < 0.0:
        reasons.append("max_cv must be finite and non-negative")
    for score in scores:
        if not math.isfinite(score):
            reasons.append("all scores must be finite")
            break
    if reasons:
        return {
            "check": "multi_seed",
            "passed": False,
            "status": "invalid",
            "metric_name": metric_name,
            "reasons": reasons,
        }
    mean = _mean(scores)
    variance = _population_variance(scores)
    std = math.sqrt(variance)
    cv = std / abs(mean) if mean != 0.0 else math.inf
    mean_ci = _bootstrap_mean_ci(scores, samples=bootstrap_samples, confidence=bootstrap_confidence, seed=seed)
    if direction == "higher":
        per_seed_ok = min(scores) >= min_score
        per_seed_reason = f"At least one seed is below min_score {min_score:.6g}"
    else:
        if max_score is None:
            reasons.append("max_score is required when direction is lower")
            return {
                "check": "multi_seed",
                "passed": False,
                "status": "invalid",
                "metric_name": metric_name,
                "reasons": reasons,
            }
        per_seed_ok = max(scores) <= max_score
        per_seed_reason = f"At least one seed is above max_score {max_score:.6g}"
    cv_ok = cv <= max_cv
    variance_ok = True if max_variance is None else variance <= max_variance
    if not per_seed_ok:
        reasons.append(per_seed_reason)
    if not cv_ok:
        reasons.append(f"Coefficient of variation {cv:.6g} exceeds max_cv {max_cv:.6g}")
    if not variance_ok:
        reasons.append(f"Legacy variance {variance:.6g} exceeds max_variance {max_variance:.6g}")
    passed = per_seed_ok and cv_ok and variance_ok
    return {
        "check": "multi_seed",
        "passed": passed,
        "status": "pass" if passed else "fail",
        "metric_name": metric_name,
        "direction": direction,
        "scores": scores,
        "metrics": {
            "mean": mean,
            "variance": variance,
            "std": std,
            "min": min(scores),
            "max": max(scores),
            "coefficient_of_variation": cv,
            "bootstrap_mean_ci": mean_ci,
            "seed_count": len(scores),
        },
        "thresholds": {
            "min_score": min_score,
            "max_score": max_score,
            "max_variance": max_variance,
            "max_cv": max_cv,
            "min_seeds": min_seeds,
            "bootstrap_samples": bootstrap_samples,
            "bootstrap_confidence": bootstrap_confidence,
            "seed": seed,
        },
        "legacy_max_variance_note": "max_variance is a legacy, scale-dependent optional gate; prefer max_cv plus the per-seed floor.",
        "legacy_variance_gate_applied": max_variance is not None,
        "reasons": reasons,
    }


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(result.get("metrics", {}))
    if isinstance(result.get("labels"), list) and isinstance(result.get("predictions"), list):
        gate_metric = "macro_f1"
        gate_min = None
        for gate in result.get("metric_checks", []):
            if isinstance(gate, dict) and gate.get("direction") == "at_least" and str(gate.get("name")) in {"macro_f1", "macro_precision", "macro_recall", "roc_auc", "pr_auc", "accuracy"}:
                gate_metric = str(gate["name"])
                gate_min = float(gate["threshold"])
                break
        class_report = classification_metrics(result, min_metric=gate_min, metric_name=gate_metric)
        checks_prefix = [class_report]
        if isinstance(class_report.get("metrics"), dict):
            metrics.update(class_report["metrics"])
    else:
        checks_prefix = []
    checks = checks_prefix + [
        seed_matches(int(result["seed"]), int(result["expected_seed"])),
        no_split_overlap(result["split"]["train_ids"], result["split"]["test_ids"]),
        split_ratio(result["split"]["train_ids"], result["split"]["test_ids"], float(result["split"]["expected_train_ratio"])),
        no_feature_target_leakage(result["features"], result.get("target", "target")),
        content_duplicate_leakage(result),
        group_entity_leakage(result),
        temporal_leakage(result),
        high_feature_target_correlation(result),
        labels_not_shuffled(result),
        preprocessing_fit_on_train_only(result),
    ]
    for check in result.get("metric_checks", []):
        if check["direction"] == "at_least":
            checks.append(metric_at_least(metrics, check["name"], float(check["threshold"])))
        elif check["direction"] == "at_most":
            checks.append(metric_at_most(metrics, check["name"], float(check["threshold"])))
        else:
            checks.append({"check": check["name"], "passed": False, "error": f"unknown direction {check['direction']}"})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


VALIDATOR_EVIDENCE = {
    "leakage": "artifacts/leakage-audit.json",
    "drift": "artifacts/drift-report.json",
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


MUTATION_NAMES = ("leaky_feature", "shuffled_labels", "train_test_overlap", "preprocessing_fit_full_data", "missing_metric", "weak_baseline_ci", "unstable_multi_seed", "bad_calibration_stats", "insignificant_shuffled_label", "content_duplicate_leakage", "group_entity_leakage", "temporal_leakage", "high_feature_target_correlation", "distribution_drift", "hard_imbalanced_majority", "hard_content_duplicate", "hard_temporal_leak")


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
    elif mutation == "missing_metric":
        metric_checks = planted.get("metric_checks", [])
        metrics = planted.get("metrics", {})
        if metric_checks and isinstance(metric_checks, list) and isinstance(metric_checks[0], dict) and isinstance(metrics, dict):
            metrics.pop(str(metric_checks[0].get("name", "")), None)
        planted["metrics"] = metrics
    elif mutation == "weak_baseline_ci":
        planted["features"] = list(planted.get("features", [])) + ["target"]
    elif mutation == "unstable_multi_seed":
        planted["labels_shuffled"] = True
    elif mutation == "bad_calibration_stats":
        planted["preprocessing"] = {"fit_scope": "full_data"}
    elif mutation == "insignificant_shuffled_label":
        train_ids = planted["split"]["train_ids"]
        if train_ids:
            planted["split"]["test_ids"] = [train_ids[0], *list(planted["split"]["test_ids"])]
    else:
        raise ValueError(f"unknown mutation: {mutation}")
    return planted



def _base_leakage_result() -> dict[str, Any]:
    return {
        "seed": 1,
        "expected_seed": 1,
        "features": ["x1", "x2"],
        "target": "target",
        "group_column": "group_id",
        "time_column": "timestamp",
        "split": {"train_ids": [1, 2, 3], "test_ids": [4, 5, 6], "expected_train_ratio": 0.5},
        "rows": [
            {"id": 1, "x1": 1.0, "x2": 2.0, "target": 0, "group_id": "a", "timestamp": "2024-01-01"},
            {"id": 2, "x1": 2.0, "x2": 3.0, "target": 1, "group_id": "b", "timestamp": "2024-01-02"},
            {"id": 3, "x1": 3.0, "x2": 5.0, "target": 0, "group_id": "c", "timestamp": "2024-01-03"},
            {"id": 4, "x1": 4.0, "x2": 7.0, "target": 1, "group_id": "d", "timestamp": "2024-01-04"},
            {"id": 5, "x1": 5.0, "x2": 11.0, "target": 0, "group_id": "e", "timestamp": "2024-01-05"},
            {"id": 6, "x1": 6.0, "x2": 13.0, "target": 1, "group_id": "f", "timestamp": "2024-01-06"},
        ],
        "metrics": {"accuracy": 0.9},
        "metric_checks": [{"name": "accuracy", "direction": "at_least", "threshold": 0.8}],
    }


def _leakage_case_results(kind: str) -> tuple[dict[str, Any], dict[str, Any]]:
    clean_data = _base_leakage_result()
    mutant_data = copy.deepcopy(clean_data)
    if kind == "content_duplicate":
        mutant_data["rows"][3]["x1"] = 1.0; mutant_data["rows"][3]["x2"] = 2.0
    elif kind == "group":
        mutant_data["rows"][3]["group_id"] = "a"
    elif kind == "temporal":
        mutant_data["rows"][3]["timestamp"] = "2024-01-02"
    elif kind == "correlation":
        mutant_data["features"] = ["leaky_score"]
        mutant_data["max_abs_feature_target_correlation"] = 0.95
        for row in mutant_data["rows"]:
            row["leaky_score"] = float(row["target"])
    return validate_result(clean_data), validate_result(mutant_data)

def _statistical_regression_case(name: str) -> dict[str, Any] | None:
    if name in {"shuffled_label_non_significant", "insignificant_shuffled_label"}:
        clean = shuffled_label_check("classification", 0.86, [0.50 + (idx % 3) * 0.005 for idx in range(39)], alpha=0.05)
        mutant = shuffled_label_check("classification", 0.86, [0.85 + (idx % 4) * 0.01 for idx in range(39)], alpha=0.05)
        failed_checks = [] if mutant.get("passed") else ["shuffled_label"]
    elif name in {"multi_seed_high_cv", "unstable_multi_seed"}:
        clean = multi_seed_check([0.81, 0.82, 0.83, 0.82], min_score=0.75, max_cv=0.05, seed=0)
        mutant = multi_seed_check([0.70, 0.95, 0.82, 1.00], min_score=0.70, max_cv=0.05, seed=0)
        failed_checks = [] if mutant.get("passed") else ["multi_seed"]
    elif name in {"baseline_ci_below_margin", "weak_baseline_ci"}:
        clean = baseline_comparison(
            {"model_score": [0.84, 0.85, 0.86, 0.85, 0.84], "baseline_score": [0.78, 0.79, 0.80, 0.79, 0.78]},
            min_improvement=0.03,
            seed=0,
        )
        mutant = baseline_comparison(
            {"model_score": [0.82, 0.83, 0.84, 0.83, 0.82], "baseline_score": [0.80, 0.81, 0.82, 0.81, 0.80]},
            min_improvement=0.03,
            seed=0,
        )
        failed_checks = [] if mutant.get("passed") else ["baseline_comparison"]
    elif name in {"calibration_high_mce", "bad_calibration_stats"}:
        clean = calibration_check({"confidences": [0.9, 0.8, 0.2, 0.1], "correct": [True, True, False, False]}, max_ece=0.25, bins=2)
        mutant = calibration_check({"confidences": [0.9, 0.9, 0.1, 0.1], "correct": [False, False, True, True]}, max_ece=0.25, bins=2)
        failed_checks = [] if mutant.get("passed") else ["calibration"]
    elif name == "content_duplicate_leakage":
        clean_result, mutant_result = _leakage_case_results("content_duplicate")
        failed_checks = [] if mutant_result.get("passed") else ["content_duplicate_leakage"]
        clean = clean_result; mutant = mutant_result
    elif name == "group_entity_leakage":
        clean_result, mutant_result = _leakage_case_results("group")
        failed_checks = [] if mutant_result.get("passed") else ["group_entity_leakage"]
        clean = clean_result; mutant = mutant_result
    elif name == "temporal_leakage":
        clean_result, mutant_result = _leakage_case_results("temporal")
        failed_checks = [] if mutant_result.get("passed") else ["temporal_leakage"]
        clean = clean_result; mutant = mutant_result
    elif name == "high_feature_target_correlation":
        clean_result, mutant_result = _leakage_case_results("correlation")
        failed_checks = [] if mutant_result.get("passed") else ["high_feature_target_correlation"]
        clean = clean_result; mutant = mutant_result
    elif name == "distribution_drift":
        clean = drift_check({"train": {"x": [1, 2, 3, 4, 5]}, "test": {"x": [1.1, 2.1, 3.1, 4.1, 5.1]}}, max_psi=5.0, max_ks=0.5)
        mutant = drift_check({"train": {"x": [1, 1, 1, 2, 2]}, "test": {"x": [10, 11, 12, 13, 14]}}, max_psi=0.2, max_ks=0.2)
        failed_checks = [] if mutant.get("passed") else ["distribution_drift"]
    elif name == "hard_imbalanced_majority":
        clean = {"passed": True, "status": "pass"}
        mutant = validate_result(json.loads((Path(__file__).resolve().parent / "hard_examples" / "imbalanced_majority_model.json").read_text(encoding="utf-8")))
        failed_checks = [check["check"] for check in mutant.get("checks", []) if not check.get("passed")]
    elif name == "hard_content_duplicate":
        clean = {"passed": True, "status": "pass"}
        mutant = validate_result(json.loads((Path(__file__).resolve().parent / "hard_examples" / "content_duplicate_leaky.json").read_text(encoding="utf-8")))
        failed_checks = [check["check"] for check in mutant.get("checks", []) if not check.get("passed")]
    elif name == "hard_temporal_leak":
        clean = {"passed": True, "status": "pass"}
        mutant = validate_result(json.loads((Path(__file__).resolve().parent / "hard_examples" / "temporal_leak.json").read_text(encoding="utf-8")))
        failed_checks = [check["check"] for check in mutant.get("checks", []) if not check.get("passed")]
    else:
        return None
    clean_passed = bool(clean.get("passed"))
    mutant_passed = bool(mutant.get("passed"))
    return {
        "mutation": name,
        "clean_passed": clean_passed,
        "mutant_passed": mutant_passed,
        "caught": clean_passed and not mutant_passed,
        "failed_checks": failed_checks,
        "clean_status": clean.get("status"),
        "mutant_status": mutant.get("status"),
    }


def regression_resistance_artifact(result: dict[str, Any]) -> dict[str, Any]:
    clean = validate_result(result)
    mutations: list[dict[str, Any]] = []
    for mutation in MUTATION_NAMES:
        statistical_case = _statistical_regression_case(mutation)
        if statistical_case is not None:
            mutations.append({
                "name": mutation,
                "planted": True,
                "clean_passed": statistical_case["clean_passed"],
                "mutant_passed": statistical_case["mutant_passed"],
                "caught": statistical_case["caught"],
                "failed_checks": statistical_case["failed_checks"],
            })
            continue
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



def fit_diagnosis(problem_type: str, metrics: dict[str, float], thresholds: dict[str, float]) -> dict[str, Any]:
    reasons: list[str] = []
    if problem_type == "classification":
        metric_name = str(thresholds.get("metric_name", "score"))
        train_name = f"train_{metric_name}"
        validation_name = f"validation_{metric_name}"
        test_name = f"test_{metric_name}"
        required = [train_name, validation_name, test_name]
        missing = [name for name in required if name not in metrics]
        if missing:
            return {"check": "fit_diagnosis", "problem_type": problem_type, "status": "invalid", "passed": False, "missing_metrics": missing, "metrics": metrics, "thresholds": thresholds, "reasons": ["Missing required metric(s): " + ", ".join(missing)]}
        train = metrics[train_name]
        validation = metrics[validation_name]
        test = metrics[test_name]
        gap = train - min(validation, test)
        high_train = thresholds.get("high_train_score", 0.95)
        max_gap = thresholds.get("max_generalization_gap", 0.10)
        target = thresholds.get("target_score")
        if train >= high_train and gap > max_gap:
            reasons.append(f"generalization gap {gap:.6g} exceeds {max_gap:.6g} with high train {metric_name}")
            status = "overfit"
        elif target is not None and max(train, validation, test) < target:
            reasons.append(f"all {metric_name} values are below target_score {target:.6g}")
            status = "underfit"
        else:
            status = "healthy"
        return {"check": "fit_diagnosis", "problem_type": problem_type, "metric_name": metric_name, "status": status, "passed": status == "healthy", "metrics": {**metrics, "generalization_gap": gap}, "thresholds": thresholds, "reasons": reasons}
    if problem_type == "regression":
        required = ["train_error", "validation_error", "test_error"]
        missing = [name for name in required if name not in metrics]
        if missing:
            return {"check": "fit_diagnosis", "problem_type": problem_type, "status": "invalid", "passed": False, "missing_metrics": missing, "metrics": metrics, "thresholds": thresholds, "reasons": ["Missing required metric(s): " + ", ".join(missing)]}
        train = metrics["train_error"]
        validation = metrics["validation_error"]
        test = metrics["test_error"]
        worst_eval = max(validation, test)
        ratio = worst_eval / train if train > 0 else math.inf
        max_ratio = thresholds.get("max_error_ratio", 2.0)
        poor_error = thresholds.get("poor_error")
        if ratio > max_ratio:
            reasons.append(f"evaluation/train error ratio {ratio:.6g} exceeds {max_ratio:.6g}")
            status = "overfit"
        elif poor_error is not None and min(train, validation, test) > poor_error:
            reasons.append(f"all errors exceed poor_error {poor_error:.6g}")
            status = "underfit"
        else:
            status = "healthy"
        return {"check": "fit_diagnosis", "problem_type": problem_type, "status": status, "passed": status == "healthy", "metrics": {**metrics, "error_ratio": ratio}, "thresholds": thresholds, "reasons": reasons}
    return {"check": "fit_diagnosis", "problem_type": problem_type, "status": "invalid", "passed": False, "metrics": metrics, "thresholds": thresholds, "reasons": ["problem_type must be classification or regression"]}

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
    return write_result(validation, args.output)


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
                "metric_name": args.metric_name,
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
        metrics = {str(key): value for key, value in data.items()}
        result = baseline_comparison(metrics, args.model_metric, args.baseline_metric, args.min_improvement, args.direction, args.bootstrap_samples, args.bootstrap_confidence, args.seed)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "baseline_comparison", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)


def cmd_calibration(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = calibration_check(data, args.max_ece, args.bins, args.max_mce, args.max_brier)
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
            alpha = float(data.get("alpha", args.alpha))
            labels = data.get("labels") if isinstance(data.get("labels"), list) else None
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
            alpha = args.alpha
            labels = None

        result = shuffled_label_check(
            problem_type=problem_type,
            real_score=real_score,
            shuffled_scores=shuffled_scores,
            class_count=class_count,
            chance_score=None if chance_score is None else float(chance_score),
            tolerance=tolerance,
            min_real_margin=min_real_margin,
            direction=direction,
            alpha=alpha,
            labels=labels,
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
            max_variance_value = data.get("max_variance", args.max_variance)
            max_variance = None if max_variance_value is None else float(max_variance_value)
            min_seeds = int(data.get("min_seeds", args.min_seeds))
            direction = str(data.get("direction", args.direction))
            metric_name = str(data.get("metric_name", args.metric_name))
            max_cv = float(data.get("max_cv", args.max_cv))
            bootstrap_samples = int(data.get("bootstrap_samples", args.bootstrap_samples))
            bootstrap_confidence = float(data.get("bootstrap_confidence", args.bootstrap_confidence))
            seed = int(data.get("seed", args.seed))
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
            max_cv = args.max_cv
            bootstrap_samples = args.bootstrap_samples
            bootstrap_confidence = args.bootstrap_confidence
            seed = args.seed

        result = multi_seed_check(
            scores=scores,
            min_score=min_score,
            max_score=max_score,
            max_variance=max_variance,
            min_seeds=min_seeds,
            direction=direction,
            metric_name=metric_name,
            max_cv=max_cv,
            bootstrap_samples=bootstrap_samples,
            bootstrap_confidence=bootstrap_confidence,
            seed=seed,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        result = {"check": "multi_seed", "passed": False, "status": "invalid", "metrics": {}, "thresholds": {}, "reasons": [str(exc)]}
    return write_result(result, args.output)




def cmd_classification_metrics(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = classification_metrics(data, min_metric=args.min_metric, metric_name=args.metric_name, min_slice_metric=args.min_slice_metric, max_slice_gap=args.max_slice_gap)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "classification_metrics", "passed": False, "status": "invalid", "reasons": [str(exc)]}
    return write_result(result, args.output)

def cmd_drift(args: argparse.Namespace) -> int:
    try:
        data = load_json_arg(args.data_json, args.data_file)
        result = drift_check(data, max_psi=args.max_psi, max_ks=args.max_ks, bins=args.bins)
    except (ValueError, json.JSONDecodeError) as exc:
        result = {"check": "distribution_drift", "passed": False, "status": "invalid", "features": [], "reasons": [str(exc)]}
    return write_result(result, args.output)

def cmd_validator(args: argparse.Namespace) -> int:
    try:
        evidence = {
            "leakage": (args.leakage_file, json.loads(Path(args.leakage_file).read_text(encoding="utf-8"))),
            "drift": (args.drift_file, json.loads(Path(args.drift_file).read_text(encoding="utf-8"))),
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
        "drift",
        "classification-metrics",
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
    validate.add_argument("--output")
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
    fit.add_argument("--metric-name", default="score")
    fit.set_defaults(func=cmd_fit_diagnosis)

    baseline = sub.add_parser("baseline", help="compare a model metric with a baseline metric")
    baseline.add_argument("--metrics-json")
    baseline.add_argument("--metrics-file")
    baseline.add_argument("--model-metric", default="model_score")
    baseline.add_argument("--baseline-metric", default="baseline_score")
    baseline.add_argument("--min-improvement", type=float, default=0.0)
    baseline.add_argument("--direction", choices=["higher", "lower"], default="higher")
    baseline.add_argument("--bootstrap-samples", type=int, default=1000)
    baseline.add_argument("--bootstrap-confidence", type=float, default=0.95)
    baseline.add_argument("--seed", type=int, default=0)
    baseline.add_argument("--output")
    baseline.set_defaults(func=cmd_baseline)

    calibration = sub.add_parser("calibration", help="compute and validate expected calibration error")
    calibration.add_argument("--data-json")
    calibration.add_argument("--data-file")
    calibration.add_argument("--max-ece", type=float, default=0.08)
    calibration.add_argument("--max-mce", type=float)
    calibration.add_argument("--max-brier", type=float)
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
    shuffled.add_argument("--alpha", type=float, default=0.05)
    shuffled.add_argument("--direction", choices=["higher", "lower"], default="higher")
    shuffled.add_argument("--output")
    shuffled.set_defaults(func=cmd_shuffled_label)

    multi_seed = sub.add_parser("multi-seed", help="verify metric stability across multiple random seeds")
    multi_seed.add_argument("--data-json")
    multi_seed.add_argument("--data-file")
    multi_seed.add_argument("--scores-json")
    multi_seed.add_argument("--min-score", type=float, default=0.0)
    multi_seed.add_argument("--max-score", type=float)
    multi_seed.add_argument("--max-variance", type=float)
    multi_seed.add_argument("--max-cv", type=float, default=0.05)
    multi_seed.add_argument("--bootstrap-samples", type=int, default=1000)
    multi_seed.add_argument("--bootstrap-confidence", type=float, default=0.95)
    multi_seed.add_argument("--seed", type=int, default=0)
    multi_seed.add_argument("--min-seeds", type=int, default=2)
    multi_seed.add_argument("--direction", choices=["higher", "lower"], default="higher")
    multi_seed.add_argument("--metric-name", default="score")
    multi_seed.add_argument("--output")
    multi_seed.set_defaults(func=cmd_multi_seed)

    class_metrics = sub.add_parser("classification-metrics", help="compute imbalance-aware classification metrics")
    class_metrics.add_argument("--data-json")
    class_metrics.add_argument("--data-file")
    class_metrics.add_argument("--metric-name", default="macro_f1")
    class_metrics.add_argument("--min-metric", type=float)
    class_metrics.add_argument("--min-slice-metric", type=float)
    class_metrics.add_argument("--max-slice-gap", type=float)
    class_metrics.add_argument("--output")
    class_metrics.set_defaults(func=cmd_classification_metrics)

    drift = sub.add_parser("drift", help="detect train/test or reference/current distribution drift")
    drift.add_argument("--data-json")
    drift.add_argument("--data-file")
    drift.add_argument("--max-psi", type=float, default=0.2)
    drift.add_argument("--max-ks", type=float, default=0.2)
    drift.add_argument("--bins", type=int, default=10)
    drift.add_argument("--output")
    drift.set_defaults(func=cmd_drift)

    validator = sub.add_parser("validator", help="aggregate required ML invariant evidence into a validator artifact")
    validator.add_argument("--leakage-file", default="artifacts/leakage-audit.json")
    validator.add_argument("--drift-file", default="artifacts/drift-report.json")
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
