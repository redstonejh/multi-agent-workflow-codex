"""WILDS-style benchmark harness for fixed-split prediction files.

The default manifest path intentionally does not import WILDS or Torch. When
``--wilds-dataset`` is provided, the adapter imports WILDS lazily and delegates
metrics to the dataset's official ``eval`` method.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json_or_csv(path: Path) -> Any:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    return json.loads(path.read_text(encoding="utf-8"))


def as_rows(data: Any, key: str, source: str) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        value = data.get(key)
    else:
        value = data
    if not isinstance(value, list):
        raise ValueError(f"{source} must contain a list at `{key}` or be a list")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"{source}[{index}] must be an object")
        rows.append(item)
    return rows


def normalize_id(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("example id must be non-empty")
    return text


def field(row: dict[str, Any], names: tuple[str, ...], label: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    raise ValueError(f"missing {label}; accepted fields: {', '.join(names)}")


def predictions_by_id(prediction_data: Any) -> tuple[dict[str, Any], list[str]]:
    prediction_rows = as_rows(prediction_data, "predictions", "predictions")
    result: dict[str, Any] = {}
    duplicates: list[str] = []
    for row in prediction_rows:
        example_id = normalize_id(field(row, ("id", "example_id", "input_id"), "prediction id"))
        if example_id in result:
            duplicates.append(example_id)
        result[example_id] = field(row, ("prediction", "pred", "y_pred"), "prediction")
    return result, duplicates


def macro_f1(labels: list[str], predictions: list[str]) -> float:
    classes = sorted(set(labels) | set(predictions))
    if not classes:
        return 0.0
    scores: list[float] = []
    for cls in classes:
        tp = sum(1 for actual, pred in zip(labels, predictions) if actual == cls and pred == cls)
        fp = sum(1 for actual, pred in zip(labels, predictions) if actual != cls and pred == cls)
        fn = sum(1 for actual, pred in zip(labels, predictions) if actual == cls and pred != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores)


def split_metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    labels = [row["label"] for row in rows]
    predictions = [row["prediction"] for row in rows]
    correct = sum(1 for actual, pred in zip(labels, predictions) if actual == pred)
    counts = Counter(labels)
    return {
        "example_count": len(rows),
        "accuracy": correct / len(rows) if rows else 0.0,
        "macro_f1": macro_f1(labels, predictions),
        "label_counts": dict(sorted(counts.items())),
    }


def evaluate(manifest_data: Any, prediction_data: Any, manifest_path: Path, predictions_path: Path) -> dict[str, Any]:
    manifest_rows = as_rows(manifest_data, "examples", "manifest")
    prediction_rows = as_rows(prediction_data, "predictions", "predictions")

    labels_by_id: dict[str, dict[str, str]] = {}
    duplicate_labels: list[str] = []
    for row in manifest_rows:
        example_id = normalize_id(field(row, ("id", "example_id", "input_id"), "example id"))
        if example_id in labels_by_id:
            duplicate_labels.append(example_id)
        labels_by_id[example_id] = {
            "id": example_id,
            "label": str(field(row, ("label", "target", "y"), "label")),
            "split": str(field(row, ("split", "split_name"), "split")),
            "group": str(row.get("group", row.get("group_id", ""))),
        }

    predictions_by_example_id, duplicate_predictions = predictions_by_id(prediction_data)

    label_ids = set(labels_by_id)
    prediction_ids = set(predictions_by_example_id)
    missing_predictions = sorted(label_ids - prediction_ids)
    unexpected_predictions = sorted(prediction_ids - label_ids)

    joined: list[dict[str, str]] = []
    for example_id in sorted(label_ids & prediction_ids):
        row = dict(labels_by_id[example_id])
        row["prediction"] = str(predictions_by_example_id[example_id])
        joined.append(row)

    splits: dict[str, list[dict[str, str]]] = {}
    for row in joined:
        splits.setdefault(row["split"], []).append(row)
    split_results = {name: split_metrics(rows) for name, rows in sorted(splits.items())}

    problems = []
    if duplicate_labels:
        problems.append({"type": "duplicate_labels", "ids": sorted(set(duplicate_labels))})
    if duplicate_predictions:
        problems.append({"type": "duplicate_predictions", "ids": sorted(set(duplicate_predictions))})
    if missing_predictions:
        problems.append({"type": "missing_predictions", "ids": missing_predictions})
    if unexpected_predictions:
        problems.append({"type": "unexpected_predictions", "ids": unexpected_predictions})

    metadata = manifest_data if isinstance(manifest_data, dict) else {}
    dataset = metadata.get("dataset", {})
    if not isinstance(dataset, dict):
        dataset = {"name": str(dataset)}
    fixed_splits = metadata.get("fixed_splits", True) if isinstance(metadata, dict) else True

    return {
        "check": "wilds_benchmark",
        "schema_version": 1,
        "passed": not problems,
        "dataset": {
            "name": str(dataset.get("name", "unknown")),
            "version": str(dataset.get("version", "unknown")),
        },
        "fixed_splits": bool(fixed_splits),
        "manifest": str(manifest_path),
        "predictions": str(predictions_path),
        "prediction_alignment": "example_id",
        "reproducibility": {
            "deterministic": True,
            "evaluated_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        },
        "examples": {
            "manifest_count": len(labels_by_id),
            "prediction_count": len(predictions_by_example_id),
            "joined_count": len(joined),
        },
        "splits": split_results,
        "problems": problems,
    }


def as_sequence(value: Any, label: str) -> list[Any]:
    if value is None:
        raise ValueError(f"WILDS subset is missing {label}")
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value)


def subset_ids(subset: Any, count: int) -> list[str]:
    for attr in ("ids", "id_array", "indices", "_indices"):
        if hasattr(subset, attr):
            values = as_sequence(getattr(subset, attr), attr)
            if len(values) == count:
                return [normalize_id(value) for value in values]
    return [str(index) for index in range(count)]


def normalize_eval_result(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, tuple) and raw:
        metrics = raw[0]
        summary = raw[1] if len(raw) > 1 else None
    else:
        metrics = raw
        summary = None
    if not isinstance(metrics, dict):
        raise ValueError("dataset.eval must return a metrics dict or a tuple whose first item is a metrics dict")
    return metrics, str(summary) if summary is not None else None


def evaluate_with_wilds(prediction_data: Any, predictions_path: Path, dataset_name: str, split: str, root_dir: str | None) -> dict[str, Any]:
    wilds = importlib.import_module("wilds")
    dataset_kwargs: dict[str, Any] = {"dataset": dataset_name, "download": False}
    if root_dir:
        dataset_kwargs["root_dir"] = root_dir
    dataset = wilds.get_dataset(**dataset_kwargs)
    subset = dataset.get_subset(split, transform=None)
    y_true = as_sequence(getattr(subset, "y_array", None), "y_array")
    metadata = as_sequence(getattr(subset, "metadata_array", None), "metadata_array")
    if len(y_true) != len(metadata):
        raise ValueError("WILDS subset y_array and metadata_array lengths differ")
    ids = subset_ids(subset, len(y_true))
    predictions, duplicate_predictions = predictions_by_id(prediction_data)

    missing_predictions = sorted(set(ids) - set(predictions))
    unexpected_predictions = sorted(set(predictions) - set(ids))
    problems = []
    if duplicate_predictions:
        problems.append({"type": "duplicate_predictions", "ids": sorted(set(duplicate_predictions))})
    if missing_predictions:
        problems.append({"type": "missing_predictions", "ids": missing_predictions})
    if unexpected_predictions:
        problems.append({"type": "unexpected_predictions", "ids": unexpected_predictions})

    ordered_predictions = [predictions[example_id] for example_id in ids if example_id in predictions]
    metrics: dict[str, Any] = {}
    summary = None
    if not problems:
        metrics, summary = normalize_eval_result(dataset.eval(ordered_predictions, y_true, metadata))

    return {
        "check": "wilds_benchmark",
        "schema_version": 1,
        "passed": not problems,
        "dataset": {"name": dataset_name, "version": str(getattr(dataset, "version", "unknown"))},
        "fixed_splits": True,
        "split": split,
        "predictions": str(predictions_path),
        "prediction_alignment": "example_id",
        "metrics_source": "wilds.dataset.eval",
        "metrics": metrics,
        "metrics_summary": summary,
        "reproducibility": {
            "deterministic": True,
            "evaluated_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        },
        "examples": {
            "subset_count": len(ids),
            "prediction_count": len(predictions),
            "joined_count": len(ordered_predictions),
        },
        "problems": problems,
    }


def cmd_wilds_benchmark(args: argparse.Namespace) -> int:
    try:
        if args.wilds_dataset:
            predictions_path = Path(args.predictions or args.manifest)
            result = evaluate_with_wilds(load_json_or_csv(predictions_path), predictions_path, args.wilds_dataset, args.split, args.wilds_root)
        else:
            if not args.manifest or not args.predictions:
                raise ValueError("manifest and predictions are required unless --wilds-dataset is provided")
            result = evaluate(load_json_or_csv(Path(args.manifest)), load_json_or_csv(Path(args.predictions)), Path(args.manifest), Path(args.predictions))
    except (ImportError, OSError, json.JSONDecodeError, ValueError) as exc:
        result = {"check": "wilds_benchmark", "schema_version": 1, "passed": False, "problems": [{"type": "input_error", "message": str(exc)}]}
    if args.output:
        write_json(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


def add_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("wilds-benchmark", help="evaluate fixed-split WILDS-style prediction exports")
    parser.add_argument("manifest", nargs="?", help="JSON/CSV manifest with id, split, and label columns; with --wilds-dataset this may be the predictions file")
    parser.add_argument("predictions", nargs="?", help="JSON/CSV predictions with id and prediction columns")
    parser.add_argument("--wilds-dataset", help="optional WILDS dataset name; delegates metrics to dataset.eval")
    parser.add_argument("--wilds-root", help="optional root_dir passed to wilds.get_dataset")
    parser.add_argument("--split", default="test", help="WILDS split name for --wilds-dataset")
    parser.add_argument("--output", help="write benchmark result JSON")
    parser.set_defaults(func=cmd_wilds_benchmark)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate fixed-split WILDS-style prediction exports.")
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser(sub)
    parsed = parser.parse_args()
    raise SystemExit(parsed.func(parsed))
