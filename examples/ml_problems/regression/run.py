"""Deterministic toy regression problem."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SEED = 202


def generate_data(seed: int = SEED, n: int = 90) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for idx in range(n):
        x = idx / 10.0
        noise = rng.uniform(-0.35, 0.35)
        target = 2.0 * x + 3.0 + noise
        rows.append({"id": idx, "x": x, "noise": noise, "target": target})
    return rows


def split(rows: list[dict[str, Any]], train_ratio: float = 0.7) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cut = int(len(rows) * train_ratio)
    return rows[:cut], rows[cut:]


def fit_linear(rows: list[dict[str, Any]]) -> tuple[float, float]:
    xs = [row["x"] for row in rows]
    ys = [row["target"] for row in rows]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean
    return slope, intercept


def evaluate(rows: list[dict[str, Any]], slope: float, intercept: float) -> dict[str, float]:
    errors = []
    targets = [row["target"] for row in rows]
    mean_target = sum(targets) / len(targets)
    ss_res = 0.0
    ss_tot = 0.0
    for row in rows:
        pred = slope * row["x"] + intercept
        err = abs(pred - row["target"])
        errors.append(err)
        ss_res += (row["target"] - pred) ** 2
        ss_tot += (row["target"] - mean_target) ** 2
    return {"mae": sum(errors) / len(errors), "r2": 1 - (ss_res / ss_tot)}


def run(seed: int = SEED) -> dict[str, Any]:
    rows = generate_data(seed)
    train, test = split(rows)
    slope, intercept = fit_linear(train)
    test_metrics = evaluate(test, slope, intercept)
    result = {
        "problem": "regression",
        "seed": seed,
        "expected_seed": SEED,
        "features": ["x", "noise"],
        "target": "target",
        "baseline_model": "closed-form simple linear regression",
        "split": {
            "train_ids": [row["id"] for row in train],
            "test_ids": [row["id"] for row in test],
            "expected_train_ratio": 0.7,
        },
        "metrics": {
            "test_mae": round(test_metrics["mae"], 6),
            "test_r2": round(test_metrics["r2"], 6),
        },
        "metric_checks": [
            {"name": "test_mae", "direction": "at_most", "threshold": 0.4},
            {"name": "test_r2", "direction": "at_least", "threshold": 0.95},
        ],
        "acceptance_criteria": [
            "test_mae <= 0.4",
            "test_r2 >= 0.95",
            "no train/test id overlap",
            "seed == 202",
        ],
    }
    result["acceptance"] = {
        "passed": result["metrics"]["test_mae"] <= 0.4 and result["metrics"]["test_r2"] >= 0.95
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
