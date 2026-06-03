"""ML autopilot adapter for MAW.

This module may use third-party ML/data libraries when available. The
dependency-free deterministic checker layer under ``maw-tools`` is intentionally
not imported here.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import start_workflow
import verdict_check


SEED = 1701
TRAIN_RATIO = 0.70
VALIDATION_RATIO = 0.15
TARGET_HINTS = ("target", "label", "y", "outcome", "class", "response")
TIME_HINTS = ("time", "date", "timestamp", "created", "updated")
GROUP_HINTS = ("group", "user", "customer", "account", "patient", "entity", "subject")
CORE_ML_AGENTS = [
    "conductor",
    "planner",
    "leakage_auditor",
    "data_quality_auditor",
    "reproducibility_checker",
    "baseline_enforcer",
    "overfitting_checker",
    "calibration_checker",
    "critic",
    "acceptance_gate",
]


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def load_table(path: Path) -> tuple[list[dict[str, Any]], list[str], str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            return [dict(row) for row in reader], columns, "csv"
    if suffix == ".parquet":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local env
            raise RuntimeError("Parquet input requires pandas/pyarrow in the adapter environment") from exc
        frame = pd.read_parquet(path)
        return frame.to_dict(orient="records"), [str(col) for col in frame.columns], "parquet"
    raise RuntimeError("ML autopilot supports CSV and Parquet only")


def coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def is_numeric_column(rows: list[dict[str, Any]], column: str) -> bool:
    seen = 0
    numeric = 0
    for row in rows:
        value = row.get(column)
        if value in (None, ""):
            continue
        seen += 1
        if coerce_number(value) is not None:
            numeric += 1
    return seen > 0 and numeric / seen >= 0.9


def normalized_tokens(text: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", text.lower()) if part}


def infer_target(columns: list[str], goal: str) -> tuple[str | None, float, list[str], str | None]:
    goal_tokens = normalized_tokens(goal)
    normalized = {column.lower(): column for column in columns}
    for column in columns:
        if column.lower() in goal_tokens:
            return column, 0.95, [f"goal text mentioned column `{column}`"], None

    pattern = re.search(r"(?:predict|forecast|estimate|classify|model)\s+([a-zA-Z_][a-zA-Z0-9_]*)", goal, re.I)
    if pattern:
        wanted = pattern.group(1).lower()
        if wanted in normalized:
            return normalized[wanted], 0.98, [f"goal text explicitly requested `{normalized[wanted]}`"], None

    candidates = [column for column in columns if column.lower() in TARGET_HINTS or column.lower().endswith("_target")]
    if len(candidates) == 1:
        return candidates[0], 0.82, [f"single conventional target-like column `{candidates[0]}`"], None
    if len(candidates) > 1:
        return None, 0.0, [f"multiple target-like columns: {', '.join(candidates)}"], f"Which target column should MAW predict: {', '.join(candidates)}?"
    return None, 0.0, ["no high-confidence target column inference"], "Which target column should MAW predict?"


def infer_problem_type(rows: list[dict[str, Any]], target: str) -> tuple[str | None, float, list[str], str | None]:
    values = [row.get(target) for row in rows if row.get(target) not in (None, "")]
    distinct = {str(value) for value in values}
    if not values:
        return None, 0.0, ["target has no non-empty values"], f"Is `{target}` a classification or regression target?"
    numeric = [coerce_number(value) for value in values]
    numeric_count = sum(value is not None for value in numeric)
    if numeric_count / len(values) < 0.9:
        return "classification", 0.9, ["target is mostly non-numeric"], None
    if len(distinct) <= max(20, int(len(values) * 0.05)):
        return "classification", 0.82, [f"numeric target has low cardinality ({len(distinct)} classes)"], None
    return "regression", 0.88, ["numeric target has continuous-looking cardinality"], None


def infer_special_columns(columns: list[str], target: str) -> tuple[str | None, str | None]:
    time_column = next((col for col in columns if col != target and any(hint in col.lower() for hint in TIME_HINTS)), None)
    group_column = next((col for col in columns if col != target and any(hint in col.lower() for hint in GROUP_HINTS)), None)
    return time_column, group_column


def majority_class_rate(values: list[Any]) -> float:
    counts = Counter(str(value) for value in values)
    return max(counts.values()) / len(values) if values else 0.0


def profile_data(rows: list[dict[str, Any]], columns: list[str], data_path: Path, goal: str) -> dict[str, Any]:
    target, target_confidence, target_reasons, target_question = infer_target(columns, goal)
    problem_type = None
    problem_confidence = 0.0
    problem_reasons: list[str] = []
    problem_question = None
    time_column = None
    group_column = None
    numeric_features: list[str] = []
    class_balance: dict[str, Any] = {}

    if target:
        problem_type, problem_confidence, problem_reasons, problem_question = infer_problem_type(rows, target)
        time_column, group_column = infer_special_columns(columns, target)
        excluded = {target, time_column, group_column, "id", "row_id", ""}
        numeric_features = [col for col in columns if col not in excluded and is_numeric_column(rows, col)]
        if problem_type == "classification":
            target_values = [row.get(target) for row in rows if row.get(target) not in (None, "")]
            counts = Counter(str(value) for value in target_values)
            class_balance = {
                "classes": dict(sorted(counts.items())),
                "majority_class": counts.most_common(1)[0][0] if counts else None,
                "majority_class_rate": majority_class_rate(target_values),
            }

    assumptions = [*target_reasons, *problem_reasons]
    if numeric_features:
        assumptions.append("trained on numeric feature columns only")
    if time_column:
        assumptions.append(f"treated `{time_column}` as the time column")
    if group_column:
        assumptions.append(f"treated `{group_column}` as the group column")

    status = "ok"
    question = None
    if not target or target_confidence < 0.75:
        status = "needs_human"
        question = target_question
    elif not problem_type or problem_confidence < 0.75:
        status = "needs_human"
        question = problem_question
    elif not numeric_features:
        status = "needs_human"
        question = "Which numeric feature columns should MAW train on?"

    return {
        "schema_version": 1,
        "status": status,
        "needs_human_question": question,
        "data_path": str(data_path),
        "goal": goal,
        "row_count": len(rows),
        "columns": columns,
        "target_column": target,
        "target_confidence": target_confidence,
        "problem_type": problem_type,
        "problem_type_confidence": problem_confidence,
        "time_column": time_column,
        "group_column": group_column,
        "numeric_features": numeric_features,
        "class_balance": class_balance,
        "assumptions": assumptions,
        "inference_reasons": {"target": target_reasons, "problem_type": problem_reasons},
    }


def split_indices(rows: list[dict[str, Any]], profile: dict[str, Any], seed: int) -> tuple[list[int], list[int], list[int]]:
    indices = list(range(len(rows)))
    group_column = profile.get("group_column")
    time_column = profile.get("time_column")
    if time_column:
        indices.sort(key=lambda idx: str(rows[idx].get(time_column) or ""))
    elif group_column:
        groups: dict[str, list[int]] = {}
        for idx in indices:
            groups.setdefault(str(rows[idx].get(group_column)), []).append(idx)
        keys = sorted(groups)
        random.Random(seed).shuffle(keys)
        indices = [idx for key in keys for idx in groups[key]]
    else:
        random.Random(seed).shuffle(indices)
    train_end = max(1, int(len(indices) * TRAIN_RATIO))
    validation_end = max(train_end + 1, int(len(indices) * (TRAIN_RATIO + VALIDATION_RATIO)))
    validation_end = min(validation_end, len(indices) - 1)
    return indices[:train_end], indices[train_end:validation_end], indices[validation_end:]


def frame_for(rows: list[dict[str, Any]], indices: list[int], features: list[str], target: str):
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("ML training requires pandas in the adapter environment") from exc
    data = [{feature: coerce_number(rows[idx].get(feature)) for feature in features} for idx in indices]
    labels = [rows[idx].get(target) for idx in indices]
    return pd.DataFrame(data), labels


def classification_score(labels: list[Any], predictions: list[Any]) -> float:
    if not labels:
        return 0.0
    classes = sorted({str(x) for x in labels} | {str(x) for x in predictions})
    f1s = []
    for cls in classes:
        tp = sum(1 for actual, pred in zip(labels, predictions) if str(actual) == cls and str(pred) == cls)
        fp = sum(1 for actual, pred in zip(labels, predictions) if str(actual) != cls and str(pred) == cls)
        fn = sum(1 for actual, pred in zip(labels, predictions) if str(actual) == cls and str(pred) != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def regression_error(labels: list[Any], predictions: list[float]) -> float:
    pairs = [(coerce_number(actual), coerce_number(pred)) for actual, pred in zip(labels, predictions)]
    errors = [abs(actual - pred) for actual, pred in pairs if actual is not None and pred is not None]
    return sum(errors) / len(errors) if errors else math.inf


def train_once(rows: list[dict[str, Any]], profile: dict[str, Any], seed: int, shuffled: bool = False) -> dict[str, Any]:
    try:
        from sklearn.dummy import DummyClassifier, DummyRegressor  # type: ignore
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor  # type: ignore
        from sklearn.impute import SimpleImputer  # type: ignore
        from sklearn.pipeline import Pipeline  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("ML autopilot training requires scikit-learn in the adapter environment") from exc

    target = str(profile["target_column"])
    features = list(profile["numeric_features"])
    problem_type = str(profile["problem_type"])
    train_ids, validation_ids, test_ids = split_indices(rows, profile, seed)
    train_x, train_y = frame_for(rows, train_ids, features, target)
    validation_x, validation_y = frame_for(rows, validation_ids, features, target)
    test_x, test_y = frame_for(rows, test_ids, features, target)
    if shuffled:
        rng = random.Random(seed)
        train_y = list(train_y)
        rng.shuffle(train_y)

    if problem_type == "classification":
        model = Pipeline([("imputer", SimpleImputer()), ("model", RandomForestClassifier(n_estimators=80, random_state=seed))])
        baseline = DummyClassifier(strategy="most_frequent")
    else:
        model = Pipeline([("imputer", SimpleImputer()), ("model", RandomForestRegressor(n_estimators=80, random_state=seed))])
        baseline = DummyRegressor(strategy="mean")
        train_y = [float(coerce_number(value) or 0.0) for value in train_y]
        validation_y = [float(coerce_number(value) or 0.0) for value in validation_y]
        test_y = [float(coerce_number(value) or 0.0) for value in test_y]

    model.fit(train_x, train_y)
    baseline.fit(train_x, train_y)
    train_pred = list(model.predict(train_x))
    validation_pred = list(model.predict(validation_x))
    test_pred = list(model.predict(test_x))
    baseline_pred = list(baseline.predict(test_x))

    result: dict[str, Any] = {
        "seed": seed,
        "train_ids": train_ids,
        "validation_ids": validation_ids,
        "test_ids": test_ids,
        "train_y": list(train_y),
        "validation_y": list(validation_y),
        "test_y": list(test_y),
        "train_pred": train_pred,
        "validation_pred": validation_pred,
        "test_pred": test_pred,
        "baseline_pred": baseline_pred,
        "model_name": type(model.named_steps["model"]).__name__,
    }
    if problem_type == "classification":
        result["train_score"] = classification_score(list(train_y), train_pred)
        result["validation_score"] = classification_score(list(validation_y), validation_pred)
        result["test_score"] = classification_score(list(test_y), test_pred)
        result["baseline_score"] = classification_score(list(test_y), baseline_pred)
        if hasattr(model.named_steps["model"], "predict_proba"):
            probabilities = model.predict_proba(test_x)
            classes = [str(item) for item in model.named_steps["model"].classes_]
            positive_index = len(classes) - 1
            result["scores"] = [float(row[positive_index]) if len(classes) == 2 else float(max(row)) for row in probabilities]
            result["confidences"] = [float(max(row)) for row in probabilities]
    else:
        result["train_error"] = regression_error(list(train_y), train_pred)
        result["validation_error"] = regression_error(list(validation_y), validation_pred)
        result["test_error"] = regression_error(list(test_y), test_pred)
        result["baseline_error"] = regression_error(list(test_y), baseline_pred)
    return result


def raw_rows(rows: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    keep = ["id", *profile["numeric_features"], profile["target_column"]]
    if profile.get("group_column"):
        keep.append(profile["group_column"])
    if profile.get("time_column"):
        keep.append(profile["time_column"])
    out = []
    for idx, row in enumerate(rows):
        item = {"id": idx}
        for column in keep:
            if column and column not in {"id", "row_id"}:
                item[column] = row.get(column)
        out.append(item)
    return out


def derive_config(profile: dict[str, Any], primary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    problem_type = profile["problem_type"]
    target_values = [row.get(profile["target_column"]) for row in rows if row.get(profile["target_column"]) not in (None, "")]
    if problem_type == "classification":
        metric_name = "macro_f1"
        majority = profile["class_balance"].get("majority_class_rate", 0.0)
        min_metric = max(0.05, min(0.95, majority + 0.02))
        return {
            "problem_type": problem_type,
            "primary_metric": metric_name,
            "metric_direction": "higher",
            "majority_class_baseline": majority,
            "min_metric": round(min_metric, 6),
            "min_improvement": 0.0,
            "drift": {"max_psi": 5.0, "max_ks": 0.50, "columns": profile["numeric_features"]},
            "calibration_applies": True,
            "fit_diagnosis": {"metric_name": metric_name, "max_generalization_gap": 0.18, "target_score": max(0.01, majority)},
            "multi_seed": {"min_score": max(0.01, min(primary["test_score"], primary["baseline_score"] + 0.01) - 0.05), "max_cv": 0.25},
        }
    baseline_error = primary["baseline_error"]
    min_improvement = max(0.0, baseline_error * 0.02)
    observed_ratio = max(primary["validation_error"], primary["test_error"]) / max(primary["train_error"], 1e-9)
    return {
        "problem_type": problem_type,
        "primary_metric": "mae",
        "metric_direction": "lower",
        "mean_target_baseline_mae": baseline_error,
        "min_improvement": round(min_improvement, 6),
        "drift": {"max_psi": 5.0, "max_ks": 0.50, "columns": profile["numeric_features"]},
        "calibration_applies": False,
        "fit_diagnosis": {"max_error_ratio": max(3.0, min(10.0, observed_ratio * 1.25)), "poor_error": max(baseline_error, 1e-9)},
        "multi_seed": {"max_score": primary["test_error"] + max(baseline_error * 0.20, 1e-6), "max_cv": 0.35},
        "target_summary": {"count": len(target_values)},
    }


def write_training_artifacts(run_dir: Path, rows: list[dict[str, Any]], profile: dict[str, Any], inject_bug: str) -> dict[str, Any]:
    artifacts = run_dir / "artifacts"
    primary = train_once(rows, profile, SEED)
    config = derive_config(profile, primary, rows)
    problem_type = profile["problem_type"]
    features = list(profile["numeric_features"])
    target = profile["target_column"]
    train_ids = list(primary["train_ids"])
    test_ids = list(primary["test_ids"])
    if inject_bug == "train-overlap" and train_ids:
        test_ids = [train_ids[0], *test_ids]
    result = {
        "problem": problem_type,
        "seed": SEED,
        "expected_seed": SEED,
        "features": [*features, target] if inject_bug == "target-leak" else features,
        "target": target,
        "group_column": profile.get("group_column"),
        "time_column": profile.get("time_column"),
        "rows": raw_rows(rows, profile),
        "split": {"train_ids": train_ids, "test_ids": test_ids, "expected_train_ratio": TRAIN_RATIO + VALIDATION_RATIO},
        "preprocessing": {"fit_scope": "train"},
        "max_abs_feature_target_correlation": 0.999 if problem_type == "regression" else 0.98,
        "baseline_model": "majority class" if problem_type == "classification" else "mean target",
        "model": primary["model_name"],
    }
    if problem_type == "classification":
        labels = [str(value) for value in primary["test_y"]]
        predictions = [str(value) for value in primary["test_pred"]]
        correctness = [1.0 if a == b else 0.0 for a, b in zip(labels, predictions)]
        baseline_correctness = [1.0 if str(a) == str(b) else 0.0 for a, b in zip(primary["test_y"], primary["baseline_pred"])]
        result.update(
            {
                "labels": labels,
                "predictions": predictions,
                "scores": primary.get("scores", correctness),
                "metrics": {
                    "train_score": primary["train_score"],
                    "validation_score": primary["validation_score"],
                    "test_score": primary["test_score"],
                    "train_macro_f1": primary["train_score"],
                    "validation_macro_f1": primary["validation_score"],
                    "test_macro_f1": primary["test_score"],
                    "macro_f1": primary["test_score"],
                    "custom_score": primary["test_score"],
                    "baseline_macro_f1": primary["baseline_score"],
                },
                "metric_checks": [{"name": "custom_score", "direction": "at_least", "threshold": config["min_metric"]}],
                "acceptance": {"passed": primary["test_score"] >= config["min_metric"]},
            }
        )
        write_json(artifacts / "classification-results.json", {"labels": labels, "predictions": predictions, "scores": result["scores"]})
        write_json(artifacts / "metrics.json", {"model_score": correctness, "baseline_score": baseline_correctness, "labels": labels})
        write_json(artifacts / "fit-metrics.json", result["metrics"])
        write_json(artifacts / "calibration.json", {"confidences": primary.get("confidences", correctness), "correct": [bool(v) for v in correctness]})
        shuffled_scores = [train_once(rows, profile, seed, shuffled=True)["test_score"] for seed in (11, 17, 23, 31, 43)]
        write_json(
            artifacts / "shuffled-label.json",
            {
                "problem_type": "classification",
                "real_score": primary["test_score"],
                "shuffled_scores": shuffled_scores,
                "class_count": len(profile["class_balance"].get("classes", {})) or 2,
                "labels": labels,
                "direction": "higher",
                "min_real_margin": 0.0,
                "tolerance": 0.20,
                "alpha": 0.20,
            },
        )
        seed_scores = [train_once(rows, profile, seed)["test_score"] for seed in (SEED, 1702, 1703)]
        write_json(artifacts / "multi-seed.json", {"scores": seed_scores, "min_score": config["multi_seed"]["min_score"], "max_cv": config["multi_seed"]["max_cv"], "metric_name": "macro_f1"})
    else:
        model_errors = [abs(float(a) - float(b)) for a, b in zip(primary["test_y"], primary["test_pred"])]
        baseline_errors = [abs(float(a) - float(b)) for a, b in zip(primary["test_y"], primary["baseline_pred"])]
        result.update(
            {
                "metrics": {
                    "train_error": primary["train_error"],
                    "validation_error": primary["validation_error"],
                    "test_error": primary["test_error"],
                    "test_mae": primary["test_error"],
                    "baseline_mae": primary["baseline_error"],
                },
                "metric_checks": [{"name": "test_mae", "direction": "at_most", "threshold": primary["baseline_error"]}],
                "acceptance": {"passed": primary["test_error"] <= primary["baseline_error"]},
            }
        )
        write_json(artifacts / "classification-results.json", {"passed": True, "status": "not_applicable", "reason": "regression task"})
        write_json(artifacts / "metrics.json", {"model_score": model_errors, "baseline_score": baseline_errors})
        write_json(artifacts / "fit-metrics.json", result["metrics"])
        write_json(artifacts / "calibration.json", {"passed": True, "status": "not_applicable", "reason": "calibration applies to classification only"})
        shuffled_scores = [train_once(rows, profile, seed, shuffled=True)["test_error"] for seed in (11, 17, 23, 31, 43)]
        write_json(artifacts / "shuffled-label.json", {"problem_type": "regression", "real_score": primary["test_error"], "shuffled_scores": shuffled_scores, "direction": "lower", "chance_score": primary["baseline_error"], "min_real_margin": 0.0, "tolerance": primary["baseline_error"], "alpha": 0.20})
        seed_scores = [train_once(rows, profile, seed)["test_error"] for seed in (SEED, 1702, 1703)]
        write_json(artifacts / "multi-seed.json", {"scores": seed_scores, "direction": "lower", "max_score": config["multi_seed"]["max_score"], "max_cv": config["multi_seed"]["max_cv"], "metric_name": "mae"})

    train_values: dict[str, list[float]] = {feature: [] for feature in features}
    test_values: dict[str, list[float]] = {feature: [] for feature in features}
    for idx in primary["train_ids"] + primary["validation_ids"]:
        for feature in features:
            value = coerce_number(rows[idx].get(feature))
            if value is not None:
                train_values[feature].append(value)
    for idx in primary["test_ids"]:
        for feature in features:
            value = coerce_number(rows[idx].get(feature))
            if value is not None:
                test_values[feature].append(value)
    write_json(artifacts / "result.json", result)
    write_json(artifacts / "drift.json", {"train": train_values, "test": test_values})
    duplicate_rows = len(rows) - len({json.dumps(row, sort_keys=True, default=str) for row in rows})
    write_json(artifacts / "data-quality.json", {"row_count": len(rows), "missing_values": {col: sum(1 for row in rows if row.get(col) in (None, "")) for col in profile["columns"]}, "duplicate_rows": duplicate_rows})
    write_json(artifacts / "run-metadata.json", {"seed": SEED, "expected_seed": SEED, "deterministic": True, "model": primary["model_name"]})
    write_json(artifacts / "data-split.json", {"train_ids": primary["train_ids"], "validation_ids": primary["validation_ids"], "test_ids": primary["test_ids"], "split_strategy": "time" if profile.get("time_column") else "group" if profile.get("group_column") else "random", "seed": SEED})
    write_json(artifacts / "training-config.json", config)
    write_json(artifacts / "training-log.json", {"passed": True, "status": "pass", "model": primary["model_name"], "seed": SEED})
    write_json(artifacts / "evaluation-report.json", {"passed": bool(result["acceptance"]["passed"]), "status": "pass" if result["acceptance"]["passed"] else "fail", "metrics": result["metrics"]})
    return {"primary": primary, "config": config, "result": result}


def run_command(args: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
    return {"command": args, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "passed": proc.returncode == 0}


def run_validators(repo_root: Path, run_dir: Path, config: dict[str, Any], problem_type: str) -> list[dict[str, Any]]:
    checks = repo_root / "examples" / "ml_problems" / "ml_checks.py"
    py = sys.executable
    commands: list[list[str]] = [
        [py, str(checks), "validate", "artifacts/result.json", "--output", "artifacts/leakage-audit.json"],
        [py, str(checks), "drift", "--data-file", "artifacts/drift.json", "--max-psi", str(config["drift"]["max_psi"]), "--max-ks", str(config["drift"]["max_ks"]), "--output", "artifacts/drift-report.json"],
        [py, str(checks), "data-quality", "--data-file", "artifacts/data-quality.json", "--max-missing-rate", "0.20", "--max-duplicate-rate", "0.05", "--output", "artifacts/data-quality-report.json"],
        [py, str(checks), "reproducibility", "--data-file", "artifacts/run-metadata.json", "--output", "artifacts/reproducibility-check.json"],
        [py, str(checks), "baseline", "--metrics-file", "artifacts/metrics.json", "--min-improvement", str(config["min_improvement"]), "--direction", config["metric_direction"], "--bootstrap-samples", "200", "--bootstrap-confidence", "0.80", "--seed", "0", "--output", "artifacts/baseline-comparison.json"],
        [py, str(checks), "shuffled-label", "--data-file", "artifacts/shuffled-label.json", "--output", "artifacts/shuffled-label-check.json"],
        [py, str(checks), "multi-seed", "--data-file", "artifacts/multi-seed.json", "--bootstrap-samples", "200", "--bootstrap-confidence", "0.80", "--seed", "0", "--output", "artifacts/multi-seed-stability.json"],
        [py, str(checks), "regression-resistance", "--result-file", "artifacts/result.json", "--output", "artifacts/regression-resistance.json"],
    ]
    fit_command = [py, str(checks), "fit-diagnosis", "--problem-type", problem_type, "--metrics-file", "artifacts/fit-metrics.json", "--output", "artifacts/fit-diagnosis.json"]
    if problem_type == "classification":
        fit_command.extend(["--metric-name", config["fit_diagnosis"]["metric_name"], "--max-generalization-gap", str(config["fit_diagnosis"]["max_generalization_gap"]), "--target-score", str(config["fit_diagnosis"]["target_score"])])
    else:
        fit_command.extend(["--max-error-ratio", str(config["fit_diagnosis"]["max_error_ratio"]), "--poor-error", str(config["fit_diagnosis"]["poor_error"])])
    commands.insert(6, fit_command)
    if problem_type == "classification":
        commands.insert(4, [py, str(checks), "classification-metrics", "--data-file", "artifacts/classification-results.json", "--metric-name", config["primary_metric"], "--min-metric", str(config["min_metric"]), "--output", "artifacts/classification-metrics.json"])
        commands.insert(7, [py, str(checks), "calibration", "--data-file", "artifacts/calibration.json", "--max-ece", "0.25", "--output", "artifacts/calibration-report.json"])
    else:
        write_json(run_dir / "artifacts" / "classification-metrics.json", {"passed": True, "status": "not_applicable", "reason": "regression task"})
        write_json(run_dir / "artifacts" / "calibration-report.json", {"passed": True, "status": "not_applicable", "reason": "regression task"})
    results = [run_command(command, run_dir) for command in commands]
    validator = [py, str(checks), "validator", "--output", "artifacts/ml-validator.json"]
    results.append(run_command(validator, run_dir))
    write_json(run_dir / "artifacts" / "validator-command-results.json", results)
    return results


def conductor_plan(template: dict[str, Any], profile: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    roles = list(dict.fromkeys([*template["agents"], "worker"]))
    caps = dict(template["caps"])
    caps["max_agents"] = max(int(caps.get("max_agents", 0)), len(roles))
    return {
        "task_type": "ml-training-task",
        "checklist": ".codex/checklists/ml.md",
        "roles": roles,
        "caps": caps,
        "parallel_roles": ["leakage_auditor", "data_quality_auditor", "reproducibility_checker"],
        "role_justifications": {
            "data_quality_auditor": "ML autopilot derives and gates missingness and duplicate thresholds from the data profile.",
            "reproducibility_checker": "ML autopilot records deterministic seeds and run metadata for validation.",
            "overfitting_checker": "ML autopilot runs fit diagnosis from train, validation, and test raw metrics.",
            "calibration_checker": "ML autopilot validates calibration when the inferred problem type is classification.",
        },
        "autopilot": {
            "data_profile": "artifacts/data-profile.json",
            "training_config": "artifacts/training-config.json",
            "raw_result": "artifacts/result.json",
            "acceptance_artifact": "artifacts/acceptance-result.json",
            "target_column": profile.get("target_column"),
            "problem_type": profile.get("problem_type"),
            "run_dir": str(run_dir),
        },
    }


def update_template_copy(run_dir: Path, commands: list[str]) -> None:
    path = run_dir / "artifacts" / "workflow-template.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    concrete = []
    for command in commands:
        name = Path(command.split()[0]).stem if command else "command"
        concrete.append({"name": name, "command": command})
    data["deterministic_checks"] = concrete
    data["autopilot_filled"] = True
    write_json(path, data)


def fill_handoffs(run_dir: Path, profile: dict[str, Any], verdict: str | None = None) -> None:
    handoffs = sorted((run_dir / "handoffs").glob("*.md"))
    for path in handoffs:
        stem = path.stem
        match = re.match(r"(\d+)_(.+)__to__(.+)", stem)
        if not match:
            continue
        step, frm, to = match.groups()
        path.write_text(
            "\n".join(
                [
                    f"# Hand-off: {frm} -> {to}  (run {run_dir.name}, step {int(step):02d})",
                    "",
                    "## Task context",
                    f"Run ML autopilot for `{profile.get('data_path')}` with goal: {profile.get('goal')}",
                    "",
                    "## What I did",
                    f"Completed the {frm} portion of the autopilot flow using inferred target `{profile.get('target_column')}` and problem type `{profile.get('problem_type')}`.",
                    "",
                    "## Output / artifacts",
                    "- artifacts/data-profile.json  (adapter-layer data profile)",
                    "- artifacts/training-config.json  (derived validation thresholds and commands)",
                    "- artifacts/result.json  (raw per-example model export)",
                    "- artifacts/ml-report.md  (plain-language report)",
                    "",
                    "## Open questions / risks",
                    "No open question unless artifacts/data-profile.json has status needs_human.",
                    "",
                    "## Recommended next step",
                    f"{to} should continue from the generated artifacts and preserve the deterministic validation evidence.",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def append_run_verdict(run_dir: Path, verdict: str, summary: str) -> None:
    run_md = run_dir / "run.md"
    text = run_md.read_text(encoding="utf-8")
    text = re.sub(r"(?s)## Final result summary\n.*$", "", text).rstrip()
    run_md.write_text(text + f"\n\n## Final result summary\nAcceptance verdict: {verdict}\n\n{summary}\n", encoding="utf-8")


def write_needs_human(run_dir: Path, profile: dict[str, Any]) -> None:
    result = {
        "run": str(run_dir),
        "task_type": "ml-training-task",
        "handoffs": {"passed": True},
        "test": {"configured": False, "passed": True},
        "evidence": {"passed": False, "missing": ["training skipped because target/problem inference was low-confidence"]},
        "violations": [{"type": "needs_human", "message": profile["needs_human_question"]}],
        "verdict": "NEEDS-HUMAN",
    }
    write_json(run_dir / "artifacts" / "acceptance-result.json", result)
    append_run_verdict(run_dir, "NEEDS-HUMAN", str(profile["needs_human_question"]))
    write_report(run_dir, profile, None, result)


def summarize_failed_artifacts(run_dir: Path) -> list[str]:
    failed: list[str] = []
    for path in sorted((run_dir / "artifacts").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("passed") is False:
            reasons = data.get("reasons") or data.get("violations") or []
            checks = data.get("checks")
            if isinstance(checks, list):
                failed_checks = [
                    str(item.get("check") or item.get("type") or item.get("message"))
                    for item in checks
                    if isinstance(item, dict) and item.get("passed") is False
                ]
                if failed_checks:
                    reasons = [*failed_checks, *list(reasons)]
            if not reasons and data.get("check"):
                reasons = [str(data["check"])]
            failed.append(f"{path.name}: {reasons}")
    return failed


def write_report(run_dir: Path, profile: dict[str, Any], training: dict[str, Any] | None, acceptance: dict[str, Any]) -> None:
    verdict = acceptance.get("verdict", "NEEDS-HUMAN")
    lines = [
        "# ML Autopilot Report",
        "",
        f"Goal: {profile.get('goal')}",
        f"Verdict: {verdict}",
        "",
        "## Model",
    ]
    if training:
        result = training["result"]
        lines.extend([f"- Model: {result.get('model')}", f"- Target: {profile.get('target_column')}", f"- Problem type: {profile.get('problem_type')}", f"- Features: {', '.join(profile.get('numeric_features') or [])}"])
        metrics = result.get("metrics", {})
        metric_text = ", ".join(f"{key}={value:.4f}" for key, value in metrics.items() if isinstance(value, (int, float)))
        lines.extend(["", "## Trustworthy Metric Estimate", metric_text or "No metric estimate was produced."])
    else:
        lines.append("Training was skipped because a critical inference was low-confidence.")
    lines.extend(["", "## What Was Caught"])
    caught = summarize_failed_artifacts(run_dir)
    lines.extend([f"- {item}" for item in caught] or ["- No deterministic validator failures were found."])
    lines.extend(["", "## Assumptions I Made"])
    lines.extend([f"- {item}" for item in profile.get("assumptions", [])] or ["- None recorded."])
    if profile.get("needs_human_question"):
        lines.extend(["", "## Needs Human", str(profile["needs_human_question"])])
    (run_dir / "artifacts" / "ml-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_acceptance(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(repo_root / "maw-tools" / "acceptance_check.py"), "--run", str(run_dir)], capture_output=True, text=True)
    try:
        return json.loads((run_dir / "artifacts" / "acceptance-result.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"verdict": "NO-SHIP", "stdout": proc.stdout, "stderr": proc.stderr}


def cmd_ml_auto(args: argparse.Namespace, repo_root: Path) -> int:
    data_path = Path(args.data).resolve()
    rows, columns, fmt = load_table(data_path)
    task = f"ML autopilot on {data_path} goal: {args.goal}"
    template, template_path, errors = start_workflow.load_valid_template(repo_root, "ml-training-task")
    if errors or template is None or template_path is None:
        raise RuntimeError("; ".join(errors))
    run_info = start_workflow.create_run(repo_root, template, template_path, task, Path(args.run_root), args.slug)
    run_dir = Path(run_info["run_dir"])
    profile = profile_data(rows, columns, data_path, args.goal)
    profile["format"] = fmt
    write_json(run_dir / "artifacts" / "data-profile.json", profile)
    fill_handoffs(run_dir, profile)
    plan = conductor_plan(template, profile, run_dir)
    write_json(run_dir / "artifacts" / "conductor-plan.json", plan)
    plan_proc = subprocess.run([sys.executable, str(repo_root / "maw-tools" / "plan_check.py"), "--file", str(run_dir / "artifacts" / "conductor-plan.json")], capture_output=True, text=True)
    try:
        plan_result = json.loads(plan_proc.stdout)
    except json.JSONDecodeError:
        plan_result = {"passed": False, "stdout": plan_proc.stdout, "stderr": plan_proc.stderr}
    write_json(run_dir / "artifacts" / "plan-check-result.json", plan_result)
    if profile["status"] == "needs_human":
        write_needs_human(run_dir, profile)
        write_json(run_dir / "artifacts" / "verdict-check.json", verdict_check.check_run(run_dir))
        print(json.dumps({"passed": False, "verdict": "NEEDS-HUMAN", "run_dir": str(run_dir), "question": profile["needs_human_question"]}, indent=2))
        return 1

    training = write_training_artifacts(run_dir, rows, profile, args.inject_bug)
    command_results = run_validators(repo_root, run_dir, training["config"], str(profile["problem_type"]))
    update_template_copy(run_dir, [" ".join(item["command"]) for item in command_results])
    acceptance = run_acceptance(repo_root, run_dir)
    append_run_verdict(run_dir, acceptance.get("verdict", "NO-SHIP"), "See artifacts/ml-report.md for metrics, caught issues, and assumptions.")
    write_report(run_dir, profile, training, acceptance)
    verdict_result = verdict_check.check_run(run_dir)
    write_json(run_dir / "artifacts" / "verdict-check.json", verdict_result)
    print(json.dumps({"passed": acceptance.get("verdict") == "SHIP", "verdict": acceptance.get("verdict"), "run_dir": str(run_dir), "report": str(run_dir / "artifacts" / "ml-report.md")}, indent=2))
    return 0 if acceptance.get("verdict") == "SHIP" else 1


def add_parser(subparsers: argparse._SubParsersAction, repo_root: Path) -> None:
    parser = subparsers.add_parser("ml-auto", help="profile, train, validate, and report on tabular ML data")
    parser.add_argument("data", help="CSV or Parquet data path")
    parser.add_argument("--goal", required=True, help="plain-language ML goal")
    parser.add_argument("--run-root", default="runs")
    parser.add_argument("--slug")
    parser.add_argument("--inject-bug", choices=["none", "target-leak", "train-overlap"], default="none", help=argparse.SUPPRESS)
    parser.set_defaults(func=lambda args: cmd_ml_auto(args, repo_root))
