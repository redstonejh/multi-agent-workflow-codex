#!/usr/bin/env python3
"""Manual WILDS smoke check for the real civilcomments evaluator.

This file is intentionally not named ``test_*.py`` so ``unittest discover``
does not collect it. It only runs when ``MAW_WILDS_SMOKE=1`` is set.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def main() -> int:
    if os.environ.get("MAW_WILDS_SMOKE") != "1":
        print("SKIP: set MAW_WILDS_SMOKE=1 to run the manual WILDS smoke check.")
        return 0

    try:
        import wilds  # type: ignore
        from maw_cli.wilds_benchmark import as_sequence, subset_ids
    except ImportError as exc:
        print(f"FAIL: WILDS smoke requires importable wilds and maw_cli: {exc}", file=sys.stderr)
        return 1

    dataset_name = os.environ.get("MAW_WILDS_DATASET", "civilcomments")
    split = os.environ.get("MAW_WILDS_SPLIT", "val")
    root_dir = os.environ.get("MAW_WILDS_ROOT")
    dataset_kwargs: dict[str, Any] = {"dataset": dataset_name, "download": False}
    if root_dir:
        dataset_kwargs["root_dir"] = root_dir

    dataset = wilds.get_dataset(**dataset_kwargs)
    subset = dataset.get_subset(split, transform=None)
    y_true = as_sequence(getattr(subset, "y_array", None), "y_array")
    ids = subset_ids(subset, len(y_true))
    if not ids:
        print(f"FAIL: {dataset_name}/{split} subset is empty", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        predictions = root / "civilcomments-predictions.json"
        output = root / "wilds-smoke-result.json"
        predictions.write_text(
            json.dumps(
                {
                    "predictions": [
                        {"id": example_id, "prediction": jsonable(label)}
                        for example_id, label in zip(ids, y_true)
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )
        command = [
            sys.executable,
            str(ROOT / "maw.py"),
            "wilds-benchmark",
            str(predictions),
            "--wilds-dataset",
            dataset_name,
            "--split",
            split,
            "--output",
            str(output),
        ]
        if root_dir:
            command.extend(["--wilds-root", root_dir])
        proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout)
            print(proc.stderr, file=sys.stderr)
            return proc.returncode
        result = json.loads(output.read_text(encoding="utf-8"))

    metrics = result.get("metrics")
    if result.get("metrics_source") != "wilds.dataset.eval":
        print("FAIL: harness did not report WILDS dataset.eval as the metrics source", file=sys.stderr)
        return 1
    if not isinstance(metrics, dict) or not metrics:
        print("FAIL: WILDS dataset.eval metrics were not a non-empty JSON object", file=sys.stderr)
        return 1
    print(json.dumps({"passed": True, "dataset": dataset_name, "split": split, "metric_count": len(metrics)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
