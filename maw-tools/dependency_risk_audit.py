#!/usr/bin/env python3
"""Detect hidden dependency risks in Python source files."""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ANNOTATION_PREFIX = "# MAW-DEPENDENCY-RISK:"
MUTATING_METHODS = {"append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse", "update", "setdefault", "add", "discard"}
ENV_NAMES = {"environ", "getenv"}
TIME_RANDOM_NAMES = {"time", "monotonic", "perf_counter", "now", "today", "utcnow", "random", "randint", "choice", "shuffle", "uuid4"}
RISK_FIELDS = [
    "file",
    "line",
    "symbol",
    "risk_type",
    "severity",
    "explanation",
    "affected_symbols_or_files",
    "recommended_fix",
    "confidence",
]


@dataclass
class ModuleInfo:
    path: Path
    module: str
    tree: ast.Module
    module_globals: set[str] = field(default_factory=set)
    imports: dict[str, str] = field(default_factory=dict)
    imported_modules: set[str] = field(default_factory=set)
    risks: list[dict[str, Any]] = field(default_factory=list)
    calls: dict[str, set[str]] = field(default_factory=dict)
    string_literals: list[tuple[str, int, str]] = field(default_factory=list)


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def module_name(path: Path, root: Path) -> str:
    rel = path.resolve().relative_to(root.resolve())
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def iter_python_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".py" else []
    ignored = {"__pycache__", ".git", ".venv", "build", "dist"}
    return sorted(item for item in path.rglob("*.py") if not any(part in ignored for part in item.parts))


def risk_id(risk: dict[str, Any]) -> str:
    raw = "|".join(str(risk.get(key, "")) for key in ("file", "symbol", "risk_type", "explanation"))
    return "MAW-BUG-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8].upper()


def add_risk(info: ModuleInfo, root: Path, line: int, symbol: str, risk_type: str, severity: str, explanation: str, affected: list[str], fix: str, confidence: float) -> None:
    risk = {
        "file": relative(info.path, root),
        "line": line,
        "symbol": symbol,
        "risk_type": risk_type,
        "severity": severity,
        "explanation": explanation,
        "affected_symbols_or_files": affected,
        "recommended_fix": fix,
        "confidence": round(confidence, 2),
    }
    risk["id"] = risk_id(risk)
    info.risks.append(risk)


def call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return None


def assigned_names(target: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            names.update(assigned_names(item))
    elif isinstance(target, ast.Attribute):
        base = call_name(target)
        if base:
            names.add(base)
    return names


def collect_module_info(path: Path, root: Path) -> ModuleInfo:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    info = ModuleInfo(path=path, module=module_name(path, root), tree=tree)
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                info.module_globals.update(name for name in assigned_names(target) if name.isidentifier())
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if imported_module:
                    info.imported_modules.add(imported_module)
                for alias in node.names:
                    if alias.name == "*":
                        add_risk(info, root, node.lineno, "*", "broad_import", "medium", "Wildcard import hides dependencies and makes symbol ownership unclear.", [imported_module or "relative import"], "Import explicit names.", 0.88)
                    if node.level and not imported_module:
                        info.imported_modules.add(alias.name)
                        info.imports[alias.asname or alias.name] = alias.name
                    else:
                        info.imports[alias.asname or alias.name] = f"{imported_module}.{alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    info.imported_modules.add(alias.name)
                    info.imports[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            name = call_name(node.value.func) or "call"
            add_risk(info, root, node.lineno, name, "import_time_side_effect", "medium", "Top-level call runs at import time and can create hidden startup dependencies.", [info.module], "Move side effects behind a function or explicit entrypoint.", 0.75)
    return info


class FunctionAnalyzer(ast.NodeVisitor):
    def __init__(self, info: ModuleInfo, root: Path, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.info = info
        self.root = root
        self.node = node
        self.symbol = node.name
        self.args = {arg.arg for arg in node.args.args + node.args.kwonlyargs}
        self.assigned: set[str] = set()
        self.calls: set[str] = set()
        self.categories: set[str] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.assigned.update(assigned_names(target))
            self._check_mutable_arg_assignment(target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.assigned.update(assigned_names(node.target))
        self._check_mutable_arg_assignment(node.target, node.lineno)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and node.id in self.info.module_globals and node.id not in self.assigned:
            self.categories.add("global_state")
            add_risk(
                self.info,
                self.root,
                node.lineno,
                self.symbol,
                "global_state_read",
                "medium",
                f"Function reads module global `{node.id}`, so behavior can change outside the function signature.",
                [node.id],
                "Pass the value as an argument or wrap it in an explicit configuration object.",
                0.78,
            )
        elif isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in self.info.module_globals:
            self.categories.add("global_state")
            add_risk(
                self.info,
                self.root,
                node.lineno,
                self.symbol,
                "global_state_mutation",
                "high",
                f"Function mutates module global `{node.id}`, creating order-dependent behavior.",
                [node.id],
                "Return updated state or isolate mutation behind a documented state manager.",
                0.86,
            )

    def visit_Call(self, node: ast.Call) -> None:
        name = call_name(node.func)
        if name:
            self.calls.add(name)
            if self._is_env_call(name):
                self.categories.add("environment")
                add_risk(self.info, self.root, node.lineno, self.symbol, "environment_variable_dependency", "medium", f"Function depends on environment access `{name}`.", [name], "Inject configuration or validate environment at startup.", 0.9)
            if name in {"os.getcwd", "Path.cwd", "pathlib.Path.cwd"}:
                self.categories.add("filesystem")
                add_risk(self.info, self.root, node.lineno, self.symbol, "current_working_directory_dependency", "medium", "Function depends on current working directory.", [name], "Accept a base path argument or resolve paths from a known root.", 0.9)
            if any(name.endswith(f".{item}") or name == item for item in TIME_RANDOM_NAMES):
                self.categories.add("time_random")
                severity = "medium" if not any(arg in {"clock", "rng", "seed", "now"} for arg in self.args) else "low"
                add_risk(self.info, self.root, node.lineno, self.symbol, "time_or_random_dependency", severity, f"Function calls `{name}` without an obvious injected source.", [name], "Inject a clock, RNG, or seed for deterministic tests.", 0.82)
            if name.split(".")[0] in self.info.imports and "." in name:
                self.categories.add("cross_module")
                add_risk(self.info, self.root, node.lineno, self.symbol, "cross_module_call", "low", f"Function calls imported dependency `{name}`.", [self.info.imports.get(name.split('.')[0], name)], "Keep this dependency covered by integration or contract tests.", 0.64)
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in self.args and node.func.attr in MUTATING_METHODS:
                self.categories.add("mutable_args")
                add_risk(self.info, self.root, node.lineno, self.symbol, "shared_mutable_argument", "high", f"Function mutates argument `{node.func.value.id}` via `{node.func.attr}`.", [node.func.value.id], "Copy the argument or return a new value instead of mutating caller-owned state.", 0.9)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        name = call_name(node.value)
        if name == "os.environ":
            self.categories.add("environment")
            add_risk(self.info, self.root, node.lineno, self.symbol, "environment_variable_dependency", "medium", "Function depends on environment variable lookup through `os.environ`.", ["os.environ"], "Inject configuration or validate environment at startup.", 0.9)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and len(node.value) >= 4:
            self.info.string_literals.append((node.value, node.lineno, self.symbol))

    def _is_env_call(self, name: str) -> bool:
        return name in {"os.getenv", "os.environ.get"} or name.endswith(".environ.get")

    def _check_mutable_arg_assignment(self, target: ast.AST, line: int) -> None:
        if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in self.args:
            self.categories.add("mutable_args")
            add_risk(self.info, self.root, line, self.symbol, "shared_mutable_argument", "high", f"Function assigns into argument `{target.value.id}`.", [target.value.id], "Copy the input or return explicit updates instead of mutating caller-owned data.", 0.9)

    def finish(self) -> None:
        self.info.calls[self.symbol] = self.calls
        line_count = (getattr(self.node, "end_lineno", self.node.lineno) or self.node.lineno) - self.node.lineno + 1
        if len(self.calls) >= 8:
            add_risk(self.info, self.root, self.node.lineno, self.symbol, "high_fan_out", "medium", f"Function fans out to {len(self.calls)} calls.", sorted(self.calls), "Split orchestration from computation or inject a smaller collaborator.", 0.72)
        if line_count >= 45 or (line_count >= 25 and len(self.categories) >= 3):
            add_risk(self.info, self.root, self.node.lineno, self.symbol, "large_mixed_responsibility_function", "medium", f"Function spans {line_count} lines and touches {len(self.categories)} dependency categories.", sorted(self.categories), "Split the function by responsibility and add focused tests.", 0.7)


def analyze_functions(info: ModuleInfo, root: Path) -> None:
    for node in ast.walk(info.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            analyzer = FunctionAnalyzer(info, root, node)
            analyzer.visit(node)
            analyzer.finish()


def add_duplicate_literal_risks(infos: list[ModuleInfo], root: Path) -> None:
    occurrences: dict[str, list[tuple[ModuleInfo, int, str]]] = {}
    for info in infos:
        for literal, line, symbol in info.string_literals:
            if literal.strip() and not literal.startswith(("http://", "https://")):
                occurrences.setdefault(literal, []).append((info, line, symbol))
    for literal, items in occurrences.items():
        files = sorted({relative(info.path, root) for info, _line, _symbol in items})
        if len(files) < 2:
            continue
        severity = "high" if literal.endswith("_rate") or "key" in literal.lower() or "_" in literal else "medium"
        for info, line, symbol in items:
            add_risk(
                info,
                root,
                line,
                symbol,
                "implicit_coupling_magic_string",
                severity,
                f"Literal `{literal}` appears in multiple files and may be an implicit shared contract.",
                files,
                "Introduce a shared constant or schema validation for this value.",
                0.84 if severity == "high" else 0.68,
            )


def add_graph_risks(infos: list[ModuleInfo], root: Path) -> None:
    modules = {info.module: info for info in infos}
    short_to_module = {Path(info.module.replace(".", "/")).name: info.module for info in infos}
    graph: dict[str, set[str]] = {info.module: set() for info in infos}
    for info in infos:
        for imported in info.imported_modules:
            target = imported if imported in modules else short_to_module.get(imported.split(".")[0])
            if target and target != info.module:
                graph[info.module].add(target)

    for module, deps in graph.items():
        for dep in deps:
            if module in graph.get(dep, set()):
                info = modules[module]
                add_risk(info, root, 1, module, "circular_import", "high", f"Module `{module}` and `{dep}` import each other.", [module, dep], "Extract shared contracts into a third module or invert one dependency.", 0.92)

    fan_in: dict[str, set[str]] = {}
    for info in infos:
        for caller, calls in info.calls.items():
            for called in calls:
                fan_in.setdefault(called, set()).add(f"{info.module}.{caller}")
    for called, callers in fan_in.items():
        if len(callers) >= 4:
            owner = next((info for info in infos if called in info.calls or called.split(".")[0] in info.imports), infos[0])
            add_risk(owner, root, 1, called, "high_fan_in", "medium", f"Symbol `{called}` is called from {len(callers)} places.", sorted(callers), "Treat this as a shared contract and require regression coverage before changing it.", 0.65)


def analyze_path(path: Path) -> tuple[Path, list[ModuleInfo], list[dict[str, Any]]]:
    files = iter_python_files(path)
    root = path if path.is_dir() else path.parent
    infos: list[ModuleInfo] = []
    parse_errors: list[dict[str, Any]] = []
    for file in files:
        try:
            infos.append(collect_module_info(file, root))
        except SyntaxError as exc:
            parse_errors.append({"file": relative(file, root), "line": exc.lineno or 1, "error": str(exc)})
    for info in infos:
        analyze_functions(info, root)
    add_duplicate_literal_risks(infos, root)
    add_graph_risks(infos, root)
    return root, infos, parse_errors


def annotation_for(risk: dict[str, Any]) -> str:
    affected = ", ".join(risk["affected_symbols_or_files"][:2]) or "related code"
    if len(affected) > 45:
        affected = affected[:42] + "..."
    reason = risk["risk_type"].replace("_", " ")
    return f"{ANNOTATION_PREFIX} Changing this may affect {affected}. Reason: {reason}. See docs/bugs/{risk['id']}.md"


def annotate_files(root: Path, risks: list[dict[str, Any]], dry_run: bool) -> list[dict[str, Any]]:
    by_file: dict[str, list[dict[str, Any]]] = {}
    for risk in risks:
        if risk["severity"] in {"high", "medium"}:
            by_file.setdefault(risk["file"], []).append(risk)
    changes: list[dict[str, Any]] = []
    for rel_file, file_risks in by_file.items():
        path = root / rel_file
        lines = path.read_text(encoding="utf-8").splitlines()
        inserts: list[tuple[int, str, str]] = []
        for risk in sorted(file_risks, key=lambda item: int(item["line"])):
            index = max(int(risk["line"]) - 1, 0)
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())] if index < len(lines) else ""
            comment = indent + annotation_for(risk)
            already = any(risk["id"] in line and line.strip().startswith(ANNOTATION_PREFIX) for line in lines)
            if not already:
                inserts.append((index, comment, risk["id"]))
        if not inserts:
            continue
        if not dry_run:
            offset = 0
            for index, comment, _risk_id in inserts:
                lines.insert(index + offset, comment)
                offset += 1
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        changes.append({"file": rel_file, "insertions": len(inserts), "risk_ids": [risk_id for _index, _comment, risk_id in inserts], "dry_run": dry_run})
    return changes


def dossier_text(risk: dict[str, Any], run_artifact: str | None) -> str:
    today = dt.date.today().isoformat()
    affected_files = "\n".join(f"- {item}" for item in risk["affected_symbols_or_files"] if item.endswith(".py")) or f"- {risk['file']}"
    affected_symbols = "\n".join(f"- {risk['symbol']}")
    links = f"- {run_artifact}" if run_artifact else "- none recorded"
    return f"""# {risk['id']}: {risk['risk_type'].replace('_', ' ').title()}

Status: open
Severity: {risk['severity']}

## Affected files
{affected_files}

## Affected symbols
{affected_symbols}

## Root cause
{risk['explanation']}

## Reproduction steps, if applicable
1. Inspect `{risk['file']}` near line {risk['line']}.
2. Change `{risk['symbol']}` or one of the affected contracts.
3. Run the relevant regression tests for the affected files.

## Expected behavior
The dependency should be explicit, validated, or isolated behind a stable contract.

## Actual behavior
The dependency is implicit and may break when related code changes.

## Fix strategy
{risk['recommended_fix']}

## Regression tests needed
- Add a focused test covering `{risk['symbol']}` and affected files before changing this contract.

## Links to run artifacts
{links}

## Date discovered
{today}

## Date fixed, if fixed
not fixed
"""


def write_dossiers(root: Path, risks: list[dict[str, Any]], docs_dir: Path, run_artifact: str | None) -> list[str]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for risk in risks:
        if risk["severity"] != "high":
            continue
        path = docs_dir / f"{risk['id']}.md"
        path.write_text(dossier_text(risk, run_artifact), encoding="utf-8")
        written.append(relative(path, root))
    return sorted(written)


def severity_rank(value: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(value, 0)


def build_result(path: Path, annotate: bool, dry_run: bool, docs_dir: Path | None, no_dossiers: bool, run_artifact: str | None) -> dict[str, Any]:
    root, infos, parse_errors = analyze_path(path)
    risks = sorted([risk for info in infos for risk in info.risks], key=lambda item: (item["file"], int(item["line"]), item["risk_type"]))
    annotations = annotate_files(root, risks, dry_run) if annotate else []
    dossiers = [] if no_dossiers else write_dossiers(root, risks, docs_dir or root / "docs" / "bugs", run_artifact)
    summary = {
        "files_scanned": len(infos),
        "risk_count": len(risks),
        "high": sum(1 for risk in risks if risk["severity"] == "high"),
        "medium": sum(1 for risk in risks if risk["severity"] == "medium"),
        "low": sum(1 for risk in risks if risk["severity"] == "low"),
        "parse_errors": len(parse_errors),
    }
    return {
        "check": "dependency-risk-audit",
        "path": str(path),
        "passed": not parse_errors,
        "summary": summary,
        "risks": risks,
        "parse_errors": parse_errors,
        "annotations": annotations,
        "dossiers": dossiers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect hidden dependency risks in Python source files.")
    parser.add_argument("path")
    parser.add_argument("--annotate", action="store_true", help="insert idempotent MAW dependency risk comments")
    parser.add_argument("--dry-run", action="store_true", help="preview annotations and dossiers without changing source annotations")
    parser.add_argument("--fail-on", choices=["low", "medium", "high"], help="exit non-zero when any risk at this severity or above exists")
    parser.add_argument("--docs-dir", help="directory for generated high-severity bug dossiers")
    parser.add_argument("--no-dossiers", action="store_true", help="skip high-severity dossier generation")
    parser.add_argument("--run-artifact", help="run artifact link to include in generated dossiers")
    parser.add_argument("--output", help="write JSON result to a file")
    args = parser.parse_args(argv)

    result = build_result(
        Path(args.path),
        annotate=args.annotate,
        dry_run=args.dry_run,
        docs_dir=Path(args.docs_dir) if args.docs_dir else None,
        no_dossiers=args.no_dossiers or args.dry_run,
        run_artifact=args.run_artifact,
    )
    text = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)

    if not result["passed"]:
        return 1
    if args.fail_on:
        threshold = severity_rank(args.fail_on)
        if any(severity_rank(risk["severity"]) >= threshold for risk in result["risks"]):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
