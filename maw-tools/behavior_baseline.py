#!/usr/bin/env python3
"""Capture and verify deterministic behavior snapshots for refactor tasks."""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import difflib
import hashlib
import importlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import trace
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


def capture_process_items(manifest: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("processes"))):
        if not isinstance(raw, dict):
            raise ValueError("process entries must be objects")
        command = raw.get("cmd") or raw.get("command")
        if isinstance(command, str):
            shell = True
            cmd_for_run: str | list[str] = command
            command_repr: str | list[str] = command
        elif isinstance(command, list) and all(isinstance(part, str) for part in command):
            shell = False
            cmd_for_run = [sys.executable if part == "{python}" else part for part in command]
            command_repr = command
        else:
            raise ValueError(f"processes[{index}] requires cmd/command as a string or string array")
        timeout = float(raw.get("timeout", 10))
        name = entry_name(raw, f"processes[{index}]")
        proc = subprocess.run(cmd_for_run, cwd=root, capture_output=True, text=True, shell=shell, timeout=timeout)
        items.append(
            {
                "type": "process",
                "name": name,
                "command": command_repr,
                "exit_code": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "stdout_sha256": hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest(),
                "stderr_sha256": hashlib.sha256(proc.stderr.encode("utf-8")).hexdigest(),
            }
        )
    return items


def capture_exception_items(manifest: dict[str, Any], namespace: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("exceptions"))):
        if isinstance(raw, dict):
            expr = str(raw.get("expr") or "")
            name = entry_name(raw, f"exceptions[{index}]")
        else:
            expr = str(raw)
            name = expr
        if not expr:
            raise ValueError(f"exceptions[{index}] is missing expr")
        try:
            eval_expr(expr, namespace)
        except Exception as exc:
            items.append(
                {
                    "type": "exception",
                    "name": name,
                    "expr": expr,
                    "raised": True,
                    "exception_type": type(exc).__name__,
                    "exception_module": type(exc).__module__,
                    "message": str(exc),
                }
            )
        else:
            items.append({"type": "exception", "name": name, "expr": expr, "raised": False, "exception_type": None, "exception_module": None, "message": ""})
    return items


def capture_file_effect_items(manifest: dict[str, Any], namespace: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(as_entries(manifest.get("file_effects"))):
        if not isinstance(raw, dict):
            raise ValueError("file_effect entries must be objects")
        expr = str(raw.get("expr") or "")
        files = raw.get("files")
        name = entry_name(raw, f"file_effects[{index}]")
        if not expr:
            raise ValueError(f"file_effects[{index}] is missing expr")
        if not isinstance(files, list) or not files:
            raise ValueError(f"file_effects[{index}] requires files")
        for file_name in files:
            path = root_path(root, str(file_name))
            path.unlink(missing_ok=True)
        value = eval_expr(expr, namespace)
        written: list[dict[str, Any]] = []
        for file_name in files:
            path = root_path(root, str(file_name))
            if path.exists():
                payload = bytes_payload(path.read_bytes())
                written.append({"file": str(file_name), "exists": True, **payload})
            else:
                written.append({"file": str(file_name), "exists": False, "sha256": None, "length": 0, "bytes_base64": ""})
        items.append({"type": "file_effect", "name": name, "expr": expr, "return_repr": repr(value), "files": written})
    return items


def source_paths(manifest: dict[str, Any]) -> list[str]:
    paths = manifest.get("source_paths", [])
    if paths is None:
        return []
    if not isinstance(paths, list):
        raise ValueError("source_paths must be an array")
    return [str(path) for path in paths]


def rel_or_abs(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def source_file_records(manifest: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in source_paths(manifest):
        path = root_path(root, raw)
        data = path.read_bytes()
        text = data.decode("utf-8")
        records.append(
            {
                "path": raw,
                "resolved_path": str(path.resolve()),
                "relative_path": rel_or_abs(root, path),
                "sha256": hashlib.sha256(data).hexdigest(),
                "text": text,
                "line_count": len(text.splitlines()),
            }
        )
    return sorted(records, key=lambda item: item["path"])


def function_signature_from_ast(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    params: list[dict[str, Any]] = []
    for arg, default in zip(positional, defaults):
        params.append({"name": arg.arg, "kind": "positional", "default": ast.unparse(default) if default is not None else None})
    if args.vararg:
        params.append({"name": args.vararg.arg, "kind": "vararg", "default": None})
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append({"name": arg.arg, "kind": "keyword_only", "default": ast.unparse(default) if default is not None else None})
    if args.kwarg:
        params.append({"name": args.kwarg.arg, "kind": "kwarg", "default": None})
    return {"params": params, "returns": ast.unparse(node.returns) if node.returns is not None else None}


def literal_string_list(node: ast.AST) -> list[str] | None:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def public_api_for_source(path: Path, root: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_name = rel_or_abs(root, path.with_suffix("")).replace("/", ".")
    functions: dict[str, Any] = {}
    classes: dict[str, Any] = {}
    all_values: list[str] | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions[node.name] = function_signature_from_ast(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods: dict[str, Any] = {}
            init_signature: dict[str, Any] | None = None
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                    methods[child.name] = function_signature_from_ast(child)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == "__init__":
                    init_signature = function_signature_from_ast(child)
            classes[node.name] = {"bases": [ast.unparse(base) for base in node.bases], "init": init_signature, "methods": methods}
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    all_values = literal_string_list(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            all_values = literal_string_list(node.value)
    return {"module": module_name, "path": rel_or_abs(root, path), "functions": functions, "classes": classes, "__all__": all_values}


def capture_public_api(manifest: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in source_paths(manifest):
        path = root_path(root, raw)
        if path.suffix == ".py":
            records.append(public_api_for_source(path, root))
    return sorted(records, key=lambda item: item["path"])


def purge_pycache_for_sources(manifest: dict[str, Any], root: Path) -> None:
    for raw in source_paths(manifest):
        path = root_path(root, raw)
        cache = path.parent / "__pycache__"
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)


def capture_snapshot(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    root = root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    purge_pycache_for_sources(manifest, root)
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
    items.extend(capture_process_items(manifest, root))
    items.extend(capture_exception_items(manifest, namespace))
    items.extend(capture_file_effect_items(manifest, namespace, root))
    now = time.time()
    return {
        "check": "behavior_baseline",
        "passed": True,
        "metadata": {
            "captured_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "captured_at_epoch": now,
            "root": str(root),
            "source_paths": source_paths(manifest),
            "source_files": source_file_records(manifest, root),
            "public_api": capture_public_api(manifest, root),
            "performance": capture_performance(manifest, root, int(manifest.get("performance_repeats", 5))),
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
    if item_type == "process":
        if field == "exit_code":
            return "process_exit_code_changed"
        if field == "stderr":
            return "process_stderr_changed"
        return "process_stdout_changed"
    if item_type == "exception":
        if field in {"exception_type", "exception_module"}:
            return "exception_type_changed"
        if field == "message":
            return "exception_message_changed"
        return "exception_behavior_changed"
    if item_type == "file_effect":
        return "written_file_bytes_changed"
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
    "process": ("exit_code", "stdout", "stderr", "stdout_sha256", "stderr_sha256"),
    "exception": ("raised", "exception_type", "exception_module", "message"),
    "file_effect": ("return_repr", "files"),
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


def stable_snapshot_surface(snapshot: dict[str, Any]) -> dict[str, Any]:
    metadata = snapshot.get("metadata", {}) if isinstance(snapshot.get("metadata"), dict) else {}
    return {
        "items": snapshot.get("items", []),
        "source_files": metadata.get("source_files", []),
        "public_api": metadata.get("public_api", []),
    }


def compare_api_surfaces(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_map = {item["path"]: item for item in before}
    after_map = {item["path"]: item for item in after}
    diffs: list[dict[str, Any]] = []
    for path in sorted(set(before_map) - set(after_map)):
        diffs.append({"type": "api_module_removed", "path": path, "before": before_map[path]})
    for path in sorted(set(after_map) - set(before_map)):
        diffs.append({"type": "api_module_added", "path": path, "after": after_map[path]})
    for path in sorted(set(before_map) & set(after_map)):
        for field in ("functions", "classes", "__all__"):
            if before_map[path].get(field) != after_map[path].get(field):
                diffs.append({"type": f"api_{field}_changed", "path": path, "field": field, "before": before_map[path].get(field), "after": after_map[path].get(field)})
    return diffs


def baseline_source_map(baseline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata = baseline.get("metadata", {}) if isinstance(baseline.get("metadata"), dict) else {}
    files = metadata.get("source_files", [])
    return {str(item.get("path")): item for item in files if isinstance(item, dict)}


def changed_current_lines(before_text: str, after_text: str) -> set[int]:
    before = before_text.splitlines()
    after = after_text.splitlines()
    changed: set[int] = set()
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after).get_opcodes():
        if tag != "equal":
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def executed_lines_for_capture(manifest: dict[str, Any], root: Path) -> dict[str, set[int]]:
    tracer = trace.Trace(count=True, trace=False)
    tracer.runfunc(capture_snapshot, manifest, root)
    executed: dict[str, set[int]] = {}
    for (filename, line), count in tracer.results().counts.items():
        if count > 0:
            executed.setdefault(str(Path(filename).resolve()), set()).add(int(line))
    return executed


MUTATION_KINDS = (
    "flip_boolean_default",
    "off_by_one_return",
    "swap_operator",
    "drop_branch",
    "process_exit_code",
    "exception_message",
    "file_effect_bytes",
)


def mutation_transformer(kind: str) -> ast.NodeTransformer:
    class Mutator(ast.NodeTransformer):
        def __init__(self) -> None:
            self.changed = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self.generic_visit(node)
            if kind == "flip_boolean_default" and not self.changed:
                for index, default in enumerate(node.args.defaults):
                    if isinstance(default, ast.Constant) and isinstance(default.value, bool):
                        node.args.defaults[index] = ast.copy_location(ast.Constant(value=not default.value), default)
                        self.changed = True
                        break
            return node

        def visit_Return(self, node: ast.Return) -> Any:
            self.generic_visit(node)
            if kind == "process_exit_code" and not self.changed and isinstance(node.value, ast.Constant) and node.value.value == 0:
                node.value = ast.copy_location(ast.Constant(value=1), node.value)
                self.changed = True
                return node
            if kind == "off_by_one_return" and not self.changed and isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)) and not isinstance(node.value.value, bool):
                node.value = ast.copy_location(ast.Constant(value=node.value.value + 1), node.value)
                self.changed = True
            return node

        def visit_Raise(self, node: ast.Raise) -> Any:
            self.generic_visit(node)
            if kind == "exception_message" and not self.changed and isinstance(node.exc, ast.Call):
                if node.exc.args and isinstance(node.exc.args[0], ast.Constant) and isinstance(node.exc.args[0].value, str):
                    node.exc.args[0] = ast.copy_location(ast.Constant(value=node.exc.args[0].value + " changed"), node.exc.args[0])
                    self.changed = True
            return node

        def visit_BinOp(self, node: ast.BinOp) -> Any:
            self.generic_visit(node)
            if kind == "swap_operator" and not self.changed:
                replacements = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Add, ast.Div: ast.Mult}
                for old, new in replacements.items():
                    if isinstance(node.op, old):
                        node.op = new()
                        self.changed = True
                        break
            return node

        def visit_Constant(self, node: ast.Constant) -> Any:
            if kind == "file_effect_bytes" and not self.changed and isinstance(node.value, str) and "stable-bytes" in node.value:
                self.changed = True
                return ast.copy_location(ast.Constant(value=node.value.replace("stable-bytes", "changed-bytes")), node)
            return node

        def visit_If(self, node: ast.If) -> Any:
            self.generic_visit(node)
            if kind == "drop_branch" and not self.changed:
                if node.orelse:
                    node.orelse = []
                else:
                    node.test = ast.copy_location(ast.Constant(value=False), node.test)
                self.changed = True
            return node

    return Mutator()


def plant_mutation(root: Path, source_path_values: list[str], kind: str) -> dict[str, Any] | None:
    for raw in source_path_values:
        path = root_path(root, raw)
        if path.suffix != ".py" or not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        mutator = mutation_transformer(kind)
        new_tree = mutator.visit(tree)
        if getattr(mutator, "changed", False):
            ast.fix_missing_locations(new_tree)
            path.write_text(ast.unparse(new_tree) + "\n", encoding="utf-8")
            return {"kind": kind, "path": raw}
    return None


def copy_root(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".venv", "build", "dist", "*.egg-info")
    shutil.copytree(src, dst, ignore=ignore)


def python_source_files(root: Path, manifest: dict[str, Any], plan: dict[str, Any]) -> list[Path]:
    raw_paths = source_paths(manifest) or [str(path) for path in plan.get("source_paths", []) if isinstance(path, str)]
    if not raw_paths:
        raw_paths = [str(path.relative_to(root)) for path in root.rglob("*.py") if "__pycache__" not in path.parts]
    return [root_path(root, raw).resolve() for raw in raw_paths if root_path(root, raw).suffix == ".py" and root_path(root, raw).exists()]


def parse_files(paths: list[Path]) -> dict[str, ast.Module]:
    return {str(path): ast.parse(path.read_text(encoding="utf-8"), filename=str(path)) for path in paths}


def ast_name_refs(tree: ast.AST, name: str) -> list[int]:
    return [getattr(node, "lineno", 0) for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == name]


def ast_call_refs(tree: ast.AST, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                lines.append(getattr(node, "lineno", 0))
            elif isinstance(func, ast.Attribute) and func.attr == name:
                lines.append(getattr(node, "lineno", 0))
    return lines


def ast_def_lines(tree: ast.AST, name: str) -> list[int]:
    return [
        getattr(node, "lineno", 0)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name
    ]


def ast_assign_alias_lines(tree: ast.AST, alias: str, target: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(isinstance(item, ast.Name) and item.id == alias for item in node.targets):
                if isinstance(node.value, ast.Name) and node.value.id == target:
                    lines.append(getattr(node, "lineno", 0))
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                imported = item.asname or item.name
                if imported == alias and item.name == target:
                    lines.append(getattr(node, "lineno", 0))
    return lines


def function_body_hashes(trees: dict[str, ast.Module]) -> dict[str, list[dict[str, Any]]]:
    hashes: dict[str, list[dict[str, Any]]] = {}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body_dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
                digest = hashlib.sha256(body_dump.encode("utf-8")).hexdigest()
                hashes.setdefault(digest, []).append({"path": path, "name": node.name, "line": getattr(node, "lineno", 0)})
    return hashes


def collect_refs(trees: dict[str, ast.Module], name: str, calls_only: bool = False) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for path, tree in trees.items():
        lines = ast_call_refs(tree, name) if calls_only else ast_name_refs(tree, name)
        refs.extend({"path": path, "line": line} for line in lines)
    return refs


def structure_config(plan: dict[str, Any]) -> dict[str, Any]:
    config = plan.get("structure")
    return config if isinstance(config, dict) else plan


def check_structure(plan: dict[str, Any], manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    root = root.resolve()
    refactor_type = str(plan.get("refactor_type") or "")
    config = structure_config(plan)
    paths = python_source_files(root, manifest, plan)
    trees = parse_files(paths)
    violations: list[dict[str, Any]] = []
    details: dict[str, Any] = {"files": [rel_or_abs(root, path) for path in paths]}

    if refactor_type == "rename":
        old_name = str(config.get("old_name") or "")
        new_name = str(config.get("new_name") or "")
        old_refs = collect_refs(trees, old_name) if old_name else []
        new_refs = collect_refs(trees, new_name) if new_name else []
        new_defs = [item for path, tree in trees.items() for line in ast_def_lines(tree, new_name) for item in [{"path": path, "line": line}]]
        details.update({"old_name": old_name, "new_name": new_name, "old_refs": old_refs, "new_refs": new_refs, "new_defs": new_defs})
        if old_refs:
            violations.append({"type": "rename_old_name_remaining", "message": "old name remains after rename", "refs": old_refs})
        if not (new_refs or new_defs):
            violations.append({"type": "rename_new_name_unresolved", "message": "new name does not resolve", "new_name": new_name})
    elif refactor_type == "extract-function":
        extracted = str(config.get("extracted_name") or config.get("symbol") or "")
        removed_text = str(config.get("inlined_body_text") or "")
        defs = [item for path, tree in trees.items() for line in ast_def_lines(tree, extracted) for item in [{"path": path, "line": line}]]
        calls = collect_refs(trees, extracted, calls_only=True)
        raw_hits = []
        if removed_text:
            for path in paths:
                if removed_text in path.read_text(encoding="utf-8"):
                    raw_hits.append({"path": str(path), "text": removed_text})
        details.update({"extracted_name": extracted, "defs": defs, "calls": calls, "inlined_body_hits": raw_hits})
        if not defs:
            violations.append({"type": "extract_symbol_missing", "message": "extracted symbol is missing", "symbol": extracted})
        if not calls:
            violations.append({"type": "extract_symbol_not_called", "message": "extracted symbol is not called", "symbol": extracted})
        if raw_hits:
            violations.append({"type": "extract_inlined_body_remaining", "message": "inlined body remains after extraction", "hits": raw_hits})
    elif refactor_type == "inline":
        symbol = str(config.get("symbol") or config.get("old_name") or "")
        defs = [item for path, tree in trees.items() for line in ast_def_lines(tree, symbol) for item in [{"path": path, "line": line}]]
        calls = collect_refs(trees, symbol, calls_only=True)
        details.update({"symbol": symbol, "defs": defs, "calls": calls})
        if defs:
            violations.append({"type": "inline_symbol_still_defined", "message": "inlined symbol is still defined", "defs": defs})
        if calls:
            violations.append({"type": "inline_callers_not_updated", "message": "callers still reference inlined symbol", "calls": calls})
    elif refactor_type == "move-module":
        symbol = str(config.get("symbol") or "")
        old_path = str(config.get("old_path") or "")
        new_path = str(config.get("new_path") or "")
        alias_declared = bool(config.get("compatibility_alias"))
        old_file = root_path(root, old_path).resolve() if old_path else None
        new_file = root_path(root, new_path).resolve() if new_path else None
        old_tree = trees.get(str(old_file)) if old_file else None
        new_tree = trees.get(str(new_file)) if new_file else None
        old_defs = ast_def_lines(old_tree, symbol) if old_tree is not None else []
        new_defs = ast_def_lines(new_tree, symbol) if new_tree is not None else []
        alias_lines = ast_assign_alias_lines(old_tree, symbol, symbol) if old_tree is not None else []
        details.update({"symbol": symbol, "old_path": old_path, "new_path": new_path, "old_defs": old_defs, "new_defs": new_defs, "alias_lines": alias_lines, "compatibility_alias": alias_declared})
        if old_defs:
            violations.append({"type": "move_old_path_still_defines_symbol", "message": "old import path still defines moved symbol", "lines": old_defs})
        if not new_defs:
            violations.append({"type": "move_new_path_missing_symbol", "message": "new import path does not define moved symbol", "symbol": symbol})
        if alias_lines and not alias_declared:
            violations.append({"type": "move_undeclared_compatibility_alias", "message": "compatibility alias exists but was not declared", "lines": alias_lines})
        if alias_declared and not alias_lines:
            violations.append({"type": "move_declared_alias_missing", "message": "declared compatibility alias is missing", "symbol": symbol})
    elif refactor_type == "dedupe":
        survivor = str(config.get("survivor") or "")
        baseline_count = int(config.get("baseline_duplicate_count", 2))
        hashes = function_body_hashes(trees)
        duplicate_groups = [[item for item in items if item["name"] != survivor] for items in hashes.values() if len([item for item in items if item["name"] != survivor]) > 1]
        survivor_calls = collect_refs(trees, survivor, calls_only=True)
        survivor_defs = [item for path, tree in trees.items() for line in ast_def_lines(tree, survivor) for item in [{"path": path, "line": line}]]
        details.update({"survivor": survivor, "duplicate_groups": duplicate_groups, "survivor_calls": survivor_calls, "survivor_defs": survivor_defs, "baseline_duplicate_count": baseline_count})
        if duplicate_groups:
            violations.append({"type": "dedupe_duplicate_definitions_remain", "message": "duplicated definitions remain", "duplicate_groups": duplicate_groups})
        if len(survivor_defs) != 1:
            violations.append({"type": "dedupe_survivor_missing", "message": "survivor definition is missing or ambiguous", "defs": survivor_defs})
        if len(survivor_calls) < max(1, baseline_count - 1):
            violations.append({"type": "dedupe_former_call_sites_not_updated", "message": "survivor is not referenced by former call sites", "calls": survivor_calls})
    else:
        violations.append({"type": "unknown_refactor_type", "message": f"unsupported refactor_type: {refactor_type}"})

    return {"check": "refactor_structure", "schema_version": 1, "passed": not violations, "refactor_type": refactor_type, "details": details, "violations": violations}


def complexity_tolerance(plan: dict[str, Any]) -> dict[str, int]:
    raw = plan.get("complexity_tolerance", 0)
    if isinstance(raw, int):
        return {"cyclomatic_complexity": raw, "max_nesting_depth": raw, "function_length": raw}
    if isinstance(raw, dict):
        return {
            "cyclomatic_complexity": int(raw.get("cyclomatic_complexity", raw.get("cyclomatic", 0))),
            "max_nesting_depth": int(raw.get("max_nesting_depth", raw.get("nesting", 0))),
            "function_length": int(raw.get("function_length", raw.get("length", 0))),
        }
    return {"cyclomatic_complexity": 0, "max_nesting_depth": 0, "function_length": 0}


def function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, int]:
    complexity = 1
    max_depth = 0
    control_nodes = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler, ast.Match)

    def visit(child: ast.AST, depth: int) -> None:
        nonlocal complexity, max_depth
        next_depth = depth
        if isinstance(child, control_nodes):
            complexity += 1
            next_depth = depth + 1
            max_depth = max(max_depth, next_depth)
        elif isinstance(child, ast.BoolOp):
            complexity += max(0, len(child.values) - 1)
        elif isinstance(child, (ast.IfExp, ast.comprehension)):
            complexity += 1
        for grandchild in ast.iter_child_nodes(child):
            visit(grandchild, next_depth)

    for child in node.body:
        visit(child, 0)
    end_lineno = getattr(node, "end_lineno", getattr(node, "lineno", 0))
    return {
        "cyclomatic_complexity": complexity,
        "max_nesting_depth": max_depth,
        "function_length": max(0, int(end_lineno) - int(getattr(node, "lineno", end_lineno)) + 1),
    }


def function_metric_map_from_text(text: str, filename: str) -> dict[str, dict[str, Any]]:
    tree = ast.parse(text, filename=filename)
    result: dict[str, dict[str, Any]] = {}

    def collect(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                collect(node.body, f"{prefix}{node.name}.")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{node.name}"
                result[qualname] = {
                    "qualname": qualname,
                    "lineno": getattr(node, "lineno", 0),
                    "end_lineno": getattr(node, "end_lineno", getattr(node, "lineno", 0)),
                    "body_sha256": hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest(),
                    "metrics": function_complexity(node),
                }
                collect(node.body, f"{qualname}.")

    collect(tree.body)
    return result


def baseline_text_by_path(baseline: dict[str, Any]) -> dict[str, str]:
    metadata = baseline.get("metadata", {}) if isinstance(baseline.get("metadata"), dict) else {}
    files = metadata.get("source_files", [])
    return {str(item.get("path")): str(item.get("text", "")) for item in files if isinstance(item, dict)}


def check_complexity(plan: dict[str, Any], manifest: dict[str, Any], baseline: dict[str, Any], root: Path) -> dict[str, Any]:
    root = root.resolve()
    tolerances = complexity_tolerance(plan)
    justified = bool(plan.get("complexity_justification") or plan.get("justify_complexity_increase"))
    before_texts = baseline_text_by_path(baseline)
    functions: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for raw in source_paths(manifest):
        path = root_path(root, raw)
        if path.suffix != ".py" or raw not in before_texts or not path.exists():
            continue
        before = function_metric_map_from_text(before_texts[raw], raw)
        after = function_metric_map_from_text(path.read_text(encoding="utf-8"), str(path))
        for qualname in sorted(set(before) & set(after)):
            if before[qualname]["body_sha256"] == after[qualname]["body_sha256"]:
                continue
            deltas = {
                metric: after[qualname]["metrics"][metric] - before[qualname]["metrics"][metric]
                for metric in ("cyclomatic_complexity", "max_nesting_depth", "function_length")
            }
            item = {
                "path": raw,
                "qualname": qualname,
                "before": before[qualname]["metrics"],
                "after": after[qualname]["metrics"],
                "delta": deltas,
                "passed": True,
                "reasons": [],
            }
            for metric, delta in deltas.items():
                if delta > tolerances[metric]:
                    reason = f"{metric} increased by {delta}, tolerance {tolerances[metric]}"
                    item["passed"] = justified
                    item["reasons"].append(reason)
                    if not justified:
                        violations.append({"type": "complexity_increase", "path": raw, "qualname": qualname, "metric": metric, "delta": delta, "tolerance": tolerances[metric], "message": reason})
            functions.append(item)

    return {
        "check": "refactor_complexity",
        "schema_version": 1,
        "passed": not violations,
        "tolerances": tolerances,
        "complexity_justified": justified,
        "functions": functions,
        "violations": violations,
    }


def median_value(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def performance_budget(plan: dict[str, Any]) -> dict[str, Any]:
    raw = plan.get("performance_budget", {})
    if isinstance(raw, (int, float)):
        raw = {"max_regression_ratio": float(raw)}
    if not isinstance(raw, dict):
        raw = {}
    repeats = int(raw.get("repeats", plan.get("perf_repeats", 5)))
    return {
        "repeats": max(3, repeats),
        "max_regression_ratio": float(raw.get("max_regression_ratio", plan.get("perf_max_regression_ratio", 3.0))),
        "noise_ratio": float(raw.get("noise_ratio", 8.0)),
        "clear_regression_ratio": float(raw.get("clear_regression_ratio", 6.0)),
    }


def performance_probe_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    for section in ("reprs", "json", "csv"):
        for index, raw in enumerate(as_entries(manifest.get(section))):
            if isinstance(raw, dict):
                expr = str(raw.get("expr") or "")
                name = entry_name(raw, f"{section}[{index}]")
            else:
                expr = str(raw)
                name = expr
            if expr:
                probes.append({"type": section[:-1] if section.endswith("s") else section, "name": name, "expr": expr})
    for index, raw in enumerate(as_entries(manifest.get("text"))):
        if isinstance(raw, dict) and raw.get("file"):
            continue
        expr = str(raw.get("expr") or "") if isinstance(raw, dict) else str(raw)
        name = entry_name(raw, f"text[{index}]") if isinstance(raw, dict) else expr
        if expr:
            probes.append({"type": "text", "name": name, "expr": expr})
    for index, raw in enumerate(as_entries(manifest.get("exceptions"))):
        expr = str(raw.get("expr") or "") if isinstance(raw, dict) else str(raw)
        name = entry_name(raw, f"exceptions[{index}]") if isinstance(raw, dict) else expr
        if expr:
            probes.append({"type": "exception", "name": name, "expr": expr})
    for index, raw in enumerate(as_entries(manifest.get("file_effects"))):
        if isinstance(raw, dict) and raw.get("expr"):
            probes.append({"type": "file_effect", "name": entry_name(raw, f"file_effects[{index}]"), "expr": str(raw["expr"]), "files": raw.get("files", [])})
    for index, raw in enumerate(as_entries(manifest.get("processes"))):
        if isinstance(raw, dict):
            command = raw.get("cmd") or raw.get("command")
            if command:
                probes.append({"type": "process", "name": entry_name(raw, f"processes[{index}]"), "command": command, "timeout": raw.get("timeout", 10)})
    return probes


def source_file_set(manifest: dict[str, Any], root: Path) -> set[str]:
    return {str(root_path(root, raw).resolve()) for raw in source_paths(manifest)}


def trace_line_count(tracer: trace.Trace, source_files: set[str]) -> int | None:
    if not source_files:
        return None
    total = 0
    for (filename, _line), count in tracer.results().counts.items():
        if count > 0 and str(Path(filename).resolve()) in source_files:
            total += int(count)
    return total


def run_perf_probe(probe: dict[str, Any], namespace: dict[str, Any], root: Path, source_files: set[str]) -> int | None:
    probe_type = probe["type"]
    if probe_type == "process":
        command = probe.get("command")
        if isinstance(command, str):
            subprocess.run(command, cwd=root, capture_output=True, text=True, shell=True, timeout=float(probe.get("timeout", 10)))
        elif isinstance(command, list) and all(isinstance(part, str) for part in command):
            subprocess.run([sys.executable if part == "{python}" else part for part in command], cwd=root, capture_output=True, text=True, shell=False, timeout=float(probe.get("timeout", 10)))
        return None

    def execute() -> None:
        if probe_type == "file_effect":
            for file_name in probe.get("files", []):
                root_path(root, str(file_name)).unlink(missing_ok=True)
        try:
            eval_expr(str(probe["expr"]), namespace)
        except Exception:
            if probe_type != "exception":
                raise

    tracer = trace.Trace(count=True, trace=False)
    tracer.runfunc(execute)
    return trace_line_count(tracer, source_files)


def capture_performance(manifest: dict[str, Any], root: Path, repeats: int = 5) -> dict[str, Any]:
    root = root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    purge_pycache_for_sources(manifest, root)
    namespace = import_manifest_modules(manifest)
    files = source_file_set(manifest, root)
    probes: list[dict[str, Any]] = []
    for probe in performance_probe_entries(manifest):
        wall_times: list[float] = []
        line_counts: list[float] = []
        feasible_line_count = probe["type"] != "process" and bool(files)
        for _ in range(max(1, repeats)):
            start = time.perf_counter()
            line_count = run_perf_probe(probe, namespace, root, files)
            elapsed = time.perf_counter() - start
            wall_times.append(elapsed)
            if line_count is not None:
                line_counts.append(float(line_count))
        wall_min = min(wall_times) if wall_times else 0.0
        wall_max = max(wall_times) if wall_times else 0.0
        probes.append(
            {
                "type": probe["type"],
                "name": probe["name"],
                "key": f"{probe['type']}:{probe['name']}",
                "repeats": max(1, repeats),
                "wall_time_seconds": {
                    "samples": [round(value, 9) for value in wall_times],
                    "median": round(median_value(wall_times), 9),
                    "min": round(wall_min, 9),
                    "max": round(wall_max, 9),
                    "noise_ratio": round((wall_max / wall_min), 6) if wall_min > 0 else None,
                },
                "line_count": {
                    "feasible": feasible_line_count,
                    "samples": [int(value) for value in line_counts],
                    "median": int(round(median_value(line_counts))) if line_counts else None,
                },
            }
        )
    return {"schema_version": 1, "repeats": max(1, repeats), "probes": sorted(probes, key=lambda item: item["key"])}


def check_perf_budget(plan: dict[str, Any], manifest: dict[str, Any], baseline: dict[str, Any], root: Path) -> dict[str, Any]:
    budget = performance_budget(plan)
    baseline_perf = baseline.get("metadata", {}).get("performance", {}) if isinstance(baseline.get("metadata"), dict) else {}
    before_probes = {str(item.get("key")): item for item in baseline_perf.get("probes", []) if isinstance(item, dict)}
    current = capture_performance(manifest, root, int(budget["repeats"]))
    violations: list[dict[str, Any]] = []
    probes: list[dict[str, Any]] = []
    advisory_reasons: list[str] = []

    for after in current["probes"]:
        before = before_probes.get(str(after["key"]))
        if not before:
            continue
        before_wall = float(before.get("wall_time_seconds", {}).get("median") or 0.0)
        after_wall = float(after.get("wall_time_seconds", {}).get("median") or 0.0)
        wall_ratio = (after_wall / before_wall) if before_wall > 0 else None
        before_noise = before.get("wall_time_seconds", {}).get("noise_ratio")
        after_noise = after.get("wall_time_seconds", {}).get("noise_ratio")
        noisy = any(isinstance(value, (int, float)) and value > budget["noise_ratio"] for value in (before_noise, after_noise))
        line_before = before.get("line_count", {}).get("median")
        line_after = after.get("line_count", {}).get("median")
        line_ratio = (float(line_after) / float(line_before)) if isinstance(line_before, int) and line_before > 0 and isinstance(line_after, int) else None
        item = {
            "key": after["key"],
            "type": after["type"],
            "name": after["name"],
            "before": before,
            "after": after,
            "wall_time_ratio": round(wall_ratio, 6) if wall_ratio is not None else None,
            "line_count_ratio": round(line_ratio, 6) if line_ratio is not None else None,
            "noisy": noisy,
            "passed": True,
            "reasons": [],
        }
        if noisy and wall_ratio is not None and wall_ratio <= budget["clear_regression_ratio"]:
            item["advisory"] = True
            advisory_reasons.append(f"{after['key']} timing is too noisy for a hard budget")
        if wall_ratio is not None and wall_ratio > budget["max_regression_ratio"] and (not noisy or wall_ratio > budget["clear_regression_ratio"]):
            reason = f"wall time median regressed {wall_ratio:.2f}x, budget {budget['max_regression_ratio']:.2f}x"
            item["passed"] = False
            item["reasons"].append(reason)
            violations.append({"type": "wall_time_regression", "probe": after["key"], "ratio": round(wall_ratio, 6), "budget": budget["max_regression_ratio"], "message": reason})
        if line_ratio is not None and line_ratio > budget["max_regression_ratio"]:
            reason = f"trace line count regressed {line_ratio:.2f}x, budget {budget['max_regression_ratio']:.2f}x"
            item["passed"] = False
            item["reasons"].append(reason)
            violations.append({"type": "line_count_regression", "probe": after["key"], "ratio": round(line_ratio, 6), "budget": budget["max_regression_ratio"], "message": reason})
        probes.append(item)

    return {
        "check": "refactor_perf_budget",
        "schema_version": 1,
        "passed": not violations,
        "status": "advisory" if advisory_reasons and not violations else "passed" if not violations else "failed",
        "budget": budget,
        "baseline": {"repeats": baseline_perf.get("repeats"), "probe_count": len(before_probes)},
        "current": {"repeats": current["repeats"], "probe_count": len(current["probes"])},
        "probes": probes,
        "violations": violations,
        "advisory_reasons": sorted(set(advisory_reasons)),
    }


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        first = capture_snapshot(manifest, Path(args.root))
        second = capture_snapshot(manifest, Path(args.root))
        stable = stable_snapshot_surface(first) == stable_snapshot_surface(second)
        first["determinism"] = {
            "passed": stable,
            "captures": 2,
            "reason": "identical pre-edit captures" if stable else "pre-edit captures differed",
        }
        first["passed"] = stable
        if not stable:
            first["status"] = "flaky_baseline"
            first["reasons"] = ["determinism guard failed: pre-edit baseline changed across two captures"]
            first["determinism"]["first_sha256"] = hashlib.sha256(stable_json_bytes(stable_snapshot_surface(first))).hexdigest()
            first["determinism"]["second_sha256"] = hashlib.sha256(stable_json_bytes(stable_snapshot_surface(second))).hexdigest()
        result = first
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


def cmd_api(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        baseline = load_json(args.baseline)
        before = baseline.get("metadata", {}).get("public_api", [])
        after = capture_public_api(manifest, Path(args.root).resolve())
        diffs = compare_api_surfaces(before, after)
        justified = bool(args.allow_api_change)
        passed = not diffs or justified
        result = {
            "check": "api_surface_diff",
            "passed": passed,
            "baseline": args.baseline,
            "diff_count": len(diffs),
            "diffs": diffs,
            "api_change_justified": justified,
            "before": before,
            "after": after,
        }
        if diffs and not justified:
            result["reasons"] = ["public API surface changed without an explicit plan justification"]
    except Exception as exc:
        result = {"check": "api_surface_diff", "passed": False, "status": "invalid", "diffs": [{"type": "api_surface_error", "message": str(exc)}]}
    return emit(result, args.output)


def cmd_coverage(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        baseline = load_json(args.baseline)
        root = Path(args.root).resolve()
        before_map = baseline_source_map(baseline)
        executed = executed_lines_for_capture(manifest, root)
        files: list[dict[str, Any]] = []
        uncovered: list[dict[str, Any]] = []
        for raw in source_paths(manifest):
            path = root_path(root, raw).resolve()
            before_text = str(before_map.get(raw, {}).get("text", ""))
            after_text = path.read_text(encoding="utf-8")
            changed = sorted(changed_current_lines(before_text, after_text))
            covered = sorted(set(changed) & executed.get(str(path), set()))
            missing = sorted(set(changed) - set(covered))
            files.append({"path": raw, "changed_lines": changed, "covered_changed_lines": covered, "uncovered_changed_lines": missing})
            for line in missing:
                uncovered.append({"path": raw, "line": line, "reason": "behavior surface not covered"})
        result = {
            "check": "refactor_coverage",
            "passed": not uncovered,
            "baseline": args.baseline,
            "files": files,
            "uncovered": uncovered,
            "uncovered_count": len(uncovered),
        }
        if uncovered:
            result["reasons"] = ["behavior surface not covered: at least one changed source line was not exercised by baseline probes"]
    except Exception as exc:
        result = {"check": "refactor_coverage", "passed": False, "status": "invalid", "uncovered": [{"type": "coverage_error", "message": str(exc)}]}
    return emit(result, args.output)


def run_verify_subprocess(script: Path, manifest: Path, baseline: Path, root: Path, output: Path) -> tuple[int, dict[str, Any], str, str]:
    proc = subprocess.run(
        [sys.executable, str(script), "verify", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(output)],
        capture_output=True,
        text=True,
        cwd=root,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "status": "invalid", "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data, proc.stdout, proc.stderr


def cmd_resistance(args: argparse.Namespace) -> int:
    try:
        manifest_path = Path(args.manifest).resolve()
        baseline_path = Path(args.baseline).resolve()
        root = Path(args.root).resolve()
        manifest = load_json(manifest_path)
        baseline = load_json(baseline_path)
        clean_current = capture_snapshot(manifest, root)
        clean_diffs = compare_snapshots(baseline, clean_current)
        clean = {"passed": not clean_diffs, "diff_count": len(clean_diffs), "diffs": clean_diffs}
        mutations: list[dict[str, Any]] = []
        script = Path(__file__).resolve()
        for kind in MUTATION_KINDS:
            with tempfile.TemporaryDirectory() as tmp_dir:
                mutant_root = Path(tmp_dir) / "mutant"
                copy_root(root, mutant_root)
                planted = plant_mutation(mutant_root, source_paths(manifest), kind)
                if planted is None:
                    mutations.append({"name": kind, "planted": False, "caught": False, "mutant_passed": True, "failed_checks": [], "reason": "no mutation candidate found"})
                    continue
                output = Path(tmp_dir) / "behavior-diff.json"
                code, data, _stdout, stderr = run_verify_subprocess(script, manifest_path, baseline_path, mutant_root, output)
                mutant_passed = bool(data.get("passed")) and code == 0
                diffs = data.get("diffs", []) if isinstance(data.get("diffs"), list) else []
                failed_checks = sorted({str(item.get("type")) for item in diffs if isinstance(item, dict) and item.get("type")})
                mutations.append(
                    {
                        "name": kind,
                        "planted": True,
                        "path": planted["path"],
                        "caught": not mutant_passed and bool(failed_checks),
                        "mutant_passed": mutant_passed,
                        "failed_checks": failed_checks,
                        "stderr": stderr.strip(),
                    }
                )
        caught = sum(1 for item in mutations if item.get("caught") is True)
        passed = clean["passed"] and bool(mutations) and caught == len(mutations) and caught > 0
        result = {
            "check": "refactor_resistance",
            "schema_version": 1,
            "passed": passed,
            "baseline": args.baseline,
            "clean": clean,
            "mutations": mutations,
            "summary": {"total": len(mutations), "caught": caught},
        }
        if not passed:
            result["reasons"] = []
            if not clean["passed"]:
                result["reasons"].append("clean behavior diff must pass before mutation resistance is trusted")
            if caught == 0:
                result["reasons"].append("baseline caught no planted behavior mutations")
            elif caught != len(mutations):
                result["reasons"].append("one or more planted behavior mutations escaped the baseline diff")
    except Exception as exc:
        result = {"check": "refactor_resistance", "schema_version": 1, "passed": False, "status": "invalid", "mutations": [], "reasons": [str(exc)]}
    return emit(result, args.output)


def cmd_structure(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        plan = load_json(args.plan)
        result = check_structure(plan, manifest, Path(args.root))
    except Exception as exc:
        result = {"check": "refactor_structure", "schema_version": 1, "passed": False, "status": "invalid", "violations": [{"type": "structure_error", "message": str(exc)}]}
    return emit(result, args.output)


def cmd_complexity(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        plan = load_json(args.plan)
        baseline = load_json(args.baseline)
        result = check_complexity(plan, manifest, baseline, Path(args.root))
    except Exception as exc:
        result = {"check": "refactor_complexity", "schema_version": 1, "passed": False, "status": "invalid", "violations": [{"type": "complexity_error", "message": str(exc)}]}
    return emit(result, args.output)


def cmd_perf(args: argparse.Namespace) -> int:
    try:
        manifest = load_json(args.manifest)
        plan = load_json(args.plan)
        baseline = load_json(args.baseline)
        result = check_perf_budget(plan, manifest, baseline, Path(args.root))
    except Exception as exc:
        result = {"check": "refactor_perf_budget", "schema_version": 1, "passed": False, "status": "invalid", "violations": [{"type": "perf_budget_error", "message": str(exc)}], "probes": []}
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

    api = sub.add_parser("api", help="compare AST public API surface against a baseline")
    api.add_argument("--manifest", required=True)
    api.add_argument("--baseline", required=True)
    api.add_argument("--root", default=".")
    api.add_argument("--output", required=True)
    api.add_argument("--allow-api-change", action="store_true")
    api.set_defaults(func=cmd_api)

    coverage = sub.add_parser("coverage", help="require changed source lines to be exercised by baseline probes")
    coverage.add_argument("--manifest", required=True)
    coverage.add_argument("--baseline", required=True)
    coverage.add_argument("--root", default=".")
    coverage.add_argument("--output", required=True)
    coverage.set_defaults(func=cmd_coverage)

    resistance = sub.add_parser("resistance", help="plant behavior mutations and require the baseline diff to catch them")
    resistance.add_argument("--manifest", required=True)
    resistance.add_argument("--baseline", required=True)
    resistance.add_argument("--root", default=".")
    resistance.add_argument("--output", required=True)
    resistance.set_defaults(func=cmd_resistance)

    structure = sub.add_parser("structure", help="run refactor_type-specific AST structural checks")
    structure.add_argument("--plan", required=True)
    structure.add_argument("--manifest", required=True)
    structure.add_argument("--root", default=".")
    structure.add_argument("--output", required=True)
    structure.set_defaults(func=cmd_structure)

    complexity = sub.add_parser("complexity", help="compare changed-function complexity before and after a refactor")
    complexity.add_argument("--plan", required=True)
    complexity.add_argument("--manifest", required=True)
    complexity.add_argument("--baseline", required=True)
    complexity.add_argument("--root", default=".")
    complexity.add_argument("--output", required=True)
    complexity.set_defaults(func=cmd_complexity)

    perf = sub.add_parser("perf", help="compare behavior probe performance against the pre-refactor baseline")
    perf.add_argument("--plan", required=True)
    perf.add_argument("--manifest", required=True)
    perf.add_argument("--baseline", required=True)
    perf.add_argument("--root", default=".")
    perf.add_argument("--output", required=True)
    perf.set_defaults(func=cmd_perf)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
