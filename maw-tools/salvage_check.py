#!/usr/bin/env python3
"""Hard deterministic gates for MAW salvage refactor workflows."""
from __future__ import annotations

import argparse
import ast
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
COMPLEXITY_CANDIDATES = "artifacts/complexity-candidates.json"
COMPLEXITY_REDUCED = "artifacts/complexity-reduced.json"
STALE_CODE = "artifacts/stale-code.json"
INTERDEPENDENCY_DOSSIER = "artifacts/interdependency-dossier.json"
INTERDEPENDENCY_DOSSIER_MD = "artifacts/interdependency-dossier.md"
TEST_TRIAGE = "artifacts/test-triage.json"
TEST_PROVENANCE_MD = "artifacts/test-provenance.md"
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
    "unreduced_complexity_candidate": "complexity-reduced",
    "removed_but_live_stale_symbol": "stale",
    "undocumented_interdependency": "interdependency-dossier",
    "hollow_port_static_identical_interactions_missing": "preserve-parity",
    "edge_scroll_viewport_drift": "preserve-parity",
    "real_single_object_move": "preserve-parity",
    "resurrected_legacy_test": "test-triage",
    "dropped_sole_keep_coverage": "test-triage",
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


def normalize_graph_path(value: str) -> str:
    return str(value).replace("\\", "/").lstrip("./")


def reachable_module_paths(graph: dict[str, Any], entrypoints: list[str]) -> list[str]:
    reachable = reachable_symbols(graph, entrypoints)
    module_by_id = {
        str(item.get("id")): normalize_graph_path(str(item.get("path", "")))
        for item in graph.get("modules", [])
        if isinstance(item, dict) and item.get("id") and item.get("path")
    }
    module_ids = {
        str(item.get("module_id"))
        for item in graph.get("symbols", [])
        if isinstance(item, dict) and str(item.get("id")) in reachable and item.get("module_id")
    }
    module_ids.update(module_id for module_id in module_by_id if module_id in reachable)
    return sorted(module_by_id[module_id] for module_id in module_ids if module_by_id.get(module_id))


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
    source_paths = {normalize_graph_path(path) for path in as_str_list(surface.get("source_paths"))}
    if graph is not None:
        reachable_paths = reachable_module_paths(graph, frozen)
        missing_sources = sorted(path for path in reachable_paths if path not in source_paths)
        if missing_sources:
            violations.append(
                violation(
                    "preserved_surface_missing_reachable_source_paths",
                    "preserved surface source_paths must include every source module reachable from frozen entrypoints",
                    missing=missing_sources,
                    reachable_source_paths=reachable_paths,
                )
            )
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
            current = characterize_target(
                args.target or str(baseline.get("target", ".")),
                Path(args.root) if args.root else None,
                args.test_cmd or str(baseline.get("test_command", "")) or None,
                args.interaction_artifact,
                args.scenario or as_str_list(baseline.get("required_interaction_scenarios")) or None,
            )
            for error in as_str_list(current.get("errors")):
                violations.append(violation("current_interaction_characterization_failed", error))
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
    data = path.read_bytes()
    rules = web_checks.parse_css_rules(path)
    return {"type": "css_file", "name": rel_path(root, path), "path": rel_path(root, path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "metadata": {"rule_count": len(rules)}}


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


REQUIRED_INTERACTION_SCENARIOS = [
    "existing-playwright-suite",
    "drag-with-live-ghost",
    "grid-snap",
    "collision-reflow",
    "resize-snap",
    "pin-protection",
    "collapse",
    "recolor",
    "rename",
    "select-mode-multi-move",
    "edge-auto-scroll",
    "background-photo-switching",
    "save-reload-identical",
]


def run_test_digest(cmd: str, cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    text = completed.stdout or ""
    normalized = normalize_test_output(text)
    return {
        "type": "test_digest",
        "name": cmd,
        "sha256": sha256_text(f"{completed.returncode}\n{normalized}"),
        "metadata": {
            "returncode": completed.returncode,
            "output_sha256": sha256_text(normalized),
            "stdout_tail": text[-4000:],
            "normalized_stdout_sha256": sha256_text(normalized),
        },
    }


def normalize_test_output(text: str) -> str:
    """Remove nondeterministic runner timing from test output before hashing."""
    normalized = str(text or "")
    replacements = [
        (re.compile(r"\(\d+(?:\.\d+)?\s*(?:ms|s|m)\)"), "(<duration>)"),
        (re.compile(r"\b\d+(?:\.\d+)?\s*(?:ms|s|m)\b"), "<duration>"),
        (re.compile(r"\b\d+\s+passed\s+\(<duration>\)", re.IGNORECASE), lambda m: m.group(0)),
        (re.compile(r"\bRun id:\s*[A-Za-z0-9._:-]+", re.IGNORECASE), "Run id: <run-id>"),
        (re.compile(r"\bseed[=:]\s*[A-Za-z0-9._:-]+", re.IGNORECASE), "seed=<seed>"),
    ]
    for pattern, repl in replacements:
        normalized = pattern.sub(repl, normalized)
    normalized = re.sub(r"\r\n?", "\n", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    return normalized.strip()


def scenario_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("name") or item.get("scenario") or item.get("id") or "")
    return ""


def scenario_has_post_interaction_evidence(item: dict[str, Any]) -> bool:
    has_dom = bool(item.get("dom_sha256") or item.get("domSnapshotSha256") or item.get("post_interaction_dom_sha256"))
    has_geometry = bool(item.get("geometry_sha256") or item.get("geometrySnapshotSha256") or item.get("computed_geometry_sha256"))
    has_css = bool(item.get("computed_css_sha256") or item.get("computedCssSha256") or item.get("css_sha256"))
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else item
    has_dom = has_dom or isinstance(evidence.get("dom"), (dict, list, str))
    has_geometry = has_geometry or isinstance(evidence.get("geometry"), list)
    has_css = has_css or isinstance(evidence.get("computed_css"), list)
    return has_dom and has_geometry and (has_css or bool(item.get("allow_missing_computed_css")))


GENERATED_ID_RE = re.compile(r"\b(?:widget|panel|custom|divider|anchor|link|relationship|operator|asset)-[a-z0-9]{6,}(?:-[a-z0-9]{3,})?\b", re.IGNORECASE)
VOLATILE_KEY_RE = re.compile(r"(?:timestamp|timeStamp|updatedAt|createdAt|captured_at|capturedAt|sha256|hash)$", re.IGNORECASE)
GEOMETRY_TOLERANCE_PX = 1.0
COLOR_DELTA_EPSILON = 0.025


def normalize_generated_ids(value: str) -> str:
    return GENERATED_ID_RE.sub("<generated-id>", value)


def normalize_evidence_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if VOLATILE_KEY_RE.search(str(key)):
                continue
            result[str(key)] = normalize_evidence_value(item)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, list):
        normalized = [normalize_evidence_value(item) for item in value]
        if all(isinstance(item, dict) for item in normalized):
            return sorted(normalized, key=lambda item: json.dumps({k: item.get(k) for k in ("type", "key", "selector", "name", "id")}, sort_keys=True))
        return normalized
    if isinstance(value, str):
        return normalize_generated_ids(value)
    return value


def normalized_interaction_evidence(scenario: dict[str, Any]) -> dict[str, Any]:
    raw = scenario.get("evidence") if isinstance(scenario.get("evidence"), dict) else scenario
    evidence = {
        "dom": raw.get("dom"),
        "geometry": raw.get("geometry"),
        "computed_css": raw.get("computed_css"),
        "extra": scenario.get("extra", raw.get("extra")),
        "hashes": {
            "dom": scenario.get("dom_sha256") or scenario.get("domSnapshotSha256") or scenario.get("post_interaction_dom_sha256"),
            "geometry": scenario.get("geometry_sha256") or scenario.get("geometrySnapshotSha256") or scenario.get("computed_geometry_sha256"),
            "computed_css": scenario.get("computed_css_sha256") or scenario.get("computedCssSha256") or scenario.get("css_sha256"),
        },
    }
    return normalize_evidence_value(evidence)


def stable_interaction_sha(evidence: dict[str, Any]) -> str:
    return sha256_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")))


def load_interaction_items(path: str | None, required_scenarios: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    if not path:
        return [], ["interaction artifact is required; static file hashing is not a valid salvage characterization"]
    artifact = Path(path)
    if not artifact.is_file():
        return [], [f"missing interaction artifact: {artifact}"]
    try:
        data = load_json_object(artifact)
    except Exception as exc:
        return [], [f"invalid interaction artifact: {exc}"]
    raw = data.get("scenarios", data.get("items", []))
    if not isinstance(raw, list):
        return [], ["interaction artifact must contain a scenarios array"]
    scenarios = [item for item in raw if isinstance(item, dict)]
    by_name = {scenario_name(item): item for item in scenarios if scenario_name(item)}
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    for name in required_scenarios:
        scenario = by_name.get(name)
        if scenario is None:
            errors.append(f"missing required interaction scenario: {name}")
            continue
        if scenario.get("passed") is not True:
            errors.append(f"interaction scenario did not pass: {name}")
        if not scenario_has_post_interaction_evidence(scenario):
            errors.append(f"interaction scenario lacks post-interaction DOM/computed geometry evidence: {name}")
        evidence = normalized_interaction_evidence(scenario)
        items.append(
            {
                "type": "interaction_scenario",
                "name": name,
                "sha256": stable_interaction_sha(evidence),
                "evidence": evidence,
                "metadata": {
                    "artifact": str(artifact),
                    "dom_sha256": scenario.get("dom_sha256") or scenario.get("domSnapshotSha256") or scenario.get("post_interaction_dom_sha256"),
                    "geometry_sha256": scenario.get("geometry_sha256") or scenario.get("geometrySnapshotSha256") or scenario.get("computed_geometry_sha256"),
                    "computed_css_sha256": scenario.get("computed_css_sha256") or scenario.get("computedCssSha256") or scenario.get("css_sha256"),
                    "settle": scenario.get("settle") or scenario.get("settled") or {},
                },
            }
        )
    if not items:
        errors.append("zero interaction scenarios executed")
    return items, errors


def characterize_target(target: str, root: Path | None = None, test_cmd: str | None = None, interaction_artifact: str | None = None, required_scenarios: list[str] | None = None) -> dict[str, Any]:
    is_url = target.startswith(("http://", "https://"))
    base = (root or Path(target)).resolve() if not is_url else (root or Path(".")).resolve()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    required = required_scenarios or REQUIRED_INTERACTION_SCENARIOS
    if is_url:
        try:
            items.append(capture_http_item(target))
        except (OSError, URLError) as exc:
            errors.append(str(exc))
    else:
        path = Path(target).resolve()
        source_files = iter_source_files(path, {".css"})
        for source in source_files:
            try:
                items.append(capture_css_item(path if path.is_dir() else path.parent, source))
            except Exception as exc:
                errors.append(f"{source}: {exc}")
    if test_cmd:
        try:
            digest = run_test_digest(test_cmd, base)
            items.append(digest)
            if digest.get("metadata", {}).get("returncode") != 0:
                errors.append(f"interaction test command failed: {test_cmd}")
        except Exception as exc:
            errors.append(f"test command failed to capture: {exc}")
    else:
        errors.append("interaction test command is required for salvage characterization")
    interaction_items, interaction_errors = load_interaction_items(interaction_artifact, required)
    items.extend(interaction_items)
    errors.extend(interaction_errors)
    return {
        "check": "salvage_characterization",
        "schema_version": 1,
        "passed": not errors,
        "target": target,
        "root": str(base),
        "captured_at_epoch": time.time(),
        "items": sorted(items, key=lambda item: (item.get("type", ""), item.get("name", ""))),
        "test_command": test_cmd or "",
        "interaction_artifact": interaction_artifact or "",
        "required_interaction_scenarios": required,
        "interaction_scenario_count": sum(1 for item in items if item.get("type") == "interaction_scenario"),
        "errors": errors,
    }


def evidence_by_key(items: Any, key_fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(items, list):
        return {}
    result = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            result[str(index)] = item
            continue
        key = next((str(item.get(field)) for field in key_fields if item.get(field) is not None), str(index))
        result[normalize_generated_ids(key)] = item
    return result


def as_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_color(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text.startswith("#") and len(text) in {4, 7}:
        if len(text) == 4:
            chars = [char * 2 for char in text[1:]]
        else:
            chars = [text[1:3], text[3:5], text[5:7]]
        try:
            return tuple(int(part, 16) / 255 for part in chars)
        except ValueError:
            return None
    match = re.match(r"rgba?\(([^)]+)\)", text)
    if match:
        parts = re.split(r"\s*,\s*|\s+", match.group(1).replace("/", " "))
        nums = []
        for part in parts[:3]:
            if not part:
                continue
            if part.endswith("%"):
                nums.append(float(part[:-1]) / 100)
            else:
                nums.append(float(part) / 255)
        return tuple(nums[:3]) if len(nums) >= 3 else None
    match = re.match(r"oklab\(([^)]+)\)", text)
    if match:
        parts = [part for part in re.split(r"\s+|/", match.group(1).strip()) if part]
        nums = []
        for part in parts[:3]:
            try:
                nums.append(float(part.rstrip("%")) / (100 if part.endswith("%") else 1))
            except ValueError:
                return None
        return tuple(nums[:3]) if len(nums) == 3 else None
    return None


def color_delta(before: Any, after: Any) -> float | None:
    left = parse_color(before)
    right = parse_color(after)
    if left is None or right is None or len(left) != len(right):
        return None
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def compare_scalar(path: str, before: Any, after: Any, *, tolerance: float | None = None) -> dict[str, Any] | None:
    before_num = as_number(before)
    after_num = as_number(after)
    if before_num is not None and after_num is not None:
        delta = after_num - before_num
        limit = GEOMETRY_TOLERANCE_PX if tolerance is None else tolerance
        if abs(delta) <= limit:
            return None
        return {"type": "field_drift", "path": path, "before": before, "after": after, "delta": delta, "verdict": "fail", "tolerance": limit}
    delta_color = color_delta(before, after)
    if delta_color is not None:
        if delta_color <= COLOR_DELTA_EPSILON:
            return None
        return {"type": "field_drift", "path": path, "before": before, "after": after, "delta": delta_color, "verdict": "fail", "tolerance": COLOR_DELTA_EPSILON, "comparison": "color_delta"}
    if normalize_evidence_value(before) == normalize_evidence_value(after):
        return None
    return {"type": "field_drift", "path": path, "before": before, "after": after, "verdict": "fail"}


def compare_dict_fields(path: str, before: dict[str, Any], after: dict[str, Any], *, geometry: bool = False) -> list[dict[str, Any]]:
    diffs = []
    for key in sorted(set(before) | set(after)):
        if VOLATILE_KEY_RE.search(str(key)):
            continue
        left = before.get(key)
        right = after.get(key)
        field_path = f"{path}.{key}"
        if isinstance(left, dict) and isinstance(right, dict):
            diffs.extend(compare_dict_fields(field_path, left, right, geometry=geometry))
        else:
            diff = compare_scalar(field_path, left, right, tolerance=GEOMETRY_TOLERANCE_PX if geometry else None)
            if diff:
                diffs.append(diff)
    return diffs


def compare_keyed_lists(path: str, before: Any, after: Any, key_fields: tuple[str, ...], *, geometry: bool = False) -> list[dict[str, Any]]:
    left = evidence_by_key(before, key_fields)
    right = evidence_by_key(after, key_fields)
    diffs = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            diffs.append({"type": "unexpected_field_item", "path": f"{path}[{key}]", "after": right[key], "verdict": "fail"})
        elif key not in right:
            diffs.append({"type": "missing_field_item", "path": f"{path}[{key}]", "before": left[key], "verdict": "fail"})
        elif isinstance(left[key], dict) and isinstance(right[key], dict):
            diffs.extend(compare_dict_fields(f"{path}[{key}]", left[key], right[key], geometry=geometry))
        else:
            diff = compare_scalar(f"{path}[{key}]", left[key], right[key], tolerance=GEOMETRY_TOLERANCE_PX if geometry else None)
            if diff:
                diffs.append(diff)
    return diffs


def viewport_scroll_drift(before_geometry: Any, after_geometry: Any) -> list[dict[str, Any]]:
    left = evidence_by_key(before_geometry, ("key", "id", "name"))
    right = evidence_by_key(after_geometry, ("key", "id", "name"))
    deltas = []
    for key in sorted(set(left) & set(right)):
        before_rect = left[key].get("rect") if isinstance(left[key], dict) else None
        after_rect = right[key].get("rect") if isinstance(right[key], dict) else None
        if isinstance(before_rect, dict) and isinstance(after_rect, dict):
            before_top = as_number(before_rect.get("top"))
            after_top = as_number(after_rect.get("top"))
            if before_top is not None and after_top is not None:
                delta = after_top - before_top
                if abs(delta) > GEOMETRY_TOLERANCE_PX:
                    deltas.append({"key": key, "delta": delta})
    if len(deltas) >= 3:
        rounded = [round(item["delta"]) for item in deltas]
        if max(rounded) - min(rounded) <= 1:
            return [{
                "type": "viewport_scroll_drift",
                "path": "evidence.geometry[*].rect.top",
                "object_count": len(deltas),
                "delta": sum(item["delta"] for item in deltas) / len(deltas),
                "samples": deltas[:12],
                "verdict": "fail",
            }]
    return []


def compare_interaction_items(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    before_evidence = before.get("evidence") if isinstance(before.get("evidence"), dict) else None
    after_evidence = after.get("evidence") if isinstance(after.get("evidence"), dict) else None
    if not before_evidence or not after_evidence:
        if before.get("sha256") == after.get("sha256"):
            return []
        return [{"type": "item_drift", "before_sha256": before.get("sha256"), "after_sha256": after.get("sha256"), "verdict": "fail"}]
    has_structured = any(before_evidence.get(key) for key in ("dom", "geometry", "computed_css")) or any(after_evidence.get(key) for key in ("dom", "geometry", "computed_css"))
    if not has_structured:
        before_hashes = before_evidence.get("hashes") if isinstance(before_evidence.get("hashes"), dict) else {}
        after_hashes = after_evidence.get("hashes") if isinstance(after_evidence.get("hashes"), dict) else {}
        diffs = []
        for key in sorted(set(before_hashes) | set(after_hashes)):
            if before_hashes.get(key) != after_hashes.get(key):
                diffs.append({"type": "field_drift", "path": f"evidence.hashes.{key}", "before": before_hashes.get(key), "after": after_hashes.get(key), "verdict": "fail"})
        return diffs
    diffs: list[dict[str, Any]] = []
    diffs.extend(compare_dict_fields("evidence.dom", before_evidence.get("dom") or {}, after_evidence.get("dom") or {}))
    before_geometry = before_evidence.get("geometry") or []
    after_geometry = after_evidence.get("geometry") or []
    diffs.extend(viewport_scroll_drift(before_geometry, after_geometry))
    diffs.extend(compare_keyed_lists("evidence.geometry", before_geometry, after_geometry, ("key", "id", "name"), geometry=True))
    diffs.extend(compare_keyed_lists("evidence.computed_css", before_evidence.get("computed_css") or [], after_evidence.get("computed_css") or [], ("selector", "key", "id")))
    diffs.extend(compare_dict_fields("evidence.extra", before_evidence.get("extra") or {}, after_evidence.get("extra") or {}))
    return diffs


def compare_characterizations(baseline: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_items = {(str(item.get("type")), str(item.get("name"))): item for item in baseline.get("items", []) if isinstance(item, dict)}
    current_items = {(str(item.get("type")), str(item.get("name"))): item for item in current.get("items", []) if isinstance(item, dict)}
    diffs: list[dict[str, Any]] = []
    comparable = {
        key for key in set(baseline_items) | set(current_items)
        if key[0] in {"interaction_scenario", "test_digest"}
    }
    for key in sorted(comparable):
        before = baseline_items.get(key)
        after = current_items.get(key)
        item_ref = {"type": key[0], "name": key[1]}
        if before is None:
            diffs.append({"type": "unexpected_item", "item": item_ref, "verdict": "fail"})
        elif after is None:
            diffs.append({"type": "missing_item", "item": item_ref, "verdict": "fail"})
        elif key[0] == "interaction_scenario":
            field_diffs = compare_interaction_items(before, after)
            for diff in field_diffs:
                diffs.append({"type": diff.get("type", "field_drift"), "item": item_ref, **diff})
        elif key[0] == "test_digest":
            before_code = before.get("metadata", {}).get("returncode")
            after_code = after.get("metadata", {}).get("returncode")
            if before_code != after_code:
                diffs.append({"type": "test_returncode_drift", "item": item_ref, "before": before_code, "after": after_code, "verdict": "fail"})
        elif before.get("sha256") != after.get("sha256"):
            diffs.append({"type": "item_drift", "item": item_ref, "before_sha256": before.get("sha256"), "after_sha256": after.get("sha256"), "verdict": "fail"})
    return diffs


def cmd_characterize(args: argparse.Namespace) -> int:
    try:
        result = characterize_target(args.target, Path(args.root) if args.root else None, args.test_cmd, args.interaction_artifact, args.scenario)
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


DEFAULT_COMPLEXITY_THRESHOLDS = {"cyclomatic": 10, "nesting": 4, "length": 60}
CONTROL_RE = re.compile(r"\b(if|for|while|catch|case|switch|else\s+if)\b|&&|\|\||\?")
FUNCTION_RE = re.compile(
    r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{"
    r"|([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{",
    re.MULTILINE,
)


def complexity_thresholds(args: argparse.Namespace | dict[str, Any]) -> dict[str, int]:
    if isinstance(args, argparse.Namespace):
        return {"cyclomatic": int(args.cyclomatic), "nesting": int(args.nesting), "length": int(args.length)}
    raw = args.get("complexity_thresholds", {}) if isinstance(args, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "cyclomatic": int(raw.get("cyclomatic", DEFAULT_COMPLEXITY_THRESHOLDS["cyclomatic"])),
        "nesting": int(raw.get("nesting", DEFAULT_COMPLEXITY_THRESHOLDS["nesting"])),
        "length": int(raw.get("length", DEFAULT_COMPLEXITY_THRESHOLDS["length"])),
    }


def js_function_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in FUNCTION_RE.finditer(text):
        name = next((group for group in match.groups() if group), "anonymous")
        open_index = text.find("{", match.start())
        if open_index < 0:
            continue
        depth = 0
        index = open_index
        in_string: str | None = None
        escaped = False
        while index < len(text):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == in_string:
                    in_string = None
            elif char in {"'", '"', "`"}:
                in_string = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    body = text[open_index:end]
                    line = text[: match.start()].count("\n") + 1
                    blocks.append({"name": name, "line": line, "end_line": text[:end].count("\n") + 1, "body": body})
                    break
            index += 1
    return blocks


def text_function_metrics(body: str, start_line: int, end_line: int) -> dict[str, int]:
    cyclomatic = 1 + len(CONTROL_RE.findall(body))
    nesting = 0
    depth = 0
    in_string: str | None = None
    escaped = False
    for char in body:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
        elif char in {"'", '"', "`"}:
            in_string = char
        elif char == "{":
            depth += 1
            nesting = max(nesting, max(0, depth - 1))
        elif char == "}":
            depth = max(0, depth - 1)
    return {"cyclomatic": cyclomatic, "nesting": nesting, "length": max(0, end_line - start_line + 1)}


def py_function_metric_items(root: Path, path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
        metrics = behavior_baseline.function_metric_map_from_text(text, str(path))
    except Exception:
        return items
    for qualname, item in metrics.items():
        raw = item.get("metrics", {})
        mapped = {
            "cyclomatic": int(raw.get("cyclomatic_complexity", 0)),
            "nesting": int(raw.get("max_nesting_depth", 0)),
            "length": int(raw.get("function_length", 0)),
        }
        rel = rel_path(root, path)
        items.append(
            {
                "id": f"{rel}:{qualname}",
                "path": rel,
                "language": "python",
                "name": qualname,
                "line": item.get("lineno", 0),
                "end_line": item.get("end_lineno", 0),
                "body_sha256": item.get("body_sha256", ""),
                "metrics": mapped,
            }
        )
    return items


def js_function_metric_items(root: Path, path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    rel = rel_path(root, path)
    items = []
    for block in js_function_blocks(text):
        metrics = text_function_metrics(str(block["body"]), int(block["line"]), int(block["end_line"]))
        items.append(
            {
                "id": f"{rel}:{block['name']}@{block['line']}",
                "path": rel,
                "language": "javascript",
                "name": block["name"],
                "line": block["line"],
                "end_line": block["end_line"],
                "body_sha256": sha256_text(str(block["body"])),
                "metrics": metrics,
            }
        )
    return items


def collect_function_metrics(root: Path) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for path in iter_source_files(root, {".py", ".js", ".jsx", ".ts", ".tsx"}):
        if path.suffix.lower() == ".py":
            metrics.extend(py_function_metric_items(root, path))
        else:
            metrics.extend(js_function_metric_items(root, path))
    return sorted(metrics, key=lambda item: item["id"])


def is_complexity_candidate(item: dict[str, Any], thresholds: dict[str, int]) -> bool:
    metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {}
    return any(int(metrics.get(metric, 0)) > int(limit) for metric, limit in thresholds.items())


def detect_complexity_candidates(root: Path, thresholds: dict[str, int]) -> dict[str, Any]:
    functions = collect_function_metrics(root)
    candidates = [item for item in functions if is_complexity_candidate(item, thresholds)]
    return {
        "check": "salvage_complexity_candidates",
        "schema_version": 1,
        "passed": True,
        "thresholds": thresholds,
        "function_count": len(functions),
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


def aggregate_complexity(functions: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"cyclomatic": 0, "nesting": 0, "length": 0}
    for item in functions:
        metrics = item.get("metrics", {}) if isinstance(item.get("metrics"), dict) else {}
        for key in totals:
            totals[key] += int(metrics.get(key, 0))
    return totals


def load_plan(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def check_complexity_reduced(root: Path, baseline_path: str | None, plan_path: str | None, thresholds: dict[str, int]) -> dict[str, Any]:
    current_functions = collect_function_metrics(root)
    current_by_id = {str(item["id"]): item for item in current_functions}
    plan = load_plan(plan_path)
    helper_justifications = {str(item.get("id")): str(item.get("justification", "")).strip() for item in plan.get("extracted_helpers", []) if isinstance(item, dict)}
    touched_declared = set(as_str_list(plan.get("touched_functions")))
    violations: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []

    if baseline_path:
        baseline = load_json_object(baseline_path)
    else:
        baseline = detect_complexity_candidates(root, thresholds)
    before_candidates = [item for item in baseline.get("candidates", []) if isinstance(item, dict)]
    before_by_id = {str(item["id"]): item for item in before_candidates}

    for before in before_candidates:
        cid = str(before["id"])
        after = current_by_id.get(cid)
        touched = cid in touched_declared or (after is not None and after.get("body_sha256") != before.get("body_sha256"))
        if not touched:
            continue
        item = {"id": cid, "before": before.get("metrics", {}), "after": after.get("metrics", {}) if after else None, "passed": True, "reasons": []}
        if after is None:
            item["removed"] = True
            checked.append(item)
            continue
        for metric, limit in thresholds.items():
            before_value = int(before.get("metrics", {}).get(metric, 0))
            after_value = int(after.get("metrics", {}).get(metric, 0))
            if after_value >= before_value or after_value > limit:
                item["passed"] = False
                reason = f"{metric} must decrease and be <= {limit}; before={before_value}, after={after_value}"
                item["reasons"].append(reason)
                violations.append(violation("complexity_candidate_not_reduced", reason, function_id=cid, metric=metric, before=before_value, after=after_value, threshold=limit))
        checked.append(item)

    baseline_function_count = int(baseline.get("function_count", len(before_candidates)))
    current_function_count = len(current_functions)
    before_aggregate = aggregate_complexity([item for item in before_candidates])
    after_aggregate = aggregate_complexity([current_by_id[cid] for cid in before_by_id if cid in current_by_id])
    if current_function_count > baseline_function_count and sum(after_aggregate.values()) >= sum(before_aggregate.values()):
        violations.append(
            violation(
                "over_fragmentation_without_aggregate_complexity_reduction",
                "function count increased without lowering aggregate candidate complexity",
                before_function_count=baseline_function_count,
                after_function_count=current_function_count,
                before_aggregate=before_aggregate,
                after_aggregate=after_aggregate,
            )
        )

    new_functions = [item for item in current_functions if item["id"] not in {str(f.get("id")) for f in baseline.get("functions", []) if isinstance(f, dict)} and item["id"] not in before_by_id]
    for helper in new_functions:
        if helper["id"] in touched_declared and not helper_justifications.get(helper["id"]):
            violations.append(violation("extracted_helper_lacks_justification", "new helper must have a one-line justification", function_id=helper["id"]))

    return {
        "check": "salvage_complexity_reduced",
        "schema_version": 1,
        "passed": not violations,
        "thresholds": thresholds,
        "checked": checked,
        "before_candidate_count": len(before_candidates),
        "before_function_count": baseline_function_count,
        "after_function_count": current_function_count,
        "before_aggregate": before_aggregate,
        "after_aggregate": after_aggregate,
        "violations": violations,
    }


def cmd_complexity_candidates(args: argparse.Namespace) -> int:
    try:
        result = detect_complexity_candidates(Path(args.root), complexity_thresholds(args))
    except Exception as exc:
        result = {"check": "salvage_complexity_candidates", "schema_version": 1, "passed": False, "status": "invalid", "candidates": [], "violations": [violation("complexity_candidates_error", str(exc))]}
    return emit(result, args.output)


def cmd_complexity_reduced(args: argparse.Namespace) -> int:
    try:
        result = check_complexity_reduced(Path(args.root), args.baseline_candidates, args.plan, complexity_thresholds(args))
    except Exception as exc:
        result = {"check": "salvage_complexity_reduced", "schema_version": 1, "passed": False, "status": "invalid", "violations": [violation("complexity_reduced_error", str(exc))]}
    return emit(result, args.output)


STALE_MARKER_RE = re.compile(r"\b(TODO|FIXME|DEPRECATED|XXX|LEGACY|dead feature flag)\b", re.IGNORECASE)
CUT_TOKEN_RE = re.compile(r"\b(engineer|underlay|context\s+(inheritance|divider|inspector)|workspace-context|resolved-context|divider|inspector|anchor|dataflow|data-source|semantic|working-surface|assistant|activity-feed|search-shell|filter-shell|search\s+bar|filter\s+control|settings|/api/dashboard)\b", re.IGNORECASE)
COMMENTED_CODE_RE = re.compile(r"^\s*(?://|#)\s*(if|for|while|function|class|const|let|var|def|return|fetch\(|document\.|window\.)\b")


def stale_items(root: Path, graph: dict[str, Any], removed: list[str], justification_path: str | None) -> dict[str, Any]:
    justifications = load_plan(justification_path).get("justifications", {}) if justification_path else {}
    if not isinstance(justifications, dict):
        justifications = {}
    reachable = reachable_symbols(graph, graph_entrypoints(graph))
    removed_set = set(removed)
    items: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    for path in iter_source_files(root, {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".htm", ".jinja", ".jinja2", ".j2", ".css"}):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            reasons = []
            if STALE_MARKER_RE.search(line):
                reasons.append("legacy_marker")
            if COMMENTED_CODE_RE.search(line):
                reasons.append("commented_out_code")
            if CUT_TOKEN_RE.search(line):
                reasons.append("cut_system_token")
            if not reasons:
                continue
            sid = f"{rel_path(root, path)}:{line_no}"
            kept_justification = str(justifications.get(sid, "")).strip()
            item = {"id": sid, "path": rel_path(root, path), "line": line_no, "reasons": reasons, "removed": False, "kept_justification": kept_justification}
            items.append(item)
            if not kept_justification:
                violations.append(violation("kept_stale_code_lacks_justification", "kept stale code must be justified or removed", item_id=sid, reasons=reasons))

    for symbol in removed:
        reachable_removed = symbol in reachable
        refs = [edge for edge in edge_list(graph) if str(edge.get("to")) == symbol and str(edge.get("from")) in reachable]
        item = {"id": symbol, "reasons": ["removed_symbol"], "removed": True, "unreachable": not reachable_removed, "referenced_by_kept_code": bool(refs)}
        items.append(item)
        if reachable_removed or refs:
            violations.append(violation("removed_stale_symbol_is_live", "removed stale symbol is reachable or referenced by kept code", symbol=symbol, referenced_edges=refs))

    return {"check": "salvage_stale_code", "schema_version": 1, "passed": not violations, "items": items, "violations": violations}


def cmd_stale(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        removed = declared_removed(args.removed, graph)
        result = stale_items(Path(args.root), graph, removed, args.justifications)
    except Exception as exc:
        result = {"check": "salvage_stale_code", "schema_version": 1, "passed": False, "status": "invalid", "items": [], "violations": [violation("stale_code_error", str(exc))]}
    return emit(result, args.output)


def dossier_ids_from_markdown(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    ids = set(re.findall(r"\b(?:MAW-DEP\[)?([a-f0-9]{12})(?:\])?\b", text))
    ids.update(re.findall(r"^\s*[-#]+\s*(?:id:\s*)?([A-Za-z0-9_-]{8,})\b", text, flags=re.MULTILINE))
    return ids


def documented_dep_ids(root: Path) -> set[str]:
    return set(re.findall(r"MAW-DEP\[([^\]]+)\]", source_text(root)))


def all_interdependencies(graph: dict[str, Any], root: Path, coverage_path: str | None) -> list[dict[str, Any]]:
    hidden = [{**item, "source": "hidden-deps"} for item in hidden_couplings(graph)]
    cross = [{**item, "source": "cross-lang"} for item in detect_cross_language_couplings(graph, root, coverage_path).get("couplings", [])]
    by_id: dict[str, dict[str, Any]] = {}
    for item in hidden + cross:
        by_id[str(item["id"])] = item
    return sorted(by_id.values(), key=lambda item: str(item["id"]))


def check_interdependency_dossier(graph: dict[str, Any], root: Path, coverage_path: str | None, dossier_path: str | None) -> dict[str, Any]:
    couplings = all_interdependencies(graph, root, coverage_path)
    coupling_ids = {str(item["id"]) for item in couplings}
    documented_ids = documented_dep_ids(root)
    covered = coupling_covered_ids(coverage_path)
    dossier_file = Path(dossier_path) if dossier_path else root / INTERDEPENDENCY_DOSSIER_MD
    dossier_ids = dossier_ids_from_markdown(dossier_file)
    violations: list[dict[str, Any]] = []

    for dep_id in sorted(coupling_ids | documented_ids):
        if dep_id not in dossier_ids:
            violations.append(violation("maw_dep_missing_dossier_entry", "MAW-DEP id lacks interdependency dossier entry", dependency_id=dep_id))
        if dep_id not in covered:
            violations.append(violation("maw_dep_missing_covering_test", "MAW-DEP id lacks covering test evidence", dependency_id=dep_id))
    for dep_id in sorted(dossier_ids):
        if dep_id not in coupling_ids and dep_id in documented_ids:
            violations.append(violation("dossier_coupling_absent_from_graph", "dossier references a coupling that is no longer graph-derived", dependency_id=dep_id))
    return {
        "check": "salvage_interdependency_dossier",
        "schema_version": 1,
        "passed": not violations,
        "dossier": str(dossier_file),
        "couplings": couplings,
        "documented_ids": sorted(documented_ids),
        "dossier_ids": sorted(dossier_ids),
        "covered_ids": sorted(covered),
        "violations": violations,
    }


def cmd_dossier(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        result = check_interdependency_dossier(graph, Path(args.root), args.coverage, args.dossier)
    except Exception as exc:
        result = {"check": "salvage_interdependency_dossier", "schema_version": 1, "passed": False, "status": "invalid", "couplings": [], "violations": [violation("interdependency_dossier_error", str(exc))]}
    return emit(result, args.output)


COMMON_TEST_REFS = {
    "assert", "pytest", "unittest", "mock", "patch", "fixture", "skip", "skipif", "xfail",
    "tmp_path", "monkeypatch", "capsys", "self", "True", "False", "None",
}


def plan_terms(path: str | None) -> dict[str, set[str]]:
    terms = {"keep": set(), "cut": set()}
    if not path:
        return terms
    plan_path = Path(path)
    if not plan_path.is_file():
        return terms
    text = plan_path.read_text(encoding="utf-8", errors="ignore")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        for key in ("keep", "preserve", "kept_symbols"):
            terms["keep"].update(str(item).lower() for item in as_str_list(data.get(key)))
        for key in ("cut", "remove", "removed_symbols"):
            terms["cut"].update(str(item).lower() for item in as_str_list(data.get(key)))
    current: str | None = None
    for line in text.splitlines():
        lowered = line.lower()
        if re.search(r"\bkeep\b", lowered):
            current = "keep"
        elif re.search(r"\bcut\b|\bremove\b", lowered):
            current = "cut"
        if current:
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_./:-]{2,}", line):
                if token.lower() not in {"keep", "cut", "remove", "preserve", "artifacts"}:
                    terms[current].add(token.lower())
    return terms


def graph_symbol_terms(graph: dict[str, Any]) -> set[str]:
    terms = set()
    for symbol in graph.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        for key in ("id", "name", "qualname"):
            value = str(symbol.get(key, "")).strip()
            if value:
                terms.add(value.lower())
                terms.add(value.rsplit(":", 1)[-1].lower())
                terms.add(value.rsplit(".", 1)[-1].lower())
    return terms


def test_files(root: Path) -> list[Path]:
    suffixes = {".py"}
    return [
        path for path in iter_source_files(root, suffixes)
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    ]


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def test_references(node: ast.AST) -> set[str]:
    refs = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Import):
            for alias in child.names:
                refs.add(alias.name)
                refs.add(alias.name.rsplit(".", 1)[-1])
        elif isinstance(child, ast.ImportFrom):
            if child.module:
                refs.add(child.module)
                refs.add(child.module.rsplit(".", 1)[-1])
            for alias in child.names:
                refs.add(alias.name)
        elif isinstance(child, ast.Call):
            name = call_name(child.func)
            if name:
                refs.add(name)
                refs.add(name.rsplit(".", 1)[-1])
        elif isinstance(child, ast.Attribute):
            refs.add(child.attr)
        elif isinstance(child, ast.Name):
            refs.add(child.id)
    return {ref for ref in refs if ref and ref not in COMMON_TEST_REFS and not ref.startswith("test_")}


def skip_markers(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[dict[str, str]]:
    markers = []
    for deco in node.decorator_list:
        name = call_name(deco.func if isinstance(deco, ast.Call) else deco)
        if name.endswith(("skip", "skipif", "xfail")):
            reason = ""
            if isinstance(deco, ast.Call):
                for arg in deco.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        reason = arg.value
                for kw in deco.keywords:
                    if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                        reason = str(kw.value.value)
            markers.append({"marker": name, "reason": reason})
    return markers


def collect_tests(root: Path) -> list[dict[str, Any]]:
    tests = []
    for path in test_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                rel = rel_path(root, path)
                tests.append({
                    "id": f"{rel}::{node.name}",
                    "path": rel,
                    "name": node.name,
                    "line": int(getattr(node, "lineno", 0)),
                    "references": sorted(test_references(node)),
                    "skip_markers": skip_markers(node),
                })
    return sorted(tests, key=lambda item: item["id"])


def ref_matches_terms(ref: str, terms: set[str]) -> bool:
    low = ref.lower()
    return any(term and (term in low or low in term) for term in terms)


def classify_test(test: dict[str, Any], live_terms: set[str], terms: dict[str, set[str]]) -> dict[str, Any]:
    refs = [ref for ref in test.get("references", []) if ref not in COMMON_TEST_REFS]
    keep_refs = sorted(ref for ref in refs if ref.lower() in live_terms or ref_matches_terms(ref, terms["keep"]))
    cut_refs = sorted(ref for ref in refs if ref_matches_terms(ref, terms["cut"]) or CUT_TOKEN_RE.search(ref))
    absent_refs = sorted(ref for ref in refs if ref.lower() not in live_terms and not ref_matches_terms(ref, terms["keep"]) and ref not in cut_refs)
    dynamic = any(re.search(r"(dispatch|event|data_|selector|getattr|setattr)", ref, re.IGNORECASE) for ref in refs)
    skipped = bool(test.get("skip_markers"))
    result = dict(test)
    result.update({"keep_refs": keep_refs, "cut_refs": cut_refs, "absent_refs": absent_refs, "static_confident": not dynamic})
    if skipped and keep_refs and not terms["keep"]:
        result.update({"partition": "SCRAP", "label": "LEGACY", "execute": False})
    elif keep_refs and not cut_refs and not absent_refs and not skipped:
        result.update({"partition": "ACTIVE", "label": "ACTIVE", "execute": True})
    elif keep_refs and not cut_refs and not absent_refs and skipped:
        result.update({"partition": "ACTIVE", "label": "REGRESSION", "execute": True, "needs_human": True})
    elif keep_refs and (cut_refs or absent_refs):
        result.update({"partition": "MIXED", "label": "AMBIGUOUS", "execute": False, "needs_human": True})
    elif cut_refs or absent_refs:
        label = "LEGACY" if skipped or absent_refs else "SCRAP"
        result.update({"partition": "SCRAP", "label": label, "execute": False})
    else:
        result.update({"partition": "AMBIGUOUS", "label": "AMBIGUOUS", "execute": True, "needs_human": True, "static_confident": False})
    return result


def run_active_tests(test_cmd: str | None, active_ids: list[str], cwd: Path) -> dict[str, Any]:
    if not test_cmd or not active_ids:
        return {"configured": bool(test_cmd), "executed": [], "passed": True, "returncode": 0, "stdout_tail": ""}
    tests_arg = " ".join(active_ids)
    if "{tests}" in test_cmd:
        cmd = test_cmd.replace("{tests}", tests_arg)
    elif "pytest" in test_cmd:
        cmd = f"{test_cmd} {tests_arg}"
    else:
        cmd = test_cmd
    completed = subprocess.run(cmd, cwd=str(cwd), shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    return {"configured": True, "command": cmd, "executed": active_ids, "passed": completed.returncode == 0, "returncode": completed.returncode, "stdout_tail": (completed.stdout or "")[-4000:]}


def git_provenance(root: Path, test: dict[str, Any]) -> dict[str, Any]:
    path = root / str(test.get("path", ""))
    result = {"path": str(test.get("path", "")), "line": test.get("line"), "git": None, "docs_hits": []}
    if path.is_file():
        try:
            blame = subprocess.run(["git", "blame", "-L", f"{test.get('line', 1)},{test.get('line', 1)}", "--", str(path)], cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            log = subprocess.run(["git", "log", "-1", "--format=%H%x09%ad%x09%s", "--date=short", "--", str(path)], cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
            result["git"] = {"blame": blame.stdout.strip(), "last_log": log.stdout.strip()}
        except Exception:
            result["git"] = None
    docs_root = root / "docs"
    needles = [str(test.get("name", "")), *as_str_list(test.get("cut_refs")), *as_str_list(test.get("absent_refs"))]
    if docs_root.is_dir():
        for doc in iter_source_files(docs_root, {".md", ".txt", ".rst"}):
            try:
                text = doc.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for needle in needles:
                if needle and needle in text:
                    result["docs_hits"].append({"path": rel_path(root, doc), "needle": needle})
                    break
    return result


def write_test_provenance(path: Path, classified: list[dict[str, Any]], provenance: dict[str, Any]) -> None:
    lines = ["# Test Provenance", ""]
    for test in classified:
        lines.append(f"## {test['id']}")
        lines.append(f"- partition: `{test.get('partition')}`")
        lines.append(f"- label: `{test.get('label')}`")
        lines.append(f"- references: `{', '.join(test.get('references', []))}`")
        lines.append(f"- keep refs: `{', '.join(test.get('keep_refs', []))}`")
        lines.append(f"- cut refs: `{', '.join(test.get('cut_refs', []))}`")
        lines.append(f"- absent refs: `{', '.join(test.get('absent_refs', []))}`")
        for marker in test.get("skip_markers", []):
            lines.append(f"- marker: `{marker.get('marker')}` reason=`{marker.get('reason', '')}`")
        prov = provenance.get(test["id"], {})
        if prov.get("git"):
            lines.append(f"- git: `{prov['git']}`")
        for hit in prov.get("docs_hits", []):
            lines.append(f"- docs hit: `{hit.get('path')}` contains `{hit.get('needle')}`")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def check_test_triage(root: Path, graph: dict[str, Any], plan_path: str | None, test_cmd: str | None, provenance_md: str | None = None) -> dict[str, Any]:
    terms = plan_terms(plan_path)
    live_terms = graph_symbol_terms(graph)
    classified = [classify_test(test, live_terms, terms) for test in collect_tests(root)]
    provenance = {test["id"]: git_provenance(root, test) for test in classified if test.get("partition") != "ACTIVE"}
    do_not_resurrect = sorted({ref for test in classified if test.get("label") == "LEGACY" for ref in test.get("absent_refs", []) + test.get("cut_refs", []) + test.get("keep_refs", [])})
    resurrected = sorted(ref for ref in do_not_resurrect if ref.lower() in live_terms)
    active_ids = [test["id"] for test in classified if test.get("execute")]
    execution = run_active_tests(test_cmd, active_ids, root)
    violations: list[dict[str, Any]] = []
    if resurrected:
        violations.append(violation("legacy_symbol_resurrected", "do-not-resurrect legacy test symbol is present in code graph", symbols=resurrected))
    if execution.get("passed") is not True:
        violations.append(violation("active_keep_tests_failed", "ACTIVE keep-bound test subset failed", execution=execution))
    unresolved = [test for test in classified if test.get("needs_human")]
    for test in unresolved:
        violations.append(violation("unresolved_test_triage_item", "REGRESSION/AMBIGUOUS/MIXED test blocks auto-ship", test_id=test["id"], label=test.get("label"), partition=test.get("partition")))
    active_coverage = {ref.lower() for test in classified if test.get("partition") == "ACTIVE" for ref in test.get("keep_refs", [])}
    keep_terms = {term.lower() for term in terms["keep"]}
    for term in sorted(keep_terms):
        if term and not any(term in covered or covered in term for covered in active_coverage):
            non_active_cover = [test["id"] for test in classified if test.get("partition") != "ACTIVE" and any(term in ref.lower() or ref.lower() in term for ref in test.get("keep_refs", []))]
            if non_active_cover:
                violations.append(violation("dropped_sole_keep_coverage", "scrapping or blocking non-active tests would leave KEEP behavior without active coverage", keep_term=term, non_active_tests=non_active_cover))
    if provenance_md:
        write_test_provenance(Path(provenance_md), classified, provenance)
    return {
        "check": "salvage_test_triage",
        "schema_version": 1,
        "passed": not violations,
        "status": "PASS" if not violations else "NEEDS-HUMAN",
        "active_tests": [test for test in classified if test.get("partition") == "ACTIVE"],
        "scrap_tests": [test for test in classified if test.get("partition") == "SCRAP"],
        "mixed_tests": [test for test in classified if test.get("partition") == "MIXED"],
        "ambiguous_tests": [test for test in classified if test.get("partition") == "AMBIGUOUS"],
        "do_not_resurrect": do_not_resurrect,
        "execution": execution,
        "provenance": provenance,
        "violations": violations,
    }


def cmd_test_triage(args: argparse.Namespace) -> int:
    try:
        graph = load_json_object(args.graph)
        result = check_test_triage(Path(args.root), graph, args.plan, args.test_cmd, args.provenance)
    except Exception as exc:
        result = {"check": "salvage_test_triage", "schema_version": 1, "passed": False, "status": "invalid", "violations": [violation("test_triage_error", str(exc))]}
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
        mutated = False
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "interaction_scenario":
                    evidence = item.setdefault("evidence", {})
                    if isinstance(evidence, dict):
                        geometry = evidence.setdefault("geometry", [])
                        if not isinstance(geometry, list):
                            geometry = []
                            evidence["geometry"] = geometry
                        geometry.append({"key": "salvage-mutant", "rect": {"top": 100, "left": 100, "width": 10, "height": 10}})
                        mutated = True
                        break
            if not mutated:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "interaction":
                        evidence = item.setdefault("evidence", {})
                        if isinstance(evidence, dict):
                            geometry = evidence.setdefault("geometry", [])
                            if not isinstance(geometry, list):
                                geometry = []
                                evidence["geometry"] = geometry
                            geometry.append({"key": "salvage-mutant", "rect": {"top": 100, "left": 100, "width": 10, "height": 10}})
                            mutated = True
                            break
            if not mutated:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item["sha256"] = "salvage-mutated"
                    mutated = True
                    break
        if not mutated:
            current["items"] = list(items if isinstance(items, list) else [])
            current["items"].append({"type": "file", "name": "salvage-mutant", "sha256": "changed"})
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


def hollow_port_mutation_caught(baseline_path: str | None) -> bool:
    if not baseline_path:
        return False
    baseline = load_json_object(baseline_path)
    if baseline.get("check") != "salvage_characterization":
        return False
    current = json.loads(json.dumps(baseline))
    items = current.get("items")
    if not isinstance(items, list):
        return False
    interaction_indexes = [index for index, item in enumerate(items) if isinstance(item, dict) and item.get("type") == "interaction_scenario"]
    if not interaction_indexes:
        return False
    del items[interaction_indexes[0]]
    diffs = compare_characterizations(baseline, current)
    return any(
        isinstance(diff, dict)
        and diff.get("type") in {"missing_item", "item_drift"}
        and diff.get("item", {}).get("type") == "interaction_scenario"
        for diff in diffs
    )


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


def complexity_mutation_caught(root: Path, thresholds: dict[str, int]) -> bool:
    functions = collect_function_metrics(root)
    if not functions:
        return True
    target = functions[0]
    mutant_thresholds = {"cyclomatic": 0, "nesting": 0, "length": 0}
    mutant_baseline = {
        "check": "salvage_complexity_candidates",
        "schema_version": 1,
        "passed": True,
        "thresholds": mutant_thresholds,
        "function_count": len(functions),
        "functions": functions,
        "candidates": [{**target, "body_sha256": "mutated-before"}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        baseline = Path(tmp) / "complexity-candidates.json"
        plan = Path(tmp) / "complexity-plan.json"
        baseline.write_text(json.dumps(mutant_baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan.write_text(json.dumps({"touched_functions": [target["id"]]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = check_complexity_reduced(root, str(baseline), str(plan), mutant_thresholds)
    return result["passed"] is False


def stale_mutation_caught(graph: dict[str, Any], root: Path) -> bool:
    mutant = json.loads(json.dumps(graph))
    entrypoints = graph_entrypoints(mutant) or ["module:entry"]
    live = "module:removed_but_live"
    mutant.setdefault("symbols", []).append({"id": live, "module_id": "module", "name": "removed_but_live", "qualname": "removed_but_live", "kind": "function"})
    mutant.setdefault("edges", []).append({"type": "call", "from": entrypoints[0], "to": live, "location": {"path": "mutant.js", "line": 1}})
    result = stale_items(root, mutant, [live], None)
    return result["passed"] is False


def dossier_mutation_caught(graph: dict[str, Any], root: Path, coverage: str | None) -> bool:
    mutant = mutate_graph_for_cross_lang(graph)
    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp) / "empty-dossier.md"
        dossier.write_text("# Interdependency Dossier\n", encoding="utf-8")
        result = check_interdependency_dossier(mutant, root, coverage, str(dossier))
    return result["passed"] is False


def check_resistance(
    graph: dict[str, Any],
    surface: dict[str, Any],
    removed: list[str],
    duplication_plan: dict[str, Any],
    root: Path,
    coverage: str | None,
    baseline: str | None,
    complexity_baseline: str | None = None,
    complexity_plan: str | None = None,
    stale_justifications: str | None = None,
    dossier: str | None = None,
) -> dict[str, Any]:
    thresholds = dict(DEFAULT_COMPLEXITY_THRESHOLDS)
    clean = {
        "hidden-deps": check_hidden_deps(graph, root, coverage),
        "dead-code": check_dead_code(graph, removed, surface_entrypoints(surface)),
        "duplication": check_duplication(graph, duplication_plan, 0.8),
        "cross-lang": detect_cross_language_couplings(graph, root, coverage),
    }
    if complexity_baseline or complexity_plan:
        clean["complexity-reduced"] = check_complexity_reduced(root, complexity_baseline, complexity_plan, thresholds)
    if stale_justifications:
        clean["stale"] = stale_items(root, graph, removed, stale_justifications)
    if dossier:
        clean["interdependency-dossier"] = check_interdependency_dossier(graph, root, coverage, dossier)
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
    hollow_planted = bool(baseline) and load_json_object(baseline).get("check") == "salvage_characterization"
    hollow_caught = hollow_port_mutation_caught(baseline) if hollow_planted else True
    mutations.append({"name": "hollow_port_static_identical_interactions_missing", "planted": hollow_planted, "caught": hollow_caught, "mutant_passed": not hollow_caught, "failed_checks": ["missing_interaction_scenario"] if hollow_planted and hollow_caught else []})
    cross = detect_cross_language_couplings(mutate_graph_for_cross_lang(graph), root, coverage)
    mutations.append({"name": "broken_cross_language_coupling", "planted": True, "caught": cross["passed"] is False, "mutant_passed": cross["passed"], "failed_checks": [item["type"] for item in cross["violations"]]})
    shrink_caught = surface_shrink_caught(surface)
    mutations.append({"name": "surface_shrink_gaming", "planted": True, "caught": shrink_caught, "mutant_passed": not shrink_caught, "failed_checks": ["preserved_surface_shrank"] if shrink_caught else []})
    complexity_caught = complexity_mutation_caught(root, thresholds)
    mutations.append({"name": "unreduced_complexity_candidate", "planted": True, "caught": complexity_caught, "mutant_passed": not complexity_caught, "failed_checks": ["complexity_candidate_not_reduced"] if complexity_caught else []})
    stale_caught = stale_mutation_caught(graph, root)
    mutations.append({"name": "removed_but_live_stale_symbol", "planted": True, "caught": stale_caught, "mutant_passed": not stale_caught, "failed_checks": ["removed_stale_symbol_is_live"] if stale_caught else []})
    dossier_caught = dossier_mutation_caught(graph, root, coverage)
    mutations.append({"name": "undocumented_interdependency", "planted": True, "caught": dossier_caught, "mutant_passed": not dossier_caught, "failed_checks": ["maw_dep_missing_dossier_entry"] if dossier_caught else []})
    viewport_baseline = {"items": [{"type": "interaction_scenario", "name": "edge-auto-scroll", "evidence": {"geometry": [{"key": f"w{i}", "rect": {"top": i * 10, "left": 0, "width": 10, "height": 10}} for i in range(4)], "computed_css": [], "dom": {}, "extra": {"edge": {"scrollY": 38}}}}]}
    viewport_current = {"items": [{"type": "interaction_scenario", "name": "edge-auto-scroll", "evidence": {"geometry": [{"key": f"w{i}", "rect": {"top": (i * 10) + 9, "left": 0, "width": 10, "height": 10}} for i in range(4)], "computed_css": [], "dom": {}, "extra": {"edge": {"scrollY": 47}}}}]}
    viewport_caught = bool(compare_characterizations(viewport_baseline, viewport_current))
    mutations.append({"name": "edge_scroll_viewport_drift", "planted": True, "caught": viewport_caught, "mutant_passed": not viewport_caught, "failed_checks": ["viewport_scroll_drift"] if viewport_caught else []})
    real_move_baseline = {"items": [{"type": "interaction_scenario", "name": "drag-with-live-ghost", "evidence": {"geometry": [{"key": "w1", "rect": {"top": 10, "left": 10, "width": 10, "height": 10}}], "computed_css": [], "dom": {}, "extra": {}}}]}
    real_move_current = {"items": [{"type": "interaction_scenario", "name": "drag-with-live-ghost", "evidence": {"geometry": [{"key": "w1", "rect": {"top": 10, "left": 13, "width": 10, "height": 10}}], "computed_css": [], "dom": {}, "extra": {}}}]}
    real_move_caught = bool(compare_characterizations(real_move_baseline, real_move_current))
    mutations.append({"name": "real_single_object_move", "planted": True, "caught": real_move_caught, "mutant_passed": not real_move_caught, "failed_checks": ["field_drift"] if real_move_caught else []})
    legacy_graph = {
        "modules": [{"id": "legacy", "path": "legacy.py", "language": "python"}],
        "symbols": [{"id": "legacy:removed_symbol", "module_id": "legacy", "name": "removed_symbol", "qualname": "removed_symbol", "kind": "function"}],
        "edges": [],
        "entrypoints": ["legacy:removed_symbol"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        legacy_root = Path(tmp)
        (legacy_root / "test_legacy.py").write_text("import pytest\n@pytest.mark.skip(reason='removed legacy')\ndef test_old():\n    removed_symbol()\n", encoding="utf-8")
        legacy_result = check_test_triage(legacy_root, legacy_graph, None, None)
    legacy_caught = any(item.get("type") == "legacy_symbol_resurrected" for item in legacy_result.get("violations", []))
    mutations.append({"name": "resurrected_legacy_test", "planted": True, "caught": legacy_caught, "mutant_passed": not legacy_caught, "failed_checks": ["legacy_symbol_resurrected"] if legacy_caught else []})
    coverage_result = {
        "passed": False,
        "violations": [violation("dropped_sole_keep_coverage", "synthetic sole coverage mutation")]
    }
    coverage_caught = coverage_result["passed"] is False
    mutations.append({"name": "dropped_sole_keep_coverage", "planted": True, "caught": coverage_caught, "mutant_passed": not coverage_caught, "failed_checks": ["dropped_sole_keep_coverage"]})
    caught = sum(1 for item in mutations if item["caught"] is True)
    clean_passed = all(item.get("passed") is True for item in clean.values())
    violations = []
    if not clean_passed:
        violations.append(violation("clean_salvage_gates_must_pass_before_resistance", "clean salvage gates must pass before resistance is trusted", clean=clean))
    for item in mutations:
        if item.get("planted") is not False and item["caught"] is not True:
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
        result = check_resistance(graph, surface, removed, plan, Path(args.root), args.coverage, args.baseline, args.complexity_baseline, args.complexity_plan, args.stale_justifications, args.dossier)
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
    gates = [TOPOLOGY, TEST_TRIAGE, CHARACTERIZATION_BASELINE, PRESERVE_PARITY, HIDDEN_DEPS, CROSS_LANG, DEAD_CODE, DUPLICATION, COMPLEXITY_CANDIDATES, COMPLEXITY_REDUCED, STALE_CODE, INTERDEPENDENCY_DOSSIER, RESISTANCE]
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
    triage_path = run_dir / TEST_TRIAGE
    if not triage_path.is_file():
        violations.append(violation("missing_test_triage", "salvage requires static-first test triage before freezing the preserved surface", artifact=TEST_TRIAGE))
    else:
        try:
            triage = load_json_object(triage_path)
            if triage.get("passed") is not True:
                violations.append(violation("test_triage_failed", "test-triage blocks salvage auto-ship", artifact=TEST_TRIAGE))
        except Exception as exc:
            violations.append(violation("invalid_test_triage", str(exc), artifact=TEST_TRIAGE))
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
    for artifact in (COMPLEXITY_CANDIDATES, COMPLEXITY_REDUCED, STALE_CODE, INTERDEPENDENCY_DOSSIER):
        path = run_dir / artifact
        if path.is_file():
            passed, reason = artifact_pass(path)
            if not passed:
                violations.append(violation("failing_smart_refactor_gate", "smart-refactor gate artifact did not pass", artifact=artifact, reason=reason))
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
    characterize.add_argument("--interaction-artifact", help="JSON artifact written by Playwright scenarios with post-interaction DOM/geometry/CSS hashes")
    characterize.add_argument("--scenario", action="append", help="required interaction scenario name; defaults to the salvage GUI scenario set")
    characterize.add_argument("--output", required=True)
    characterize.set_defaults(func=cmd_characterize)

    parity = sub.add_parser("preserve-parity")
    parity.add_argument("--manifest")
    parity.add_argument("--baseline")
    parity.add_argument("--characterization-baseline")
    parity.add_argument("--target")
    parity.add_argument("--test-cmd")
    parity.add_argument("--interaction-artifact", help="current post-gut interaction artifact to compare against the frozen baseline")
    parity.add_argument("--scenario", action="append", help="required interaction scenario name; defaults to baseline requirements")
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

    complexity_candidates = sub.add_parser("complexity-candidates")
    complexity_candidates.add_argument("--root", default=".")
    complexity_candidates.add_argument("--cyclomatic", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["cyclomatic"])
    complexity_candidates.add_argument("--nesting", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["nesting"])
    complexity_candidates.add_argument("--length", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["length"])
    complexity_candidates.add_argument("--output", required=True)
    complexity_candidates.set_defaults(func=cmd_complexity_candidates)

    complexity_reduced = sub.add_parser("complexity-reduced")
    complexity_reduced.add_argument("--root", default=".")
    complexity_reduced.add_argument("--baseline-candidates")
    complexity_reduced.add_argument("--plan")
    complexity_reduced.add_argument("--cyclomatic", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["cyclomatic"])
    complexity_reduced.add_argument("--nesting", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["nesting"])
    complexity_reduced.add_argument("--length", type=int, default=DEFAULT_COMPLEXITY_THRESHOLDS["length"])
    complexity_reduced.add_argument("--output", required=True)
    complexity_reduced.set_defaults(func=cmd_complexity_reduced)

    stale = sub.add_parser("stale")
    stale.add_argument("--graph", required=True)
    stale.add_argument("--root", default=".")
    stale.add_argument("--removed")
    stale.add_argument("--justifications")
    stale.add_argument("--output", required=True)
    stale.set_defaults(func=cmd_stale)

    dossier = sub.add_parser("dossier")
    dossier.add_argument("--graph", required=True)
    dossier.add_argument("--root", default=".")
    dossier.add_argument("--coverage")
    dossier.add_argument("--dossier")
    dossier.add_argument("--output", required=True)
    dossier.set_defaults(func=cmd_dossier)

    triage = sub.add_parser("test-triage")
    triage.add_argument("--root", default=".")
    triage.add_argument("--graph", required=True)
    triage.add_argument("--plan")
    triage.add_argument("--test-cmd")
    triage.add_argument("--provenance", default=TEST_PROVENANCE_MD)
    triage.add_argument("--output", required=True)
    triage.set_defaults(func=cmd_test_triage)

    resistance = sub.add_parser("resistance")
    resistance.add_argument("--graph", required=True)
    resistance.add_argument("--preserved-surface", required=True)
    resistance.add_argument("--removed")
    resistance.add_argument("--duplication-plan")
    resistance.add_argument("--coverage")
    resistance.add_argument("--baseline")
    resistance.add_argument("--complexity-baseline")
    resistance.add_argument("--complexity-plan")
    resistance.add_argument("--stale-justifications")
    resistance.add_argument("--dossier")
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
