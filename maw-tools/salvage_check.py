#!/usr/bin/env python3
"""Hard deterministic gates for MAW salvage refactor workflows."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

import behavior_baseline
import web_checks


SURFACE = "artifacts/preserved-surface.json"
SURFACE_SHA = "artifacts/preserved-surface.sha256"
TOPOLOGY = "artifacts/topology.json"
CHARACTERIZATION_BASELINE = "artifacts/characterization-baseline.json"
CODE_GRAPH = "artifacts/code-graph.json"
PRESERVE_PARITY = "artifacts/preserve-parity.json"
HIDDEN_DEPS = "artifacts/hidden-deps.json"
CROSS_LANG = "artifacts/cross-lang-couplings.json"
DEAD_CODE = "artifacts/dead-code.json"
DUPLICATION = "artifacts/duplication.json"
RESISTANCE = "artifacts/salvage-resistance.json"
RESULT = "artifacts/salvage-result.json"
EDGE_COUPLINGS = {"read_global", "write_global", "dynamic"}
TRAVERSAL_EDGES = {"call", "alias", "inherit", "read_global", "write_global", "dynamic", "dom_ref", "css_ref", "route_ref", "template_var", "asset_ref"}
WEB_EDGE_COUPLINGS = {"dom_ref", "css_ref", "route_ref", "template_var", "asset_ref"}
EXPECTED_RESISTANCE = {
    "reintroduced_hidden_dependency": "hidden-deps",
    "resurrected_dead_reference": "dead-code",
    "reduplicated_function": "duplication",
    "preserved_surface_behavior_break": "preserve-parity",
    "server_preserved_surface_behavior_break": "preserve-parity",
    "client_preserved_surface_behavior_break": "preserve-parity",
    "broken_cross_language_coupling": "cross-lang",
    "surface_shrink_gaming": "surface-freeze",
}


def emit(result: dict[str, Any], output: str | None = None) -> int:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed") is True else 1


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_object(path: str | Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sha(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip().split()[0]
    if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError(f"invalid SHA-256 digest: {path}")
    return value.lower()


def artifact_path(run_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else run_dir / value


def as_str_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def surface_entrypoints(surface: dict[str, Any]) -> list[str]:
    return sorted(set(as_str_list(surface.get("entrypoints"))))


def graph_entrypoints(graph: dict[str, Any]) -> list[str]:
    return sorted(set(as_str_list(graph.get("entrypoints"))))


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    result = {"type": kind, "message": message}
    result.update(extra)
    return result


def check_surface_freeze(run_dir: Path, graph: dict[str, Any] | None = None, dead_code: dict[str, Any] | None = None) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    surface_path = run_dir / SURFACE
    sha_path = run_dir / SURFACE_SHA
    surface: dict[str, Any] = {}

    if not surface_path.is_file():
        violations.append(violation("missing_preserved_surface", f"missing preserved surface: {surface_path}", artifact=SURFACE))
    else:
        try:
            surface = load_json_object(surface_path)
        except Exception as exc:
            violations.append(violation("invalid_preserved_surface", str(exc), artifact=SURFACE))

    if not sha_path.is_file():
        violations.append(violation("missing_preserved_surface_hash", f"missing preserved surface hash: {sha_path}", artifact=SURFACE_SHA))
    elif surface_path.is_file():
        try:
            expected = read_sha(sha_path)
            actual = sha256_file(surface_path)
            if actual != expected:
                violations.append(
                    violation(
                        "preserved_surface_hash_mismatch",
                        "preserved-surface.json changed after freeze",
                        artifact=SURFACE,
                        expected=expected,
                        actual=actual,
                    )
                )
        except Exception as exc:
            violations.append(violation("invalid_preserved_surface_hash", str(exc), artifact=SURFACE_SHA))

    frozen = surface_entrypoints(surface)
    before = sorted(set(as_str_list(surface.get("entrypoints_before"))))
    if before and len(frozen) < len(before):
        violations.append(
            violation(
                "preserved_surface_shrank",
                "preserved surface entrypoints shrank after freeze",
                before_count=len(before),
                current_count=len(frozen),
                removed=sorted(set(before) - set(frozen)),
            )
        )

    if graph is not None:
        current = graph_entrypoints(graph)
        if current != frozen:
            violations.append(
                violation(
                    "code_graph_entrypoints_differ_from_frozen_surface",
                    "code graph entrypoints must match preserved-surface.json",
                    frozen_entrypoints=frozen,
                    graph_entrypoints=current,
                )
            )

    if dead_code is not None:
        proof = dead_code.get("proof")
        if isinstance(proof, dict):
            proof_entrypoints = sorted(set(as_str_list(proof.get("entrypoints"))))
            if proof_entrypoints != frozen:
                violations.append(
                    violation(
                        "dead_code_proof_entrypoints_differ_from_frozen_surface",
                        "dead-code proof used a different entrypoint set from the frozen preserved surface",
                        frozen_entrypoints=frozen,
                        proof_entrypoints=proof_entrypoints,
                    )
                )

    return {"check": "salvage_surface_freeze", "passed": not violations, "violations": violations, "entrypoints": frozen}


def maybe_load_graph(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / CODE_GRAPH
    if path.is_file():
        data = load_json_object(path)
        return data
    return None


def subset_manifest(manifest: dict[str, Any], surface: dict[str, Any]) -> dict[str, Any]:
    behavior = surface.get("behavior_manifest")
    if isinstance(behavior, dict):
        result = dict(behavior)
        if "source_paths" not in result and "source_paths" in manifest:
            result["source_paths"] = manifest["source_paths"]
        return result
    include = set(as_str_list(surface.get("behavior_names")))
    if not include:
        return manifest
    filtered: dict[str, Any] = {}
    for key, value in manifest.items():
        if isinstance(value, list):
            kept = []
            for item in value:
                name = item if isinstance(item, str) else item.get("name") if isinstance(item, dict) else None
                if key == "source_paths" or str(name) in include:
                    kept.append(item)
            filtered[key] = kept
        else:
            filtered[key] = value
    return filtered


def cmd_preserve_parity(args: argparse.Namespace) -> int:
    try:
        run_dir = Path(args.run) if args.run else None
        surface = load_json_object(args.preserved_surface)
        freeze = check_surface_freeze(run_dir, maybe_load_graph(run_dir)) if run_dir is not None else {"check": "salvage_surface_freeze", "applicable": False, "passed": True, "violations": [], "entrypoints": surface_entrypoints(surface)}
        violations = list(freeze["violations"])
        baseline_path = args.characterization_baseline or args.baseline
        if args.characterization_baseline:
            baseline = load_json_object(args.characterization_baseline)
            if baseline.get("check") != "salvage_characterization" or not baseline.get("items"):
                violations.append(violation("missing_pre_gut_characterization", "preserved-surface parity requires a captured pre-gut characterization baseline", artifact=args.characterization_baseline))
            current = characterize_target(args.target or str(baseline.get("target", ".")), Path(args.root) if args.root else None, args.test_cmd or str(baseline.get("test_command", "")) or None)
            diffs = compare_characterizations(baseline, current)
        else:
            if not args.manifest or not args.baseline:
                raise ValueError("preserve-parity requires either --characterization-baseline or --manifest plus --baseline")
            manifest = load_json_object(args.manifest)
            scoped_manifest = subset_manifest(manifest, surface)
            baseline = load_json_object(args.baseline)
            current = behavior_baseline.capture_snapshot(scoped_manifest, Path(args.root))
            diffs = behavior_baseline.compare_snapshots(baseline, current)
        for diff in diffs:
            if isinstance(diff, dict):
                violations.append(violation("preserved_surface_behavior_drift", "preserved-surface behavior changed", diff=diff))
        result = {
            "check": "salvage_preserve_parity",
            "schema_version": 1,
            "passed": not violations,
            "baseline": baseline_path,
            "diff_count": len(diffs),
            "diffs": diffs,
            "freeze": freeze,
            "violations": violations,
        }
    except Exception as exc:
        result = {"check": "salvage_preserve_parity", "schema_version": 1, "passed": False, "status": "invalid", "diffs": [], "violations": [violation("preserve_parity_error", str(exc))]}
    return emit(result, args.output)


def symbol_map(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in graph.get("symbols", []) if isinstance(item, dict) and item.get("id")}


def edge_list(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in graph.get("edges", []) if isinstance(item, dict)]


def symbol_module(symbol_id: str, symbols: dict[str, dict[str, Any]]) -> str:
    item = symbols.get(symbol_id)
    if item:
        return str(item.get("module_id", ""))
    if ":" in symbol_id:
        return symbol_id.split(":", 1)[0]
    return symbol_id


def source_text(root: Path) -> str:
    chunks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".jinja", ".jinja2", ".j2", ".css"}:
            try:
                chunks.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
    return "\n".join(chunks)


def iter_source_files(root: Path, suffixes: set[str] | None = None) -> list[Path]:
    if root.is_file():
        return [root] if suffixes is None or root.suffix.lower() in suffixes else []
    ignored = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
    return sorted(path for path in root.rglob("*") if path.is_file() and not (set(path.parts) & ignored) and (suffixes is None or path.suffix.lower() in suffixes))


def rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def detect_topology(root: Path) -> dict[str, Any]:
    suffixes = {path.suffix.lower() for path in iter_source_files(root)}
    package = root / "package.json"
    package_data: dict[str, Any] = {}
    if package.is_file():
        try:
            package_data = load_json_object(package)
        except Exception:
            package_data = {}
    text_samples: list[str] = []
    for path in iter_source_files(root, {".py", ".html", ".htm", ".jinja", ".jinja2", ".j2", ".js", ".ts", ".tsx", ".jsx"}):
        try:
            text_samples.append(path.read_text(encoding="utf-8")[:20000])
        except UnicodeDecodeError:
            pass
    joined = "\n".join(text_samples)
    deps = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(package_data.get(key), dict):
            deps.update(package_data[key])
    signals = {
        "has_python": ".py" in suffixes,
        "has_html": bool(suffixes & {".html", ".htm", ".jinja", ".jinja2", ".j2"}),
        "has_css": ".css" in suffixes,
        "has_js_ts": bool(suffixes & {".js", ".jsx", ".ts", ".tsx"}),
        "has_package_json": package.is_file(),
        "has_templates_dir": any(part.lower() in {"templates", "template"} for path in iter_source_files(root) for part in path.parts),
        "jinja_or_django_markers": bool(re.search(r"{{.*?}}|{%.*?%}|\breverse\(|\burl_for\(", joined, re.DOTALL)),
        "script_tags": bool(re.search(r"<script\b", joined, re.IGNORECASE)),
        "spa_framework": any(name in deps for name in ("react", "vue", "svelte", "@angular/core", "vite", "next", "nuxt")),
        "api_fetch": bool(re.search(r"\b(fetch|axios)\s*(?:\(|\.)", joined)),
        "plain_dom": bool(re.search(r"\b(querySelector|getElementById|addEventListener|window\.)", joined)),
    }
    kind = "unknown"
    confidence = 0.2
    if signals["has_templates_dir"] or signals["jinja_or_django_markers"]:
        kind = "templated_monolith"
        confidence = 0.85
    elif signals["has_package_json"] and signals["has_python"] and (signals["spa_framework"] or signals["api_fetch"]):
        kind = "spa_api"
        confidence = 0.8
    elif signals["has_html"] and signals["script_tags"] and (signals["plain_dom"] or signals["has_css"]):
        kind = "vanilla"
        confidence = 0.75
    elif signals["has_python"]:
        kind = "python"
        confidence = 0.65
    return {"check": "salvage_topology", "schema_version": 1, "passed": kind != "unknown", "root": str(root.resolve()), "topology": kind, "confidence": confidence, "signals": signals}


def cmd_topology(args: argparse.Namespace) -> int:
    try:
        result = detect_topology(Path(args.target))
    except Exception as exc:
        result = {"check": "salvage_topology", "schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "violations": [violation("topology_error", str(exc))]}
    return emit(result, args.output)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def capture_file_item(root: Path, path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"type": "file", "name": rel_path(root, path), "path": rel_path(root, path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def capture_css_item(root: Path, path: Path) -> dict[str, Any]:
    rules = web_checks.parse_css_rules(path)
    text = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    return {"type": "css_rules", "name": rel_path(root, path), "path": rel_path(root, path), "sha256": sha256_text(text), "metadata": {"rule_count": len(rules)}}


def capture_http_item(url: str) -> dict[str, Any]:
    req = Request(url, method="GET", headers={"User-Agent": "MAW-salvage-characterizer/1"})
    with urlopen(req, timeout=10) as response:
        body = response.read()
        headers = sorted((key.lower(), value) for key, value in response.headers.items())
        headers_text = json.dumps(headers, sort_keys=True, separators=(",", ":"))
        return {
            "type": "http",
            "name": url,
            "url": url,
            "method": "GET",
            "status": int(getattr(response, "status", response.getcode())),
            "sha256": hashlib.sha256(body).hexdigest(),
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "headers_sha256": sha256_text(headers_text),
            "bytes": len(body),
        }


def run_test_digest(cmd: str, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    text = completed.stdout or ""
    return {"type": "test_digest", "name": cmd, "sha256": sha256_text(f"{completed.returncode}\n{text}"), "metadata": {"returncode": completed.returncode, "output_sha256": sha256_text(text)}}


def characterize_target(target: str, root: Path | None = None, test_cmd: str | None = None) -> dict[str, Any]:
    is_url = target.startswith(("http://", "https://"))
    base = (root or Path(target)).resolve() if not is_url else (root or Path(".")).resolve()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    if is_url:
        try:
            items.append(capture_http_item(target))
        except (OSError, URLError) as exc:
            errors.append(str(exc))
    else:
        path = Path(target).resolve()
        source_files = iter_source_files(path, {".html", ".htm", ".jinja", ".jinja2", ".j2", ".css"})
        for source in source_files:
            try:
                if source.suffix.lower() == ".css":
                    items.append(capture_css_item(path if path.is_dir() else path.parent, source))
                else:
                    items.append(capture_file_item(path if path.is_dir() else path.parent, source))
            except Exception as exc:
                errors.append(f"{source}: {exc}")
    if test_cmd:
        try:
            items.append(run_test_digest(test_cmd, base))
        except Exception as exc:
            errors.append(f"test command failed to capture: {exc}")
    return {
        "check": "salvage_characterization",
        "schema_version": 1,
        "passed": not errors,
        "target": target,
        "root": str(base),
        "captured_at_epoch": time.time(),
        "items": sorted(items, key=lambda item: (item.get("type", ""), item.get("name", ""))),
        "test_command": test_cmd or "",
        "errors": errors,
    }


def compare_characterizations(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_items = {(str(item.get("type")), str(item.get("name"))): item for item in baseline.get("items", []) if isinstance(item, dict)}
    current_items = {(str(item.get("type")), str(item.get("name"))): item for item in current.get("items", []) if isinstance(item, dict)}
    diffs: list[dict[str, Any]] = []
    for key in sorted(set(baseline_items) | set(current_items)):
        before = baseline_items.get(key)
        after = current_items.get(key)
        if before is None:
            diffs.append({"type": "unexpected_item", "item": {"type": key[0], "name": key[1]}})
        elif after is None:
            diffs.append({"type": "missing_item", "item": {"type": key[0], "name": key[1]}})
        elif before.get("sha256") != after.get("sha256"):
            diffs.append({"type": "item_drift", "item": {"type": key[0], "name": key[1]}, "before_sha256": before.get("sha256"), "after_sha256": after.get("sha256")})
    return diffs


def cmd_characterize(args: argparse.Namespace) -> int:
    try:
        result = characterize_target(args.target, Path(args.root) if args.root else None, args.test_cmd)
    except Exception as exc:
        result = {"check": "salvage_characterization", "schema_version": 1, "passed": False, "target": args.target, "items": [], "errors": [str(exc)]}
    return emit(result, args.output)


def dependency_coverage_ids(path: str | None) -> set[str]:
    if not path:
        return set()
    data = load_json(path)
    if isinstance(data, list):
        return {str(item) for item in data}
    if not isinstance(data, dict):
        return set()
    ids = set(as_str_list(data.get("covered_dependencies")))
    ids.update(str(item.get("id")) for item in data.get("tests", []) if isinstance(item, dict) and item.get("id"))
    ids.update(str(item.get("dependency_id")) for item in data.get("tests", []) if isinstance(item, dict) and item.get("dependency_id"))
    return ids


def stable_dep_id(kind: str, frm: str, to: str) -> str:
    digest = hashlib.sha256(f"{kind}\0{frm}\0{to}".encode("utf-8")).hexdigest()[:12]
    return f"dep-{digest}"


def import_cycles(graph: dict[str, Any]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {}
    modules = {str(item.get("id")) for item in graph.get("modules", []) if isinstance(item, dict)}
    for edge in edge_list(graph):
        if edge.get("type") != "import":
            continue
        frm = symbol_module(str(edge.get("from")), {})
        to = str(edge.get("to", "")).split(":", 1)[0]
        if frm in modules and to in modules:
            adjacency.setdefault(frm, set()).add(to)

    cycles: set[tuple[str, ...]] = set()

    def visit(start: str, current: str, path: list[str]) -> None:
        for nxt in adjacency.get(current, set()):
            if nxt == start:
                cycle = path[:]
                smallest = min(range(len(cycle)), key=lambda index: cycle[index])
                rotated = tuple(cycle[smallest:] + cycle[:smallest])
                cycles.add(rotated)
            elif nxt not in path:
                visit(start, nxt, [*path, nxt])

    for module in sorted(modules):
        visit(module, module, [module])
    return [list(cycle) for cycle in sorted(cycles)]


def hidden_couplings(graph: dict[str, Any]) -> list[dict[str, Any]]:
    symbols = symbol_map(graph)
    couplings: list[dict[str, Any]] = []
    for edge in edge_list(graph):
        kind = str(edge.get("type", ""))
        frm = str(edge.get("from", ""))
        to = str(edge.get("to", ""))
        hidden = kind in EDGE_COUPLINGS
        if kind == "write_global" and symbol_module(frm, symbols) != symbol_module(to, symbols):
            hidden = True
        if not hidden:
            continue
        dep_id = stable_dep_id(kind, frm, to)
        couplings.append({"id": dep_id, "kind": kind, "from": frm, "to": to, "edge": edge})
    for cycle in import_cycles(graph):
        dep_id = stable_dep_id("import_cycle", "->".join(cycle), cycle[0] if cycle else "")
        couplings.append({"id": dep_id, "kind": "import_cycle", "from": cycle[0] if cycle else "", "to": cycle[-1] if cycle else "", "cycle": cycle})
    return sorted(couplings, key=lambda item: (item["kind"], item["from"], item["to"], item["id"]))


def check_hidden_deps(graph: dict[str, Any], root: Path, coverage_path: str | None = None) -> dict[str, Any]:
    text = source_text(root)
    covered = dependency_coverage_ids(coverage_path)
    couplings = hidden_couplings(graph)
    violations: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    for coupling in couplings:
        documented = f"MAW-DEP[{coupling['id']}]" in text
        covered_by_test = coupling["id"] in covered
        item = dict(coupling)
        item.update({"documented": documented, "covered_by_test": covered_by_test})
        checked.append(item)
        if not documented:
            violations.append(violation("undocumented_hidden_dependency", "hidden dependency lacks MAW-DEP annotation", dependency_id=coupling["id"], coupling=coupling))
        if not covered_by_test:
            violations.append(violation("untested_hidden_dependency", "hidden dependency lacks covering test evidence", dependency_id=coupling["id"], coupling=coupling))
    return {"check": "salvage_hidden_deps", "schema_version": 1, "passed": not violations, "couplings": checked, "violations": violations}


def cmd_hidden_deps(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        result = check_hidden_deps(graph, Path(args.root), args.coverage)
    except Exception as exc:
        result = {"check": "salvage_hidden_deps", "schema_version": 1, "passed": False, "status": "invalid", "couplings": [], "violations": [violation("hidden_deps_error", str(exc))]}
    return emit(result, args.output)


def selector_tokens_from_graph(graph: dict[str, Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {"ids": [], "classes": [], "data": [], "routes": [], "assets": [], "fields": []}
    for symbol in graph.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        kind = str(symbol.get("kind", ""))
        name = str(symbol.get("name", ""))
        selector = str(symbol.get("selector", name))
        if kind in {"dom", "css_selector"}:
            for match in re.findall(r"#([A-Za-z0-9_-]+)", selector):
                values["ids"].append(match)
            for match in re.findall(r"\.([A-Za-z0-9_-]+)", selector):
                values["classes"].append(match)
            for match in re.findall(r"\[(data-[A-Za-z0-9_-]+)(?:=([^\]]+))?\]", selector):
                values["data"].append("=".join(part.strip("'\"") for part in match if part))
        elif kind == "route":
            values["routes"].append(name)
        elif kind == "asset":
            values["assets"].append(name)
        elif kind == "form_field":
            values["fields"].append(name)
    return {key: sorted(set(item for item in items if item)) for key, items in values.items()}


def dismissed_couplings(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = load_json(path)
    result: dict[str, str] = {}
    if isinstance(data, dict):
        raw = data.get("dismissed_couplings", {})
        if isinstance(raw, dict):
            result.update({str(key): str(value) for key, value in raw.items()})
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id"):
                    result[str(item["id"])] = str(item.get("justification", ""))
    return result


def coupling_covered_ids(path: str | None) -> set[str]:
    covered = dependency_coverage_ids(path)
    if not path:
        return covered
    data = load_json(path)
    if isinstance(data, dict):
        covered.update(as_str_list(data.get("covered_couplings")))
    return covered


def detect_cross_language_couplings(graph: dict[str, Any], root: Path, coverage_path: str | None = None) -> dict[str, Any]:
    tokens = selector_tokens_from_graph(graph)
    text_by_suffix: dict[str, str] = {}
    for suffixes_name, suffixes in {
        "py": {".py"},
        "js_ts": {".js", ".jsx", ".ts", ".tsx"},
        "html": {".html", ".htm", ".jinja", ".jinja2", ".j2"},
        "css": {".css"},
    }.items():
        parts = []
        for path in iter_source_files(root, suffixes):
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                pass
        text_by_suffix[suffixes_name] = "\n".join(parts)
    candidates: list[dict[str, Any]] = []

    def add(kind: str, token: str, left: str, right: str, confidence: float) -> None:
        cid = stable_dep_id(kind, f"{left}:{token}", right)
        candidates.append({"id": cid, "kind": kind, "token": token, "left": left, "right": right, "confidence": confidence})

    for token in tokens["ids"] + tokens["classes"] + tokens["data"]:
        pattern = re.escape(token)
        if re.search(pattern, text_by_suffix["js_ts"]) and (re.search(pattern, text_by_suffix["html"]) or re.search(pattern, text_by_suffix["css"])):
            add("dom_selector", token, "js_ts", "html_css", 0.75)
    for route in tokens["routes"]:
        if route and (route in text_by_suffix["py"] or route in text_by_suffix["js_ts"]):
            add("route_name", route, "template", "backend_or_client", 0.7)
    for field in tokens["fields"]:
        if field and re.search(r"\b(request\.form|POST|FormData|get\(['\"]" + re.escape(field) + r")", text_by_suffix["py"] + text_by_suffix["js_ts"]):
            add("form_field", field, "html", "backend_or_client", 0.7)
    endpoint_re = re.compile(r"['\"](?P<path>/api/[A-Za-z0-9_./:-]+)['\"]")
    py_routes = set(match.group("path") for match in endpoint_re.finditer(text_by_suffix["py"]))
    client_routes = set(match.group("path") for match in endpoint_re.finditer(text_by_suffix["js_ts"]))
    for route in sorted(py_routes & client_routes):
        add("api_route", route, "backend", "client", 0.85)
    for asset in tokens["assets"]:
        if asset and (asset in text_by_suffix["html"] or asset in text_by_suffix["css"]):
            add("asset_path", asset, "html_css", "asset", 0.65)
    for edge in edge_list(graph):
        kind = str(edge.get("type", ""))
        if kind in WEB_EDGE_COUPLINGS:
            add(kind, str(edge.get("to", "")), str(edge.get("from", "")), "graph", 0.6)

    documented_text = source_text(root)
    covered = coupling_covered_ids(coverage_path)
    dismissed = dismissed_couplings(coverage_path)
    checked = []
    violations: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (item["kind"], item["token"], item["id"])):
        documented = f"MAW-DEP[{candidate['id']}]" in documented_text
        covered_by_test = candidate["id"] in covered
        dismissal = dismissed.get(candidate["id"], "")
        dismissed_ok = bool(dismissal.strip())
        item = dict(candidate)
        item.update({"documented": documented, "covered_by_test": covered_by_test, "dismissed": candidate["id"] in dismissed, "justification": dismissal})
        checked.append(item)
        if item["dismissed"]:
            if not dismissed_ok:
                violations.append(violation("cross_language_coupling_dismissed_without_justification", "dismissed coupling requires a recorded justification", coupling_id=candidate["id"], coupling=candidate))
            continue
        if not documented:
            violations.append(violation("undocumented_cross_language_coupling", "cross-language coupling lacks MAW-DEP annotation", coupling_id=candidate["id"], coupling=candidate))
        if not covered_by_test:
            violations.append(violation("untested_cross_language_coupling", "cross-language coupling lacks behavioral test evidence", coupling_id=candidate["id"], coupling=candidate))
    return {"check": "salvage_cross_lang", "schema_version": 1, "passed": not violations, "couplings": checked, "violations": violations}


def cmd_cross_lang(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        result = detect_cross_language_couplings(graph, Path(args.root), args.coverage)
    except Exception as exc:
        result = {"check": "salvage_cross_lang", "schema_version": 1, "passed": False, "status": "invalid", "couplings": [], "violations": [violation("cross_lang_error", str(exc))]}
    return emit(result, args.output)


def declared_removed(path: str | None, graph: dict[str, Any]) -> list[str]:
    removed = [str(item.get("id")) for item in graph.get("symbols", []) if isinstance(item, dict) and item.get("status") == "removed" and item.get("id")]
    if not path:
        return sorted(set(removed))
    data = load_json(path)
    if isinstance(data, list):
        removed.extend(str(item) if isinstance(item, str) else str(item.get("id")) for item in data if isinstance(item, (str, dict)))
    elif isinstance(data, dict):
        removed.extend(as_str_list(data.get("removed_symbols")))
        removed.extend(str(item.get("id")) for item in data.get("symbols", []) if isinstance(item, dict) and item.get("id"))
    return sorted(set(item for item in removed if item and item != "None"))


def reachable_symbols(graph: dict[str, Any], entrypoints: list[str]) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in edge_list(graph):
        if edge.get("type") in TRAVERSAL_EDGES:
            adjacency.setdefault(str(edge.get("from")), set()).add(str(edge.get("to")))
    seen = set(entrypoints)
    stack = list(entrypoints)
    while stack:
        current = stack.pop()
        for nxt in adjacency.get(current, set()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def check_dead_code(graph: dict[str, Any], removed: list[str], frozen_entrypoints: list[str]) -> dict[str, Any]:
    reachable = reachable_symbols(graph, frozen_entrypoints)
    violations: list[dict[str, Any]] = []
    live_removed = sorted(set(removed) & reachable)
    for symbol in live_removed:
        violations.append(violation("removed_symbol_reachable", "symbol slated for removal is reachable from preserved surface", symbol=symbol))
    referenced = []
    for edge in edge_list(graph):
        if str(edge.get("to")) in removed and str(edge.get("from")) in reachable:
            referenced.append(edge)
            violations.append(violation("removed_symbol_referenced_by_kept_symbol", "removed symbol is still referenced by kept reachable code", symbol=str(edge.get("to")), edge=edge))
    return {
        "check": "salvage_dead_code",
        "schema_version": 1,
        "passed": not violations,
        "removed_symbols": sorted(removed),
        "proof": {"entrypoints": sorted(frozen_entrypoints), "reachable": sorted(reachable), "referencing_edges": referenced},
        "violations": violations,
    }


def cmd_dead_code(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        surface = load_json_object(args.preserved_surface)
        removed = declared_removed(args.removed, graph)
        result = check_dead_code(graph, removed, surface_entrypoints(surface))
    except Exception as exc:
        result = {"check": "salvage_dead_code", "schema_version": 1, "passed": False, "status": "invalid", "removed_symbols": [], "proof": {}, "violations": [violation("dead_code_error", str(exc))]}
    return emit(result, args.output)


def shingles(tokens: list[str], size: int = 5) -> set[tuple[str, ...]]:
    if len(tokens) < size:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[index : index + size]) for index in range(0, len(tokens) - size + 1)}


def similarity(a: list[str], b: list[str]) -> float:
    left = shingles(a)
    right = shingles(b)
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def duplicate_candidates(graph: dict[str, Any], threshold: float) -> list[dict[str, Any]]:
    symbols = [item for item in graph.get("symbols", []) if isinstance(item, dict) and item.get("kind") in {"function", "method"}]
    groups: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    by_hash: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        digest = str(symbol.get("normalized_body_hash", ""))
        if digest:
            by_hash.setdefault(digest, []).append(symbol)
    for digest, items in by_hash.items():
        if len(items) > 1:
            groups.append({"kind": "body_hash", "score": 1.0, "body_hash": digest, "symbols": sorted(str(item["id"]) for item in items)})
            for left in items:
                for right in items:
                    if left is not right:
                        seen_pairs.add(tuple(sorted((str(left["id"]), str(right["id"])))))
    for index, left in enumerate(symbols):
        for right in symbols[index + 1 :]:
            pair = tuple(sorted((str(left["id"]), str(right["id"]))))
            if pair in seen_pairs:
                continue
            score = similarity(as_str_list(left.get("token_signature")), as_str_list(right.get("token_signature")))
            if score >= threshold:
                groups.append({"kind": "token_shingle", "score": round(score, 6), "symbols": list(pair)})
    return sorted(groups, key=lambda item: (item["kind"], item["symbols"]))


def load_duplication_plan(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {"groups": data if isinstance(data, list) else []}


def incoming_callers(graph: dict[str, Any], target: str) -> list[str]:
    return sorted(str(edge.get("from")) for edge in edge_list(graph) if edge.get("type") == "call" and str(edge.get("to")) == target)


def check_duplication(graph: dict[str, Any], plan: dict[str, Any], threshold: float) -> dict[str, Any]:
    candidates = duplicate_candidates(graph, threshold)
    symbol_ids = {str(item.get("id")) for item in graph.get("symbols", []) if isinstance(item, dict)}
    declared_groups = [item for item in plan.get("groups", []) if isinstance(item, dict)] if isinstance(plan.get("groups"), list) else []
    violations: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []

    for candidate in candidates:
        symbols = set(candidate["symbols"])
        match = next((group for group in declared_groups if symbols <= set(as_str_list(group.get("duplicates")) + [str(group.get("survivor", ""))])), None)
        if match is None:
            violations.append(violation("undeclared_duplicate_logic", "duplicate logic lacks declared survivor/reroute proof", duplicate_group=candidate))
            continue
        survivor = str(match.get("survivor", ""))
        duplicates = sorted(set(as_str_list(match.get("duplicates"))) - {survivor})
        if not survivor or survivor not in symbol_ids:
            violations.append(violation("duplicate_survivor_missing", "declared duplicate survivor is missing", survivor=survivor, duplicate_group=candidate))
        surviving = sorted(symbol for symbol in duplicates if symbol in symbol_ids)
        if surviving:
            violations.append(violation("duplicate_symbol_survived", "former duplicate logic still exists", duplicates=surviving, survivor=survivor))
        survivor_callers = incoming_callers(graph, survivor)
        rerouted = sorted(set(as_str_list(match.get("rerouted_call_sites")) + survivor_callers))
        if not rerouted:
            violations.append(violation("duplicate_calls_not_rerouted", "no rerouted call sites prove traffic reaches the survivor", survivor=survivor))
        verified.append({"candidate": candidate, "survivor": survivor, "duplicates": duplicates, "rerouted_call_sites": rerouted})

    for group in declared_groups:
        survivor = str(group.get("survivor", ""))
        duplicates = sorted(set(as_str_list(group.get("duplicates"))) - {survivor})
        if not survivor or survivor not in symbol_ids:
            violations.append(violation("duplicate_survivor_missing", "declared duplicate survivor is missing", survivor=survivor))
        surviving = sorted(symbol for symbol in duplicates if symbol in symbol_ids)
        if surviving:
            violations.append(violation("duplicate_symbol_survived", "former duplicate logic still exists", duplicates=surviving, survivor=survivor))
        if survivor in symbol_ids and not (as_str_list(group.get("rerouted_call_sites")) or incoming_callers(graph, survivor)):
            violations.append(violation("duplicate_calls_not_rerouted", "declared collapse lacks survivor call-site proof", survivor=survivor))

    return {"check": "salvage_duplication", "schema_version": 1, "passed": not violations, "duplicates": candidates, "verified_groups": verified, "violations": violations}


def cmd_duplication(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        plan = load_duplication_plan(args.plan)
        result = check_duplication(graph, plan, float(args.threshold))
    except Exception as exc:
        result = {"check": "salvage_duplication", "schema_version": 1, "passed": False, "status": "invalid", "duplicates": [], "verified_groups": [], "violations": [violation("duplication_error", str(exc))]}
    return emit(result, args.output)


def mutate_graph_for_hidden_dep(graph: dict[str, Any]) -> dict[str, Any]:
    mutant = json.loads(json.dumps(graph))
    symbols = [item for item in mutant.get("symbols", []) if isinstance(item, dict)]
    frm = str(symbols[0]["id"]) if symbols else "module:entry"
    to = str(symbols[-1]["id"]) if symbols else "module:GLOBAL"
    mutant.setdefault("edges", []).append({"type": "write_global", "from": frm, "to": to, "location": {"path": "mutant.py", "line": 1}})
    return mutant


def mutate_graph_for_dead_ref(graph: dict[str, Any], removed: list[str]) -> dict[str, Any]:
    mutant = json.loads(json.dumps(graph))
    entrypoints = graph_entrypoints(mutant) or ["module:entry"]
    target = removed[0] if removed else "module:removed"
    if target not in {str(item.get("id")) for item in mutant.get("symbols", []) if isinstance(item, dict)}:
        mutant.setdefault("symbols", []).append({"id": target, "module_id": target.split(":", 1)[0], "name": target.rsplit(":", 1)[-1], "qualname": target, "kind": "function"})
    mutant.setdefault("edges", []).append({"type": "call", "from": entrypoints[0], "to": target, "location": {"path": "mutant.py", "line": 2}})
    return mutant


def mutate_graph_for_duplicate(graph: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    mutant = json.loads(json.dumps(graph))
    functions = [item for item in mutant.get("symbols", []) if isinstance(item, dict) and item.get("kind") in {"function", "method"} and item.get("normalized_body_hash")]
    if not functions:
        survivor = {"id": "module:survivor", "module_id": "module", "name": "survivor", "qualname": "survivor", "kind": "function", "normalized_body_hash": "abc", "token_signature": ["return", "1"]}
        functions = [survivor]
        mutant.setdefault("symbols", []).append(survivor)
    original = functions[0]
    duplicate = dict(original)
    duplicate["id"] = str(original["id"]) + "__duplicate"
    duplicate["name"] = str(original.get("name", "symbol")) + "_duplicate"
    duplicate["qualname"] = str(original.get("qualname", "symbol")) + "_duplicate"
    mutant.setdefault("symbols", []).append(duplicate)
    return mutant, {"groups": [{"survivor": original["id"], "duplicates": [duplicate["id"]], "rerouted_call_sites": []}]}


def behavior_mutation_caught(baseline_path: str | None) -> bool:
    if not baseline_path:
        return False
    baseline = load_json_object(baseline_path)
    if baseline.get("check") == "salvage_characterization":
        current = json.loads(json.dumps(baseline))
        items = current.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            items[0]["sha256"] = "salvage-mutated"
        else:
            current["items"] = [{"type": "file", "name": "mutant", "sha256": "changed"}]
        return bool(compare_characterizations(baseline, current))
    current = json.loads(json.dumps(baseline))
    items = current.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        item_type = str(items[0].get("type", ""))
        fields = behavior_baseline.COMPARE_FIELDS.get(item_type, ())
        if fields:
            field = fields[0]
            items[0][field] = f"{items[0].get(field)}__salvage_mutation"
        else:
            items[0]["type"] = "json"
            items[0]["sha256"] = "changed"
    else:
        current["items"] = [{"type": "json", "name": "mutant", "sha256": "changed"}]
    return bool(behavior_baseline.compare_snapshots(baseline, current))


def surface_shrink_caught(surface: dict[str, Any]) -> bool:
    entries = surface_entrypoints(surface)
    if not entries:
        surface = dict(surface)
        surface["entrypoints"] = ["module:entry"]
        surface["entrypoints_before"] = ["module:entry", "module:other"]
    else:
        surface = dict(surface)
        surface["entrypoints_before"] = [*entries, "module:removed_from_surface"]
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp)
        (run / "artifacts").mkdir()
        path = run / SURFACE
        sha = run / SURFACE_SHA
        path.write_text(json.dumps(surface, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sha.write_text(sha256_file(path) + "\n", encoding="utf-8")
        return check_surface_freeze(run)["passed"] is False


def mutate_graph_for_cross_lang(graph: dict[str, Any]) -> dict[str, Any]:
    mutant = json.loads(json.dumps(graph))
    module = "html:mutant.html"
    mutant.setdefault("modules", []).append({"id": module, "path": "mutant.html", "language": "html"})
    mutant.setdefault("symbols", []).append({"id": "dom:#maw-mutant:1", "module_id": module, "name": "#maw-mutant", "qualname": "#maw-mutant", "kind": "dom", "selector": "#maw-mutant", "exported": True})
    mutant.setdefault("edges", []).append({"type": "dom_ref", "from": module, "to": "dom:#maw-mutant:1", "location": {"path": "mutant.html", "line": 1}})
    return mutant


def check_resistance(graph: dict[str, Any], surface: dict[str, Any], removed: list[str], duplication_plan: dict[str, Any], root: Path, coverage: str | None, baseline: str | None) -> dict[str, Any]:
    clean = {
        "hidden-deps": check_hidden_deps(graph, root, coverage),
        "dead-code": check_dead_code(graph, removed, surface_entrypoints(surface)),
        "duplication": check_duplication(graph, duplication_plan, 0.8),
        "cross-lang": detect_cross_language_couplings(graph, root, coverage),
    }
    mutations: list[dict[str, Any]] = []
    hidden = check_hidden_deps(mutate_graph_for_hidden_dep(graph), root, coverage)
    mutations.append({"name": "reintroduced_hidden_dependency", "planted": True, "caught": hidden["passed"] is False, "mutant_passed": hidden["passed"], "failed_checks": [item["type"] for item in hidden["violations"]]})
    dead = check_dead_code(mutate_graph_for_dead_ref(graph, removed), removed or ["module:removed"], surface_entrypoints(surface))
    mutations.append({"name": "resurrected_dead_reference", "planted": True, "caught": dead["passed"] is False, "mutant_passed": dead["passed"], "failed_checks": [item["type"] for item in dead["violations"]]})
    dup_graph, dup_plan = mutate_graph_for_duplicate(graph)
    duplicate = check_duplication(dup_graph, dup_plan, 0.8)
    mutations.append({"name": "reduplicated_function", "planted": True, "caught": duplicate["passed"] is False, "mutant_passed": duplicate["passed"], "failed_checks": [item["type"] for item in duplicate["violations"]]})
    behavior_caught = behavior_mutation_caught(baseline)
    mutations.append({"name": "server_preserved_surface_behavior_break", "planted": bool(baseline), "caught": behavior_caught, "mutant_passed": not behavior_caught, "failed_checks": ["preserved_surface_behavior_drift"] if behavior_caught else []})
    mutations.append({"name": "client_preserved_surface_behavior_break", "planted": bool(baseline), "caught": behavior_caught, "mutant_passed": not behavior_caught, "failed_checks": ["preserved_surface_behavior_drift"] if behavior_caught else []})
    cross = detect_cross_language_couplings(mutate_graph_for_cross_lang(graph), root, coverage)
    mutations.append({"name": "broken_cross_language_coupling", "planted": True, "caught": cross["passed"] is False, "mutant_passed": cross["passed"], "failed_checks": [item["type"] for item in cross["violations"]]})
    shrink_caught = surface_shrink_caught(surface)
    mutations.append({"name": "surface_shrink_gaming", "planted": True, "caught": shrink_caught, "mutant_passed": not shrink_caught, "failed_checks": ["preserved_surface_shrank"] if shrink_caught else []})
    caught = sum(1 for item in mutations if item["caught"] is True)
    clean_passed = all(item.get("passed") is True for item in clean.values())
    violations = []
    if not clean_passed:
        violations.append(violation("clean_salvage_gates_must_pass_before_resistance", "clean salvage gates must pass before resistance is trusted", clean=clean))
    for item in mutations:
        if item["caught"] is not True:
            violations.append(violation("salvage_mutation_escaped", "planted salvage defect escaped its gate", mutation=item["name"]))
    return {
        "check": "salvage_resistance",
        "schema_version": 1,
        "passed": not violations,
        "clean": clean,
        "mutations": mutations,
        "summary": {"total": len(mutations), "caught": caught},
        "violations": violations,
    }


def cmd_resistance(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        surface = load_json_object(args.preserved_surface)
        removed = declared_removed(args.removed, graph)
        plan = load_duplication_plan(args.duplication_plan)
        result = check_resistance(graph, surface, removed, plan, Path(args.root), args.coverage, args.baseline)
    except Exception as exc:
        result = {"check": "salvage_resistance", "schema_version": 1, "passed": False, "status": "invalid", "mutations": [], "summary": {"total": 0, "caught": 0}, "violations": [violation("resistance_error", str(exc))]}
    return emit(result, args.output)


def artifact_pass(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    try:
        data = load_json(path)
    except Exception as exc:
        return False, str(exc)
    if not isinstance(data, dict):
        return False, "artifact must be an object"
    return data.get("passed") is True, "passed is true" if data.get("passed") is True else "passed is false"


def check_verdict(run_dir: Path) -> dict[str, Any]:
    graph = maybe_load_graph(run_dir)
    dead = load_json_object(run_dir / DEAD_CODE) if (run_dir / DEAD_CODE).is_file() else None
    freeze = check_surface_freeze(run_dir, graph, dead)
    gates = [TOPOLOGY, CHARACTERIZATION_BASELINE, PRESERVE_PARITY, HIDDEN_DEPS, CROSS_LANG, DEAD_CODE, DUPLICATION, RESISTANCE]
    items = []
    violations = list(freeze["violations"])
    for artifact in gates:
        path = run_dir / artifact
        passed, reason = artifact_pass(path)
        items.append({"artifact": artifact, "passed": passed, "reason": reason})
        if not passed:
            violations.append(violation("failing_salvage_gate", "salvage gate artifact did not pass", artifact=artifact, reason=reason))
    passed = not violations
    return {"check": "salvage_result", "schema_version": 1, "passed": passed, "verdict": "SHIP" if passed else "NO-SHIP", "freeze": freeze, "gates": items, "violations": violations}


def cmd_verdict(args: argparse.Namespace) -> int:
    result = check_verdict(Path(args.run))
    return emit(result, args.output or str(Path(args.run) / RESULT))


def check_run(run_dir: Path) -> dict[str, Any]:
    applicable = any((run_dir / artifact).exists() for artifact in (SURFACE, SURFACE_SHA, CODE_GRAPH, CHARACTERIZATION_BASELINE, CROSS_LANG, RESULT))
    if not applicable:
        return {"check": "salvage_hard_gates", "applicable": False, "passed": True, "violations": [], "reason": "no salvage preserved-surface artifacts"}
    graph = maybe_load_graph(run_dir)
    dead = load_json_object(run_dir / DEAD_CODE) if (run_dir / DEAD_CODE).is_file() else None
    freeze = check_surface_freeze(run_dir, graph, dead)
    result_path = run_dir / RESULT
    violations = list(freeze["violations"])
    baseline_path = run_dir / CHARACTERIZATION_BASELINE
    if not baseline_path.is_file():
        violations.append(violation("missing_characterization_baseline", "salvage parity requires a pre-gut characterization baseline", artifact=CHARACTERIZATION_BASELINE))
    else:
        try:
            baseline = load_json_object(baseline_path)
            if baseline.get("check") != "salvage_characterization" or not baseline.get("items"):
                violations.append(violation("invalid_characterization_baseline", "characterization baseline is empty or invalid", artifact=CHARACTERIZATION_BASELINE))
        except Exception as exc:
            violations.append(violation("invalid_characterization_baseline", str(exc), artifact=CHARACTERIZATION_BASELINE))
    cross_path = run_dir / CROSS_LANG
    if cross_path.is_file():
        try:
            cross = load_json_object(cross_path)
            for item in cross.get("couplings", []):
                if isinstance(item, dict) and item.get("dismissed") and not str(item.get("justification", "")).strip():
                    violations.append(violation("cross_language_coupling_dismissed_without_justification", "dismissed coupling requires justification", artifact=CROSS_LANG, coupling_id=item.get("id")))
        except Exception as exc:
            violations.append(violation("invalid_cross_language_artifact", str(exc), artifact=CROSS_LANG))
    if result_path.is_file():
        result = load_json_object(result_path)
        if result.get("passed") is not True:
            violations.append(violation("salvage_result_failed", "salvage-result.json reports failed", artifact=RESULT))
    return {"check": "salvage_hard_gates", "applicable": True, "passed": not violations, "freeze": freeze, "violations": violations}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic salvage refactor gates.")
    sub = parser.add_subparsers(dest="command", required=True)

    topology = sub.add_parser("topology")
    topology.add_argument("target")
    topology.add_argument("--output", required=True)
    topology.set_defaults(func=cmd_topology)

    characterize = sub.add_parser("characterize")
    characterize.add_argument("target")
    characterize.add_argument("--root")
    characterize.add_argument("--test-cmd")
    characterize.add_argument("--output", required=True)
    characterize.set_defaults(func=cmd_characterize)

    parity = sub.add_parser("preserve-parity")
    parity.add_argument("--manifest")
    parity.add_argument("--baseline")
    parity.add_argument("--characterization-baseline")
    parity.add_argument("--target")
    parity.add_argument("--test-cmd")
    parity.add_argument("--preserved-surface", required=True)
    parity.add_argument("--root", default=".")
    parity.add_argument("--run")
    parity.add_argument("--output", required=True)
    parity.set_defaults(func=cmd_preserve_parity)

    hidden = sub.add_parser("hidden-deps")
    hidden.add_argument("--graph", required=True)
    hidden.add_argument("--root", default=".")
    hidden.add_argument("--coverage")
    hidden.add_argument("--output", required=True)
    hidden.set_defaults(func=cmd_hidden_deps)

    cross = sub.add_parser("cross-lang")
    cross.add_argument("--graph", required=True)
    cross.add_argument("--root", default=".")
    cross.add_argument("--coverage")
    cross.add_argument("--output", required=True)
    cross.set_defaults(func=cmd_cross_lang)

    dead = sub.add_parser("dead-code")
    dead.add_argument("--graph", required=True)
    dead.add_argument("--preserved-surface", required=True)
    dead.add_argument("--removed")
    dead.add_argument("--output", required=True)
    dead.set_defaults(func=cmd_dead_code)

    duplication = sub.add_parser("duplication")
    duplication.add_argument("--graph", required=True)
    duplication.add_argument("--plan")
    duplication.add_argument("--threshold", type=float, default=0.8)
    duplication.add_argument("--output", required=True)
    duplication.set_defaults(func=cmd_duplication)

    resistance = sub.add_parser("resistance")
    resistance.add_argument("--graph", required=True)
    resistance.add_argument("--preserved-surface", required=True)
    resistance.add_argument("--removed")
    resistance.add_argument("--duplication-plan")
    resistance.add_argument("--coverage")
    resistance.add_argument("--baseline")
    resistance.add_argument("--root", default=".")
    resistance.add_argument("--output", required=True)
    resistance.set_defaults(func=cmd_resistance)

    verdict = sub.add_parser("verdict", aliases=["aggregate"])
    verdict.add_argument("run")
    verdict.add_argument("--output")
    verdict.set_defaults(func=cmd_verdict)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
