"""Deterministic toy classification problem."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


SEED = 101


def generate_data(seed: int = SEED, n: int = 80) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for idx in range(n):
        signal = rng.uniform(-1.0, 1.0)
        noise = rng.uniform(-0.12, 0.12)
        label = 1 if signal + noise >= 0 else 0
        rows.append({"id": idx, "signal": signal, "noise": noise, "target": label})
    return rows


def split(rows: list[dict[str, Any]], train_ratio: float = 0.75) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cut = int(len(rows) * train_ratio)
    return rows[:cut], rows[cut:]


def predict(row: dict[str, Any]) -> int:
    return 1 if row["signal"] >= 0 else 0


def accuracy(rows: list[dict[str, Any]]) -> float:
    return sum(1 for row in rows if predict(row) == row["target"]) / len(rows)


def run(seed: int = SEED) -> dict[str, Any]:
    rows = generate_data(seed)
    train, test = split(rows)
    result = {
        "problem": "classification",
        "seed": seed,
        "expected_seed": SEED,
        "features": ["signal", "noise"],
        "target": "target",
        "baseline_model": "threshold(signal >= 0)",
        "split": {
            "train_ids": [row["id"] for row in train],
            "test_ids": [row["id"] for row in test],
            "expected_train_ratio": 0.75,
        },
        "metrics": {
            "train_accuracy": round(accuracy(train), 6),
            "test_accuracy": round(accuracy(test), 6),
        },
        "metric_checks": [
            {"name": "test_accuracy", "direction": "at_least", "threshold": 0.85}
        ],
        "acceptance_criteria": [
            "test_accuracy >= 0.85",
            "no train/test id overlap",
            "seed == 101",
            "features do not include target leakage",
        ],
    }
    result["acceptance"] = {"passed": result["metrics"]["test_accuracy"] >= 0.85}
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
