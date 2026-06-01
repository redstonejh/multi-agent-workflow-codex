"""Deterministic toy data validation problem."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SEED = 303


def generate_data(seed: int = SEED, n: int = 50) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for idx in range(n):
        value = 20 + rng.random() * 60
        rows.append({"id": idx, "feature_value": value, "target": 1 if value >= 50 else 0})
    return rows


def split(rows: list[dict[str, Any]], train_ratio: float = 0.8) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cut = int(len(rows) * train_ratio)
    return rows[:cut], rows[cut:]


def validate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [row["id"] for row in rows]
    missing = [row["id"] for row in rows if row["feature_value"] is None or row["target"] is None]
    out_of_range = [row["id"] for row in rows if not 0 <= row["feature_value"] <= 100]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    return {
        "missing_count": len(missing),
        "out_of_range_count": len(out_of_range),
        "duplicate_id_count": len(duplicates),
    }


def run(seed: int = SEED) -> dict[str, Any]:
    rows = generate_data(seed)
    train, test = split(rows)
    metrics = validate_rows(rows)
    metrics["valid_rows"] = len(rows)
    result = {
        "problem": "data_validation",
        "seed": seed,
        "expected_seed": SEED,
        "features": ["feature_value"],
        "target": "target",
        "baseline_model": "data quality rules",
        "split": {
            "train_ids": [row["id"] for row in train],
            "test_ids": [row["id"] for row in test],
            "expected_train_ratio": 0.8,
        },
        "metrics": metrics,
        "metric_checks": [
            {"name": "missing_count", "direction": "at_most", "threshold": 0},
            {"name": "out_of_range_count", "direction": "at_most", "threshold": 0},
            {"name": "duplicate_id_count", "direction": "at_most", "threshold": 0},
            {"name": "valid_rows", "direction": "at_least", "threshold": 50},
        ],
        "acceptance_criteria": [
            "missing_count == 0",
            "out_of_range_count == 0",
            "duplicate_id_count == 0",
            "no train/test id overlap",
            "seed == 303",
        ],
    }
    result["acceptance"] = {
        "passed": metrics["missing_count"] == 0 and metrics["out_of_range_count"] == 0 and metrics["duplicate_id_count"] == 0
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = run()
    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
