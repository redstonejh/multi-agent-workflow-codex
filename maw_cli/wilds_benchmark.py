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
import shutil
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def load_json_or_csv(path: Path) -> Any:
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                item = json.loads(stripped)
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{index} JSONL row must be an object")
                rows.append(item)
        return rows
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


def jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        try:
            return jsonable(value.tolist())
        except (TypeError, ValueError):
            pass
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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
            if len(values) >= count:
                return [normalize_id(value) for value in values[:count]]
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


def apply_limit(values: list[Any], limit: int | None, label: str) -> list[Any]:
    if limit is None:
        return values
    if limit <= 0:
        raise ValueError("--limit must be a positive integer")
    if limit > len(values):
        raise ValueError(f"--limit {limit} exceeds {label} length {len(values)}")
    return values[:limit]


def limited_eval_array(value: Any, limit: int | None, label: str) -> Any:
    if value is None:
        raise ValueError(f"WILDS subset is missing {label}")
    if limit is None:
        return value
    if limit <= 0:
        raise ValueError("--limit must be a positive integer")
    if len(value) < limit:
        raise ValueError(f"--limit {limit} exceeds {label} length {len(value)}")
    try:
        return value[:limit]
    except TypeError:
        return as_sequence(value, label)[:limit]


def predictions_for_eval(predictions: list[Any], y_true: Any) -> Any:
    try:
        import torch  # type: ignore
    except ImportError:
        return predictions
    if isinstance(y_true, torch.Tensor):
        return torch.as_tensor(predictions, dtype=y_true.dtype, device=y_true.device)
    return predictions


def ensure_torch_scatter_available() -> None:
    try:
        importlib.import_module("torch_scatter")
        return
    except ImportError:
        pass
    try:
        import torch  # type: ignore
    except ImportError:
        return

    module = types.ModuleType("torch_scatter")

    def scatter(src: Any, index: Any, dim_size: int | None = None, reduce: str = "sum", dim: int = 0, out: Any = None) -> Any:
        if dim != 0:
            raise NotImplementedError("fallback torch_scatter.scatter only supports dim=0")
        if reduce not in {"sum", "mean"}:
            raise NotImplementedError("fallback torch_scatter.scatter only supports sum/mean")
        if dim_size is None:
            dim_size = int(index.max().item()) + 1 if index.numel() else 0
        result_shape = (dim_size, *tuple(src.shape[1:]))
        result = torch.zeros(result_shape, dtype=src.dtype, device=src.device) if out is None else out.zero_()
        counts = torch.zeros(dim_size, dtype=src.dtype, device=src.device)
        for value, group in zip(src, index):
            group_index = int(group.item())
            result[group_index] += value
            counts[group_index] += 1
        if reduce == "mean":
            nonzero = counts > 0
            if result.dim() == 1:
                result[nonzero] = result[nonzero] / counts[nonzero]
            else:
                result[nonzero] = result[nonzero] / counts[nonzero].reshape(-1, *([1] * (result.dim() - 1)))
        return result

    module.scatter = scatter  # type: ignore[attr-defined]
    sys.modules["torch_scatter"] = module


def evaluate_with_wilds(prediction_data: Any, predictions_path: Path, dataset_name: str, split: str, root_dir: str | None, limit: int | None = None) -> dict[str, Any]:
    wilds = importlib.import_module("wilds")
    dataset_kwargs: dict[str, Any] = {"dataset": dataset_name, "download": False}
    if root_dir:
        dataset_kwargs["root_dir"] = root_dir
    dataset = wilds.get_dataset(**dataset_kwargs)
    subset = dataset.get_subset(split, transform=None)
    y_true = limited_eval_array(getattr(subset, "y_array", None), limit, "y_array")
    metadata = limited_eval_array(getattr(subset, "metadata_array", None), limit, "metadata_array")
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

    ordered_prediction_values = [predictions[example_id] for example_id in ids if example_id in predictions]
    ordered_predictions = predictions_for_eval(ordered_prediction_values, y_true)
    metrics: dict[str, Any] = {}
    summary = None
    if not problems:
        ensure_torch_scatter_available()
        metrics, summary = normalize_eval_result(dataset.eval(ordered_predictions, y_true, metadata))

    return {
        "check": "wilds_benchmark",
        "schema_version": 1,
        "passed": not problems,
        "dataset": {"name": dataset_name, "version": str(getattr(dataset, "version", "unknown"))},
        "fixed_splits": True,
        "split": split,
        "limit": limit,
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
            "joined_count": len(ordered_prediction_values),
        },
        "problems": problems,
    }


def load_wilds_subset(dataset_name: str, split: str, root_dir: str | None) -> tuple[Any, Any]:
    wilds = importlib.import_module("wilds")
    dataset_kwargs: dict[str, Any] = {"dataset": dataset_name, "download": False}
    if root_dir:
        dataset_kwargs["root_dir"] = root_dir
    dataset = wilds.get_dataset(**dataset_kwargs)
    return dataset, dataset.get_subset(split, transform=None)


def subset_count(subset: Any) -> int:
    try:
        return len(subset)
    except TypeError:
        y_array = getattr(subset, "y_array", None)
        if y_array is None:
            raise ValueError("WILDS subset must provide __len__ or y_array")
        return len(as_sequence(y_array, "y_array"))


def subset_input_at(subset: Any, index: int) -> Any:
    try:
        item = subset[index]
    except TypeError as exc:
        raise ValueError("WILDS subset must support indexed reads for export") from exc
    if isinstance(item, (list, tuple)) and item:
        return item[0]
    return item


def default_predictions_path(export_path: Path) -> Path:
    return export_path.with_name(export_path.stem + "-predictions.jsonl")


def default_score_path(export_path: Path) -> Path:
    return export_path.with_name(export_path.stem + "-score.json")


def render_model_command(command: str, input_path: Path, output_path: Path) -> str:
    input_arg = subprocess.list2cmdline([str(input_path)])
    output_arg = subprocess.list2cmdline([str(output_path)])
    if "{input}" in command or "{output}" in command:
        return command.replace("{input}", input_arg).replace("{output}", output_arg)
    return f"{command} {input_arg} {output_arg}"


def run_model_command(command: str, input_path: Path, output_path: Path) -> dict[str, Any]:
    rendered = render_model_command(command, input_path, output_path)
    completed = subprocess.run(rendered, shell=True, cwd=Path.cwd(), capture_output=True, text=True)
    return {
        "command": rendered,
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def export_with_wilds(
    dataset_name: str,
    split: str,
    root_dir: str | None,
    output_path: Path,
    model_cmd: str | None,
    predictions_output: Path | None,
    score_output: Path | None,
    limit: int | None,
) -> dict[str, Any]:
    dataset, subset = load_wilds_subset(dataset_name, split, root_dir)
    count = subset_count(subset)
    if limit is not None:
        if limit <= 0:
            raise ValueError("--limit must be a positive integer")
        if limit > count:
            raise ValueError(f"--limit {limit} exceeds WILDS subset length {count}")
        count = limit
    ids = subset_ids(subset, count)
    rows: list[dict[str, Any]] = []
    for index, example_id in enumerate(ids):
        x_value = jsonable(subset_input_at(subset, index))
        row = {"id": example_id, "x": x_value}
        if isinstance(x_value, str):
            row["text"] = x_value
        rows.append(row)
    write_jsonl(output_path, rows)

    result: dict[str, Any] = {
        "check": "wilds_export",
        "schema_version": 1,
        "passed": True,
        "dataset": {"name": dataset_name, "version": str(getattr(dataset, "version", "unknown"))},
        "fixed_splits": True,
        "split": split,
        "limit": limit,
        "export": {"path": str(output_path), "example_count": len(rows), "format": "jsonl"},
        "prediction_alignment": "example_id",
        "reproducibility": {
            "deterministic": True,
            "exported_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        },
        "model": None,
        "score": None,
        "problems": [],
    }

    if model_cmd:
        predictions_path = predictions_output or default_predictions_path(output_path)
        score_path = score_output or default_score_path(output_path)
        model_result = run_model_command(model_cmd, output_path, predictions_path)
        result["model"] = {"predictions": str(predictions_path), **model_result}
        if not model_result["passed"]:
            result["passed"] = False
            result["problems"].append({"type": "model_command_failed", "returncode": model_result["returncode"]})
            return result
        if not predictions_path.is_file():
            result["passed"] = False
            result["problems"].append({"type": "missing_predictions_output", "path": str(predictions_path)})
            return result
        score = evaluate_with_wilds(load_json_or_csv(predictions_path), predictions_path, dataset_name, split, root_dir, limit=limit)
        write_json(score_path, score)
        result["score"] = {"path": str(score_path), "passed": bool(score.get("passed")), "metrics_source": score.get("metrics_source")}
        result["passed"] = bool(score.get("passed"))
        if not result["passed"]:
            result["problems"].append({"type": "score_failed", "details": score.get("problems", [])})
    elif score_output:
        result["passed"] = False
        result["problems"].append({"type": "score_requires_model_cmd", "message": "--score-output requires --model-cmd"})

    return result


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


def cmd_wilds_export(args: argparse.Namespace) -> int:
    try:
        result = export_with_wilds(
            args.wilds_dataset,
            args.split,
            args.wilds_root,
            Path(args.output),
            args.model_cmd,
            Path(args.predictions_output) if args.predictions_output else None,
            Path(args.score_output) if args.score_output else None,
            args.limit,
        )
    except (ImportError, OSError, json.JSONDecodeError, ValueError) as exc:
        result = {"check": "wilds_export", "schema_version": 1, "passed": False, "problems": [{"type": "input_error", "message": str(exc)}]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


def render_markdown_list(items: list[str]) -> str:
    if not items:
        return "- None recorded."
    return "\n".join(f"- {item}" for item in items)


def fill_loop_handoffs(run_dir: Path, result: dict[str, Any]) -> None:
    context = "Closed WILDS evaluation loop over fixed score and prediction artifacts."
    iterations = result.get("iterations", [])
    latest = iterations[-1] if iterations else {}
    instructions = latest.get("worker_instructions", []) if isinstance(latest, dict) else []
    for handoff in sorted((run_dir / "handoffs").glob("*.md")):
        name = handoff.name
        if "conductor__to__planner" in name:
            did = "Started an ml-validation workflow run and scoped it to WILDS benchmark validator signals."
            artifacts = "- artifacts/workflow-template.json  (ml-validation workflow template)\n- artifacts/artifact-checklist.md  (template artifacts)"
            risks = "The loop validates an existing benchmark artifact; it does not train a new model unless a retry command is provided."
            next_step = "Planner should map score, prediction, validator, critic, and acceptance artifacts."
        elif "planner__to__worker" in name:
            did = "Mapped the loop: copy score artifacts, run wilds_validator, record tripped signals, and hand remediation back to worker."
            artifacts = "- artifacts/score.json  (benchmark score input)\n- artifacts/predictions.jsonl  (optional probability/label rows)"
            risks = "Calibration requires probabilities and labels; missing fields should be diagnosed explicitly."
            next_step = "Worker should run the validator and capture bounded retry instructions."
        elif "worker__to__critic" in name:
            did = "Ran the WILDS validator loop and wrote iteration artifacts."
            artifacts = "- artifacts/wilds-validator.json  (latest validator signals)\n- artifacts/wilds-loop-result.json  (full loop record)"
            risks = "Any failed signal must produce a concrete try-next instruction."
            next_step = "Critic should review tripped signals and send remediation instructions if needed."
        elif "critic__to__worker" in name:
            did = "Reviewed validator output and prepared remediation instructions."
            artifacts = "- artifacts/critic-diagnosis.md  (diagnosis and worker retry instructions)"
            risks = "Retries are bounded by max_iters; unchanged artifacts will keep tripping the same checks."
            next_step = "Worker should try the listed remediation and re-score, or stop at the max iteration verdict."
        else:
            did = "Checked loop artifacts, handoffs, and final verdict."
            artifacts = "- artifacts/acceptance-result.json  (closed-loop acceptance verdict)"
            risks = "A NO-SHIP verdict means one or more validator signals still need remediation."
            next_step = "Use the acceptance verdict as the canonical run result."
        handoff.write_text(
            "\n".join(
                [
                    handoff.read_text(encoding="utf-8").split("## Task context", 1)[0].rstrip(),
                    "",
                    "## Task context",
                    context,
                    "",
                    "## What I did",
                    did,
                    "",
                    "## Output / artifacts",
                    artifacts,
                    "",
                    "## Open questions / risks",
                    risks,
                    "",
                    "## Recommended next step",
                    next_step + ("\n\nCurrent worker instructions:\n" + render_markdown_list(instructions) if instructions else ""),
                    "",
                ]
            ),
            encoding="utf-8",
        )


def write_critic_diagnosis(path: Path, validator_result: dict[str, Any], iteration: int) -> None:
    lines = [
        "# WILDS Critic Diagnosis",
        "",
        f"Iteration: {iteration}",
        f"Validator passed: {validator_result.get('passed')}",
        "",
        "## Tripped signals",
        render_markdown_list([str(item) for item in validator_result.get("tripped", [])]),
        "",
        "## Worker instructions",
        render_markdown_list([str(item) for item in validator_result.get("worker_instructions", [])]),
        "",
        "## Recommendations",
        render_markdown_list([str(item) for item in validator_result.get("recommendations", [])]),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def update_loop_run_markdown(run_dir: Path, verdict: str, loop_result: dict[str, Any]) -> None:
    run_md = run_dir / "run.md"
    text = run_md.read_text(encoding="utf-8")
    if "- Task type:" not in text:
        text = text.replace("- Status: in-progress", "- Status: in-progress\n- Task type: ml-validation-task")
    summary = [
        "## Final result summary",
        f"Final verdict: {verdict}",
        "",
        f"Iterations: {len(loop_result.get('iterations', []))}",
        f"Latest validator passed: {loop_result.get('passed')}",
        "",
    ]
    if "## Final result summary" in text:
        text = text.split("## Final result summary", 1)[0].rstrip() + "\n\n" + "\n".join(summary)
    else:
        text = text.rstrip() + "\n\n" + "\n".join(summary)
    run_md.write_text(text, encoding="utf-8")


def cmd_wilds_loop(args: argparse.Namespace, repo_root: Path) -> int:
    try:
        import start_workflow  # type: ignore
        import wilds_validator  # type: ignore

        template, template_path, errors = start_workflow.load_valid_template(repo_root, "ml-validation-task")
        if errors or template is None or template_path is None:
            raise ValueError("; ".join(errors))
        run_info = start_workflow.create_run(
            repo_root,
            template,
            template_path,
            "Closed WILDS benchmark evaluation loop",
            Path(args.run_root),
            args.slug,
        )
        run_dir = Path(run_info["run_dir"])
        artifacts = run_dir / "artifacts"
        score_path = Path(args.score)
        copied_score = artifacts / "score.json"
        shutil.copyfile(score_path, copied_score)
        copied_predictions: Path | None = None
        if args.predictions:
            copied_predictions = artifacts / ("predictions.jsonl" if Path(args.predictions).suffix.lower() == ".jsonl" else "predictions.json")
            shutil.copyfile(Path(args.predictions), copied_predictions)

        thresholds = {
            "max_worst_group_gap": args.max_worst_group_gap,
            "max_expected_calibration_error": args.max_expected_calibration_error,
            "max_brier_score": args.max_brier_score,
            "min_majority_margin": args.min_majority_margin,
        }
        iterations: list[dict[str, Any]] = []
        latest_validator: dict[str, Any] = {}
        for iteration in range(1, args.max_iters + 1):
            predictions = wilds_validator.load_jsonl_or_rows(copied_predictions) if copied_predictions else None
            latest_validator = wilds_validator.validate(load_json(copied_score), predictions, thresholds, args.majority_accuracy, args.calibration_bins)
            iteration_path = artifacts / f"wilds-validator-iteration-{iteration}.json"
            write_json(iteration_path, latest_validator)
            write_json(artifacts / "wilds-validator.json", latest_validator)
            write_critic_diagnosis(artifacts / "critic-diagnosis.md", latest_validator, iteration)
            item = {
                "iteration": iteration,
                "validator_artifact": str(iteration_path),
                "passed": bool(latest_validator.get("passed")),
                "tripped": latest_validator.get("tripped", []),
                "worker_instructions": latest_validator.get("worker_instructions", []),
            }
            iterations.append(item)
            if latest_validator.get("passed") is True:
                break
            if not args.retry_cmd:
                break
            rendered_retry = render_model_command(args.retry_cmd, copied_score, copied_score)
            completed = subprocess.run(rendered_retry, shell=True, cwd=Path.cwd(), capture_output=True, text=True)
            item["retry"] = {
                "command": rendered_retry,
                "returncode": completed.returncode,
                "passed": completed.returncode == 0,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            if completed.returncode != 0:
                break

        verdict = "SHIP" if latest_validator.get("passed") is True else "NO-SHIP"
        loop_result = {
            "check": "wilds_closed_loop",
            "schema_version": 1,
            "passed": verdict == "SHIP",
            "run_dir": str(run_dir),
            "score": str(copied_score),
            "predictions": str(copied_predictions) if copied_predictions else None,
            "max_iters": args.max_iters,
            "iterations": iterations,
            "verdict": verdict,
        }
        write_json(artifacts / "wilds-loop-result.json", loop_result)
        acceptance_result = {
            "run": str(run_dir),
            "task_type": "ml-validation-task",
            "validator": latest_validator,
            "loop": loop_result,
            "verdict": verdict,
            "passed": verdict == "SHIP",
        }
        write_json(artifacts / "acceptance-result.json", acceptance_result)
        fill_loop_handoffs(run_dir, loop_result)
        update_loop_run_markdown(run_dir, verdict, loop_result)
        result = {"check": "wilds_loop", "schema_version": 1, "passed": True, "run_dir": str(run_dir), "verdict": verdict, "loop": loop_result}
    except (ImportError, OSError, json.JSONDecodeError, ValueError) as exc:
        result = {"check": "wilds_loop", "schema_version": 1, "passed": False, "problems": [{"type": "input_error", "message": str(exc)}]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") is True else 1


def add_parser(subparsers: argparse._SubParsersAction, repo_root: Path | None = None) -> None:
    parser = subparsers.add_parser("wilds-benchmark", help="evaluate fixed-split WILDS-style prediction exports")
    parser.add_argument("manifest", nargs="?", help="JSON/CSV manifest with id, split, and label columns; with --wilds-dataset this may be the predictions file")
    parser.add_argument("predictions", nargs="?", help="JSON/CSV predictions with id and prediction columns")
    parser.add_argument("--wilds-dataset", help="optional WILDS dataset name; delegates metrics to dataset.eval")
    parser.add_argument("--wilds-root", help="optional root_dir passed to wilds.get_dataset")
    parser.add_argument("--split", default="test", help="WILDS split name for --wilds-dataset")
    parser.add_argument("--output", help="write benchmark result JSON")
    parser.set_defaults(func=cmd_wilds_benchmark)

    export = subparsers.add_parser("wilds-export", help="export WILDS split examples and optionally run model -> score")
    export.add_argument("--wilds-dataset", required=True, help="WILDS dataset name; loaded lazily with download=False")
    export.add_argument("--wilds-root", help="optional root_dir passed to wilds.get_dataset")
    export.add_argument("--split", default="test", help="WILDS split name to export")
    export.add_argument("--output", required=True, help="write exported examples JSONL with id and x/text fields")
    export.add_argument("--limit", type=int, help="optional maximum number of examples from the start of the fixed split")
    export.add_argument("--model-cmd", help="optional command that reads {input} JSONL and writes {output} predictions JSON/JSONL")
    export.add_argument("--predictions-output", help="prediction JSON path passed to --model-cmd as {output}; defaults beside export")
    export.add_argument("--score-output", help="benchmark score JSON path; defaults beside export when --model-cmd is set")
    export.set_defaults(func=cmd_wilds_export)

    loop = subparsers.add_parser("wilds-loop", help="wrap a WILDS score artifact in a MAW closed validation loop")
    loop.add_argument("--score", required=True, help="score JSON from wilds-benchmark or wilds-export")
    loop.add_argument("--predictions", help="optional prediction JSON/JSONL with probabilities and labels")
    loop.add_argument("--run-root", default="runs", help="directory where the MAW run folder is created")
    loop.add_argument("--slug", help="optional run folder slug")
    loop.add_argument("--max-iters", type=int, default=3, help="maximum critic/worker loop iterations")
    loop.add_argument("--retry-cmd", help="optional command to refresh score.json after a failed validator iteration")
    loop.add_argument("--majority-accuracy", type=float, default=0.5)
    loop.add_argument("--max-worst-group-gap", type=float, default=0.20)
    loop.add_argument("--max-expected-calibration-error", type=float, default=0.10)
    loop.add_argument("--max-brier-score", type=float, default=0.25)
    loop.add_argument("--min-majority-margin", type=float, default=0.02)
    loop.add_argument("--calibration-bins", type=int, default=10)
    loop.set_defaults(func=lambda args: cmd_wilds_loop(args, repo_root or Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate fixed-split WILDS-style prediction exports.")
    sub = parser.add_subparsers(dest="command", required=True)
    add_parser(sub)
    parsed = parser.parse_args()
    raise SystemExit(parsed.func(parsed))
