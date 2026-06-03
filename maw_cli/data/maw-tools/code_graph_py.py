#!/usr/bin/env python3
"""Emit the normalized MAW code-graph schema for Python source."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


EDGE_TYPES = {"import", "call", "read_global", "write_global", "inherit", "alias", "dynamic"}


def emit(result: dict[str, Any], output: str | None) -> int:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed", True) else 1


def rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def module_id(root: Path, path: Path) -> str:
    rel = path.resolve().relative_to(root.resolve()).with_suffix("")
    return ".".join(rel.parts)


def iter_py_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    ignored = {".git", "__pycache__", ".venv", "venv", "build", "dist"}
    return sorted(path for path in root.rglob("*.py") if not (set(path.parts) & ignored))


def normalize_tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+|==|!=|<=|>=|[-+*/%<>]", text) if token]


def body_hash(node: ast.AST) -> tuple[str, list[str]]:
    body = getattr(node, "body", [])
    dump = ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)
    digest = hashlib.sha256(dump.encode("utf-8")).hexdigest()
    try:
        source = ast.unparse(ast.Module(body=body, type_ignores=[]))
    except Exception:
        source = dump
    return digest, normalize_tokens(source)


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def assign_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        result: list[str] = []
        for item in target.elts:
            result.extend(assign_names(item))
        return result
    return []


class ScopeCollector(ast.NodeVisitor):
    def __init__(self, module: str, path: str) -> None:
        self.module = module
        self.path = path
        self.symbols: list[dict[str, Any]] = []
        self.top_level_names: set[str] = set()
        self.qual_stack: list[str] = []

    def symbol_id(self, qualname: str) -> str:
        return f"{self.module}:{qualname}"

    def add_symbol(self, name: str, kind: str, node: ast.AST, exported: bool) -> None:
        qualname = ".".join([*self.qual_stack, name])
        symbol: dict[str, Any] = {
            "id": self.symbol_id(qualname),
            "module_id": self.module,
            "name": name,
            "qualname": qualname,
            "kind": kind,
            "exported": exported,
            "location": {"path": self.path, "line": getattr(node, "lineno", 1), "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1))},
        }
        if kind in {"function", "method", "class"}:
            digest, tokens = body_hash(node)
            symbol["normalized_body_hash"] = digest
            symbol["token_signature"] = tokens
        self.symbols.append(symbol)
        if not self.qual_stack:
            self.top_level_names.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        kind = "method" if self.qual_stack else "function"
        self.add_symbol(node.name, kind, node, not node.name.startswith("_"))
        self.qual_stack.append(node.name)
        self.generic_visit(node)
        self.qual_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.add_symbol(node.name, "class", node, not node.name.startswith("_"))
        self.qual_stack.append(node.name)
        self.generic_visit(node)
        self.qual_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> Any:
        if not self.qual_stack:
            for target in node.targets:
                for name in assign_names(target):
                    self.add_symbol(name, "var", node, not name.startswith("_"))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if not self.qual_stack:
            for name in assign_names(node.target):
                self.add_symbol(name, "var", node, not name.startswith("_"))
        self.generic_visit(node)


class EdgeCollector(ast.NodeVisitor):
    def __init__(self, module: str, path: str, known_by_name: dict[str, str], top_level_names: set[str]) -> None:
        self.module = module
        self.path = path
        self.known_by_name = known_by_name
        self.top_level_names = top_level_names
        self.edges: list[dict[str, Any]] = []
        self.scope_stack: list[dict[str, Any]] = [{"id": module, "locals": set()}]
        self.global_decls: list[set[str]] = [set()]

    @property
    def current_id(self) -> str:
        return str(self.scope_stack[-1]["id"])

    @property
    def current_locals(self) -> set[str]:
        return self.scope_stack[-1]["locals"]

    def edge(self, kind: str, to: str, node: ast.AST, **metadata: Any) -> None:
        if kind not in EDGE_TYPES:
            raise AssertionError(kind)
        item: dict[str, Any] = {
            "type": kind,
            "from": self.current_id,
            "to": to,
            "location": {"path": self.path, "line": getattr(node, "lineno", 1)},
        }
        if metadata:
            item["metadata"] = metadata
        self.edges.append(item)

    def target_for_name(self, name: str) -> str:
        return self.known_by_name.get(name, f"external:{name}")

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.edge("import", alias.name, node, imported_as=alias.asname or alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = "." * int(node.level or 0) + str(node.module or "")
        for alias in node.names:
            self.edge("import", f"{module}:{alias.name}", node, imported_as=alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        qual = ".".join([*(str(self.current_id).split(":", 1)[1].split(".") if ":" in self.current_id and self.current_id.split(":", 1)[1] else []), node.name])
        if self.current_id == self.module:
            qual = node.name
        sid = f"{self.module}:{qual}"
        local_names = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
        if node.args.vararg:
            local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_names.add(node.args.kwarg.arg)
        self.scope_stack.append({"id": sid, "locals": local_names})
        self.global_decls.append(set())
        self.generic_visit(node)
        self.global_decls.pop()
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        sid = f"{self.module}:{node.name}" if self.current_id == self.module else f"{self.current_id}.{node.name}"
        for base in node.bases:
            name = call_name(base)
            if name:
                self.edge("inherit", self.target_for_name(name), base)
        self.scope_stack.append({"id": sid, "locals": set()})
        self.global_decls.append(set())
        self.generic_visit(node)
        self.global_decls.pop()
        self.scope_stack.pop()

    def visit_Global(self, node: ast.Global) -> Any:
        self.global_decls[-1].update(node.names)

    def visit_Call(self, node: ast.Call) -> Any:
        name = call_name(node.func)
        if name:
            if name in {"getattr", "setattr", "eval", "exec", "__import__"} or name.startswith("import_module"):
                dynamic_kind = "monkeypatch" if name == "setattr" else "dynamic_dispatch"
                self.edge("dynamic", f"dynamic:{name}", node, dynamic_kind=dynamic_kind)
            self.edge("call", self.target_for_name(name), node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        names = [name for target in node.targets for name in assign_names(target)]
        if self.current_id == self.module and isinstance(node.value, ast.Name):
            for name in names:
                self.edge("alias", self.target_for_name(node.value.id), node, alias=name)
        for name in names:
            if self.current_id == self.module:
                continue
            if name in self.top_level_names or name in self.global_decls[-1]:
                self.edge("write_global", self.target_for_name(name), node)
            else:
                self.current_locals.add(name)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        for name in assign_names(node.target):
            if self.current_id != self.module and (name in self.top_level_names or name in self.global_decls[-1]):
                self.edge("write_global", self.target_for_name(name), node)
            else:
                self.current_locals.add(name)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> Any:
        for name in assign_names(node.target):
            if self.current_id != self.module and (name in self.top_level_names or name in self.global_decls[-1]):
                self.edge("write_global", self.target_for_name(name), node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> Any:
        if self.current_id != self.module and isinstance(node.ctx, ast.Load):
            if node.id in self.top_level_names and node.id not in self.current_locals:
                self.edge("read_global", self.target_for_name(node.id), node)


def graph_for(root: Path, entrypoints: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    files = iter_py_files(root)
    modules: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    trees: dict[Path, ast.Module] = {}
    top_levels: dict[str, set[str]] = {}

    for path in files:
        rel = rel_path(root, path)
        mid = module_id(root, path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        trees[path] = tree
        modules.append({"id": mid, "path": rel, "language": "python"})
        symbols.append({"id": mid, "module_id": mid, "name": mid.rsplit(".", 1)[-1], "qualname": mid, "kind": "module", "exported": True, "location": {"path": rel, "line": 1, "end_line": 1}})
        collector = ScopeCollector(mid, rel)
        collector.visit(tree)
        symbols.extend(collector.symbols)
        top_levels[mid] = collector.top_level_names

    known_by_name: dict[str, str] = {}
    for symbol in symbols:
        name = str(symbol.get("name"))
        if name and name not in known_by_name:
            known_by_name[name] = str(symbol["id"])
        qualname = str(symbol.get("qualname", ""))
        if qualname and qualname not in known_by_name:
            known_by_name[qualname] = str(symbol["id"])

    edges: list[dict[str, Any]] = []
    for path, tree in trees.items():
        mid = module_id(root, path)
        collector = EdgeCollector(mid, rel_path(root, path), known_by_name, top_levels.get(mid, set()))
        collector.visit(tree)
        edges.extend(collector.edges)

    if entrypoints is None:
        entrypoints = sorted(symbol["id"] for symbol in symbols if symbol.get("kind") in {"function", "class"} and symbol.get("exported") is True)

    return {
        "schema_version": 1,
        "language": "python",
        "root": str(root),
        "modules": sorted(modules, key=lambda item: item["id"]),
        "symbols": sorted(symbols, key=lambda item: item["id"]),
        "edges": sorted(edges, key=lambda item: (item["type"], item["from"], item["to"], item.get("location", {}).get("line", 0))),
        "entrypoints": sorted(entrypoints),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit normalized Python code graph JSON.")
    parser.add_argument("path", help="Python file or project root")
    parser.add_argument("--entrypoint", action="append", dest="entrypoints", help="preserved-surface symbol id; may be repeated")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = graph_for(Path(args.path), args.entrypoints)
        result["passed"] = True
    except Exception as exc:
        result = {"schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "errors": [str(exc)], "modules": [], "symbols": [], "edges": [], "entrypoints": []}
    return emit(result, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
