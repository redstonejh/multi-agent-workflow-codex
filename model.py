#!/usr/bin/env python3
"""CivilComments TF-IDF + logistic regression baseline for WILDS exports.

This script is intentionally outside ``maw-tools`` because it uses optional
third-party ML dependencies. It reads exported examples as JSONL and writes
prediction JSONL with ids preserved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def scalar(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return scalar(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        try:
            value = value.tolist()
        except (TypeError, ValueError):
            pass
    if isinstance(value, list) and len(value) == 1:
        return scalar(value[0])
    return value


def text_from_x(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "comment_text", "sentence", "x"):
            item = value.get(key)
            if isinstance(item, str):
                return item
    return str(value)


def read_export(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{index} must be a JSON object")
            if "id" not in item or item["id"] in (None, ""):
                raise ValueError(f"{path}:{index} is missing id")
            if "text" not in item and "x" not in item:
                raise ValueError(f"{path}:{index} is missing text/x")
            rows.append(item)
    return rows


def write_predictions(path: Path, ids: list[str], predictions: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example_id, prediction in zip(ids, predictions):
            handle.write(json.dumps({"id": str(example_id), "prediction": scalar(prediction)}, sort_keys=True) + "\n")


def load_wilds_subset(dataset_name: str, split: str, root_dir: str | None) -> Any:
    import wilds  # type: ignore

    kwargs: dict[str, Any] = {"dataset": dataset_name, "download": False}
    if root_dir:
        kwargs["root_dir"] = root_dir
    dataset = wilds.get_dataset(**kwargs)
    return dataset.get_subset(split, transform=None)


def subset_len(subset: Any) -> int:
    try:
        return len(subset)
    except TypeError:
        labels = getattr(subset, "y_array", None)
        if labels is None:
            raise ValueError("WILDS train subset must provide __len__ or y_array")
        if hasattr(labels, "tolist"):
            labels = labels.tolist()
        return len(labels)


def train_rows(subset: Any, limit: int | None) -> tuple[list[str], list[Any]]:
    count = subset_len(subset)
    if limit is not None:
        if limit <= 0:
            raise ValueError("--max-train must be a positive integer")
        count = min(count, limit)
    texts: list[str] = []
    labels: list[Any] = []
    y_array = getattr(subset, "y_array", None)
    if hasattr(y_array, "tolist"):
        y_array = y_array.tolist()
    for index in range(count):
        item = subset[index]
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            x_value, y_value = item[0], item[1]
        else:
            x_value = item
            if y_array is None:
                raise ValueError("WILDS train subset item must include y or expose y_array")
            y_value = y_array[index]
        texts.append(text_from_x(x_value))
        labels.append(scalar(y_value))
    return texts, labels


def fit_model(texts: list[str], labels: list[Any]) -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.linear_model import LogisticRegression  # type: ignore
    from sklearn.pipeline import Pipeline  # type: ignore

    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=100000, ngram_range=(1, 2), min_df=2)),
            ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", solver="liblinear")),
        ]
    )
    model.fit(texts, labels)
    return model


def run(args: argparse.Namespace) -> dict[str, Any]:
    export_rows = read_export(Path(args.input_jsonl))
    ids = [str(row["id"]) for row in export_rows]
    texts = [str(row.get("text")) if isinstance(row.get("text"), str) else text_from_x(row.get("x")) for row in export_rows]
    train_subset = load_wilds_subset(args.wilds_dataset, args.train_split, args.wilds_root)
    train_texts, train_labels = train_rows(train_subset, args.max_train)
    model = fit_model(train_texts, train_labels)
    predictions = list(model.predict(texts))
    write_predictions(Path(args.output_jsonl), ids, predictions)
    return {
        "check": "civilcomments_baseline_model",
        "passed": True,
        "dataset": args.wilds_dataset,
        "train_split": args.train_split,
        "train_examples": len(train_texts),
        "prediction_examples": len(predictions),
        "output": args.output_jsonl,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train a CivilComments TF-IDF logistic baseline and predict a WILDS export JSONL.")
    parser.add_argument("input_jsonl", help="WILDS export JSONL with id and text/x")
    parser.add_argument("output_jsonl", help="prediction JSONL to write")
    parser.add_argument("--wilds-dataset", default="civilcomments", help="WILDS dataset name")
    parser.add_argument("--wilds-root", help="optional root_dir passed to wilds.get_dataset")
    parser.add_argument("--train-split", default="train", help="WILDS split used for fitting the baseline")
    parser.add_argument("--max-train", type=int, help="optional cap for faster local smoke runs")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (ImportError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"check": "civilcomments_baseline_model", "passed": False, "problems": [{"type": "input_error", "message": str(exc)}]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
