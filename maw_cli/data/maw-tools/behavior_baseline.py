#!/usr/bin/env python3
"""Capture and verify deterministic behavior snapshots for refactor tasks."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib
import inspect
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True


def emit(result: dict[str, Any], output: str | None = None) -> int:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed") else 1


def load_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data


def as_entries(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("manifest sections must be arrays")
    return value


def entry_name(entry: Any, fallback: str) -> str:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        value = entry.get("name") or entry.get("target") or entry.get("expr") or entry.get("file") or fallback
        return str(value)
    return fallback


def stable_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def bytes_payload(data: bytes) -> dict[str, Any]:
    return {
        "bytes_base64": base64.b64encode(data).decode("ascii"),
        "length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def text_payload(text: str) -> dict[str, Any]:
    data = text.encode("utf-8")
    payload = bytes_payload(data)
    payload["text"] = text
    return payload


def root_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def import_manifest_modules(manifest: dict[str, Any]) -> dict[str, Any]:
    importlib.invalidate_caches()
    namespace: dict[str, Any] = {"__builtins__": __builtins__}
    for raw in as_entries(manifest.get("modules")):
        if isinstance(raw, str):
            module_name = raw
            alias = raw.rsplit(".", 1)[-1]
        elif isinstance(raw, dict):
            module_name = str(raw.get("name") or raw.get("module") or "")
            alias = str(raw.get("as") or module_name.rsplit(".", 1)[-1])
        else:
            raise ValueError("modules entries must be strings or objects")
        if not module_name:
            raise ValueError("module entry is missing name")
        module = importlib.import_module(module_name)
        namespace[alias] = module
        namespace[module_name] = module
    return namespace


def eval_expr(expr: str, namespace: dict[str, Any]) -> Any:
    return eval(expr, namespace, {})


def resolve_target(target: str) -> Any:
    parts = target.split(".")
    for index in range(len(parts), 0, -1):
        module_name = ".".join(parts[:index])
        try:
            obj = importlib.import_module(module_name)
        except ImportError:
            continue
        for part in parts[index:]:
            obj = getattr(obj, part)
        return obj
    raise ValueError(f"could not resolve target: {target}")


def normalized_module_entry(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"module": raw, "attrs": []}
    if isinstance(raw, dict):
        module = str(raw.get("name") or raw.get("module") or "")
        attrs = raw.get("attrs", [])
        if attrs is None:
            attrs = []
        if not isinstance(attrs, list):
            raise ValueError("module attrs must be an array")
        return {"module": module, "attrs": [str(item) for item in attrs]}
    raise ValueError("module entries must be strings or objects")


def capture_module_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in as_entries(manifest.get("modules")):
        entry = normalized_module_entry(raw)
        module_name = entry["module"]
        if not module_name:
            raise ValueError("module entry is missing name")
        module = importlib.import_module(module_name)
        attrs: dict[str, Any] = {}
        for attr in entry["attrs"]:
            attrs[attr] = getattr(module, attr)
        public_names = sorted(name for name in dir(module) if not name.startswith("_"))
        items.append(
            {
                "type": "module",
                "name": module_name,
                "module": module_name,
                "public_names": public_names,
                "attrs_json": stable_json_bytes(attrs).decode("utf-8"),
            }
        )
    return items


def signature_entries(manifest: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for index, raw in enumerate(as_entries(manifest.get("signatures"))):
        if isinstance(raw, str):
            result.append({"name": raw, "target": raw})
        elif isinstance(raw, dict):
            if raw.get("module") and raw.get("members") == "public":
                module_name = str(raw["module"])
                module = importlib.import_module(module_name)
                for member_name in sorted(name for name in dir(module) if not name.startswith("_")):
                    obj = getattr(module, member_name)
                    if callable(obj):
                        target = f"{module_name}.{member_name}"
                        result.append({"name": target, "target": target})
                continue
            target = str(raw.get("target") or "")
            if not target:
                raise ValueError(f"signatures[{index}] is missing target")
            result.append({"name": str(raw.get("name") or target), "target": target})
        else:
            raise ValueError("signature entries must be strings or objects")
    return result


def capture_signature_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in signature_entries(manifest):
        obj = resolve_target(entry["target"])
        items.append(
            {
                "type": "signature",
                "name": entry["name"],
                "target": entry["target"],
                "signature": str(inspect.signature(obj)),
            }
        )
    return items


def capture_repr_items(manifest: dict[str, Any], namespace: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("reprs"))):
        if isinstance(raw, str):
            name = raw
            expr = raw
        elif isinstance(raw, dict):
            expr = str(raw.get("expr") or "")
            name = entry_name(raw, f"reprs[{index}]")
        else:
            raise ValueError("repr entries must be strings or objects")
        if not expr:
            raise ValueError(f"reprs[{index}] is missing expr")
        value = eval_expr(expr, namespace)
        items.append({"type": "repr", "name": name, "expr": expr, "repr": repr(value), "str": str(value)})
    return items


def capture_json_items(manifest: dict[str, Any], namespace: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("json"))):
        if isinstance(raw, dict):
            expr = str(raw.get("expr") or "")
            name = entry_name(raw, f"json[{index}]")
        else:
            expr = str(raw)
            name = expr
        if not expr:
            raise ValueError(f"json[{index}] is missing expr")
        payload = bytes_payload(stable_json_bytes(eval_expr(expr, namespace)))
        items.append({"type": "json", "name": name, "expr": expr, **payload})
    return items


def csv_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
        headers = sorted({str(key) for row in value for key in row})
        writer.writerow(headers)
        for row in value:
            writer.writerow([row.get(header, "") for header in headers])
    else:
        writer.writerows(value)
    return buffer.getvalue().encode("utf-8")


def capture_csv_items(manifest: dict[str, Any], namespace: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("csv"))):
        if isinstance(raw, dict):
            expr = str(raw.get("expr") or "")
            name = entry_name(raw, f"csv[{index}]")
        else:
            expr = str(raw)
            name = expr
        if not expr:
            raise ValueError(f"csv[{index}] is missing expr")
        payload = bytes_payload(csv_bytes(eval_expr(expr, namespace)))
        items.append({"type": "csv", "name": name, "expr": expr, **payload})
    return items


def capture_text_items(manifest: dict[str, Any], namespace: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("text"))):
        if isinstance(raw, dict):
            name = entry_name(raw, f"text[{index}]")
            if raw.get("file"):
                file_path = root_path(root, str(raw["file"]))
                payload = bytes_payload(file_path.read_bytes())
                items.append({"type": "text", "name": name, "file": str(raw["file"]), **payload})
                continue
            expr = str(raw.get("expr") or "")
        else:
            expr = str(raw)
            name = expr
        if not expr:
            raise ValueError(f"text[{index}] is missing expr or file")
        items.append({"type": "text", "name": name, "expr": expr, **text_payload(str(eval_expr(expr, namespace)))})
    return items


def capture_alias_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("aliases"))):
        if not isinstance(raw, dict):
            raise ValueError("alias entries must be objects")
        alias = str(raw.get("alias") or "")
        target = str(raw.get("target") or "")
        name = entry_name(raw, f"aliases[{index}]")
        if not alias or not target:
            raise ValueError(f"aliases[{index}] requires alias and target")
        alias_obj = resolve_target(alias)
        target_obj = resolve_target(target)
        items.append(
            {
                "type": "alias",
                "name": name,
                "alias": alias,
                "target": target,
                "same_object": alias_obj is target_obj,
                "alias_object": stable_object_label(alias_obj),
                "target_object": stable_object_label(target_obj),
            }
        )
    return items


def stable_object_label(obj: Any) -> str:
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if module and qualname:
        return f"{module}.{qualname}"
    return repr(obj)


def capture_file_items(manifest: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("files"))):
        if isinstance(raw, str):
            name = raw
            path_value = raw
        elif isinstance(raw, dict):
            path_value = str(raw.get("path") or raw.get("file") or "")
            name = entry_name(raw, f"files[{index}]")
        else:
            raise ValueError("file entries must be strings or objects")
        if not path_value:
            raise ValueError(f"files[{index}] is missing path")
        file_path = root_path(root, path_value)
        items.append({"type": "file", "name": name, "path": path_value, **bytes_payload(file_path.read_bytes())})
    return items


def source_paths(manifest: dict[str, Any]) -> list[str]:
    paths = manifest.get("source_paths", [])
    if paths is None:
        return []
    if not isinstance(paths, list):
        raise ValueError("source_paths must be an array")
    return [str(path) for path in paths]


def capture_snapshot(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    root = root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    namespace = import_manifest_modules(manifest)
    items: list[dict[str, Any]] = []
    items.extend(capture_module_items(manifest))
    items.extend(capture_signature_items(manifest))
    items.extend(capture_repr_items(manifest, namespace))
    items.extend(capture_json_items(manifest, namespace))
    items.extend(capture_csv_items(manifest, namespace))
    items.extend(capture_text_items(manifest, namespace, root))
    items.extend(capture_alias_items(manifest))
    items.extend(capture_file_items(manifest, root))
    now = time.time()
    return {
        "check": "behavior_baseline",
        "passed": True,
        "metadata": {
            "captured_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "captured_at_epoch": now,
            "root": str(root),
            "source_paths": source_paths(manifest),
        },
        "items": sorted(items, key=item_key),
    }


def item_key(item: dict[str, Any]) -> str:
    return f"{item.get('type', '')}:{item.get('name', '')}"


def diff_type(item_type: str, field: str | None = None) -> str:
    if item_type == "signature":
        return "signature_changed"
    if item_type == "repr":
        return "str_changed" if field == "str" else "repr_changed"
    if item_type == "json":
        return "json_bytes_changed"
    if item_type == "csv":
        return "csv_bytes_changed"
    if item_type == "text":
        return "text_changed"
    if item_type == "alias":
        return "alias_changed"
    if item_type == "file":
        return "file_bytes_changed"
    if item_type == "module":
        return "module_state_changed"
    return "behavior_changed"


COMPARE_FIELDS = {
    "module": ("public_names", "attrs_json"),
    "signature": ("signature",),
    "repr": ("repr", "str"),
    "json": ("sha256", "length", "bytes_base64"),
    "csv": ("sha256", "length", "bytes_base64"),
    "text": ("sha256", "length", "bytes_base64"),
    "alias": ("same_object", "alias_object", "target_object"),
    "file": ("sha256", "length", "bytes_base64"),
}


def compare_snapshots(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_items = {item_key(item): item for item in baseline.get("items", []) if isinstance(item, dict)}
    current_items = {item_key(item): item for item in current.get("items", []) if isinstance(item, dict)}
    diffs: list[dict[str, Any]] = []

    for key in sorted(set(baseline_items) - set(current_items)):
        item = baseline_items[key]
        diffs.append({"type": "behavior_item_missing", "item": key, "item_type": item.get("type"), "name": item.get("name")})
    for key in sorted(set(current_items) - set(baseline_items)):
        item = current_items[key]
        diffs.append({"type": "behavior_item_added", "item": key, "item_type": item.get("type"), "name": item.get("name")})

    for key in sorted(set(baseline_items) & set(current_items)):
        before = baseline_items[key]
        after = current_items[key]
        item_type = str(before.get("type", ""))
        fields = COMPARE_FIELDS.get(item_type, ())
        for field in fields:
            if before.get(field) != after.get(field):
                diffs.append(
                    {
                        "type": diff_type(item_type, field),
                        "item": key,
                        "item_type": item_type,
                        "name": before.get("name"),
                        "field": field,
                        "before": before.get(field),
                        "after": after.get(field),
                    }
                )
    return diffs


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        result = capture_snapshot(manifest, Path(args.root))
    except Exception as exc:
        result = {"check": "behavior_baseline", "passed": False, "status": "invalid", "items": [], "diffs": [], "reasons": [str(exc)]}
    return emit(result, args.output)


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        baseline = load_json(args.baseline)
        current = capture_snapshot(manifest, Path(args.root))
        diffs = compare_snapshots(baseline, current)
        result = {
            "check": "behavior_diff",
            "passed": not diffs,
            "baseline": args.baseline,
            "metadata": current.get("metadata", {}),
            "diff_count": len(diffs),
            "diffs": diffs,
        }
    except Exception as exc:
        result = {"check": "behavior_diff", "passed": False, "status": "invalid", "diffs": [{"type": "behavior_diff_error", "message": str(exc)}]}
    return emit(result, args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture or verify refactor behavior baselines.")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture the legacy behavior surface before refactor edits")
    capture.add_argument("--manifest", required=True)
    capture.add_argument("--root", default=".")
    capture.add_argument("--output", required=True)
    capture.set_defaults(func=cmd_capture)

    verify = sub.add_parser("verify", help="regenerate behavior and diff it against a baseline")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--baseline", required=True)
    verify.add_argument("--root", default=".")
    verify.add_argument("--output", required=True)
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
