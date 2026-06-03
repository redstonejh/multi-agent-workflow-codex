#!/usr/bin/env python3
"""Self-tests for salvage refactor hard gates."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
GRAPH = TOOLS / "code_graph_py.py"
GRAPH_HTML = TOOLS / "code_graph_html.py"
SALVAGE = TOOLS / "salvage_check.py"
BEHAVIOR = TOOLS / "behavior_baseline.py"
MAW = ROOT / "maw.py"


def run_json(command: list[str], cwd: Path) -> tuple[int, dict]:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_source(root: Path, variant: str) -> None:
    if variant == "clean":
        text = '''
STATE = {"offset": 1}

def keep(value):
    return survivor(value)

def survivor(value):
    return value + 1
'''
    elif variant == "dirty":
        text = '''
STATE = {"offset": 1}

def keep(value):
    return duplicate(value)

def survivor(value):
    return value + 1

def duplicate(value):
    return value + 1

def mutates_state(value):
    global STATE
    STATE = {"offset": value}
    return STATE["offset"]
'''
    elif variant == "live_dead":
        text = '''
def keep(value):
    return removed(value)

def removed(value):
    return value - 1
'''
    elif variant == "parity_break":
        text = '''
STATE = {"offset": 1}

def keep(value):
    return survivor(value) + 10

def survivor(value):
    return value + 1
'''
    else:
        raise AssertionError(variant)
    (root / "legacy.py").write_text(text.lstrip(), encoding="utf-8")


def code_graph(root: Path, output: Path, entrypoint: str = "legacy:keep") -> dict:
    code, data = run_json([sys.executable, str(GRAPH), str(root), "--entrypoint", entrypoint, "--output", str(output)], root)
    assert code == 0, data
    return data


def behavior_manifest(root: Path) -> Path:
    path = root / "behavior-manifest.json"
    write_json(path, {"source_paths": ["legacy.py"], "modules": ["legacy"], "json": [{"name": "keep", "expr": "legacy.keep(4)"}]})
    return path


def capture_baseline(root: Path, manifest: Path, output: Path) -> dict:
    code, data = run_json([sys.executable, str(BEHAVIOR), "capture", "--manifest", str(manifest), "--root", str(root), "--output", str(output)], root)
    assert code == 0, data
    return data


def write_surface(path: Path, entrypoints: list[str] | None = None) -> None:
    write_json(path, {"entrypoints": entrypoints or ["legacy:keep"], "entrypoints_before": entrypoints or ["legacy:keep"]})


def write_web_fixture(root: Path) -> None:
    (root / "templates").mkdir()
    (root / "static").mkdir()
    (root / "templates" / "index.html").write_text(
        """<!doctype html>
<html lang="en">
<head><title>Keep</title><link rel="stylesheet" href="../static/app.css"></head>
<body>
  <main id="keep-root" class="screen" data-action="save">{{ user.name }}</main>
  <form action="/api/save"><input name="token" value="abc"></form>
  <script src="../static/app.js"></script>
</body>
</html>
""",
        encoding="utf-8",
    )
    (root / "static" / "app.css").write_text("#keep-root { color: #111111; }\n.screen { display: block; }\n", encoding="utf-8")
    (root / "static" / "app.js").write_text("document.querySelector('#keep-root').addEventListener('click', () => fetch('/api/save'));\n", encoding="utf-8")
    (root / "app.py").write_text("def save():\n    return {'token': 'abc'}\n", encoding="utf-8")


def hidden_dep_ids(graph: dict, root: Path) -> list[str]:
    output = root / "hidden.json"
    _code, data = run_json([sys.executable, str(SALVAGE), "hidden-deps", "--graph", str(root / "code-graph.json"), "--root", str(root), "--output", str(output)], root)
    return sorted(item["id"] for item in data.get("couplings", []))


def main() -> int:
    results: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_source(root, "clean")
        graph_path = root / "code-graph.json"
        graph = code_graph(root, graph_path)
        ids = hidden_dep_ids(graph, root)
        source = root / "legacy.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n" + "\n".join(f"# MAW-DEP[{dep_id}]: fixture survivor call is preserved" for dep_id in ids) + "\n", encoding="utf-8")
        coverage = root / "hidden-deps-tests.json"
        write_json(coverage, {"covered_dependencies": ids})
        surface = root / "preserved-surface.json"
        write_surface(surface)
        manifest = behavior_manifest(root)
        baseline = root / "behavior-baseline.json"
        capture_baseline(root, manifest, baseline)
        parity = root / "preserve-parity.json"
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--manifest", str(manifest), "--baseline", str(baseline), "--preserved-surface", str(surface), "--root", str(root), "--output", str(parity)], root)
        results.append({"name": "parity_clean_passes", "passed": code == 0 and data.get("passed") is True})
        write_source(root, "parity_break")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--manifest", str(manifest), "--baseline", str(baseline), "--preserved-surface", str(surface), "--root", str(root), "--output", str(parity)], root)
        results.append({"name": "parity_break_fails", "passed": code != 0 and any(item.get("type") == "preserved_surface_behavior_drift" for item in data.get("violations", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_web_fixture(root)
        topology = root / "topology.json"
        code, data = run_json([sys.executable, str(SALVAGE), "topology", str(root), "--output", str(topology)], root)
        results.append({"name": "topology_templated_monolith_detected", "passed": code == 0 and data.get("topology") == "templated_monolith"})
        graph_path = root / "html-code-graph.json"
        code, data = run_json([sys.executable, str(GRAPH_HTML), str(root), "--output", str(graph_path)], root)
        edge_types = {item.get("type") for item in data.get("edges", [])}
        results.append({"name": "html_css_graph_emits_salvage_edges", "passed": code == 0 and {"dom_ref", "css_ref", "template_var", "asset_ref"} <= edge_types})
        surface = root / "preserved-surface.json"
        entrypoints = [item["id"] for item in data.get("symbols", []) if item.get("name") == "#keep-root"][:1]
        write_surface(surface, entrypoints or ["dom:#keep-root"])
        baseline = root / "characterization-baseline.json"
        code, data = run_json([sys.executable, str(SALVAGE), "characterize", str(root), "--output", str(baseline)], root)
        results.append({"name": "characterization_baseline_captures_files", "passed": code == 0 and data.get("passed") is True and len(data.get("items", [])) >= 2})
        parity = root / "preserve-parity.json"
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "characterization_parity_clean_passes", "passed": code == 0 and data.get("passed") is True})
        (root / "static" / "app.css").write_text("#keep-root { color: #222222; }\n.screen { display: block; }\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "characterization_parity_drift_fails", "passed": code != 0 and any(item.get("type") == "preserved_surface_behavior_drift" for item in data.get("violations", []))})
        cross = root / "cross-lang-couplings.json"
        code, data = run_json([sys.executable, str(SALVAGE), "cross-lang", "--graph", str(graph_path), "--root", str(root), "--output", str(cross)], root)
        results.append({"name": "cross_lang_undocumented_coupling_fails", "passed": code != 0 and any(item.get("type") == "undocumented_cross_language_coupling" for item in data.get("violations", []))})
        ids = sorted(item["id"] for item in data.get("couplings", []))
        coverage = root / "hidden-deps-tests.json"
        write_json(coverage, {"dismissed_couplings": {dep_id: "" for dep_id in ids}})
        code, data = run_json([sys.executable, str(SALVAGE), "cross-lang", "--graph", str(graph_path), "--root", str(root), "--coverage", str(coverage), "--output", str(cross)], root)
        results.append({"name": "cross_lang_empty_dismissal_fails", "passed": code != 0 and any(item.get("type") == "cross_language_coupling_dismissed_without_justification" for item in data.get("violations", []))})
        write_json(coverage, {"dismissed_couplings": {dep_id: "static fixture coupling accepted by characterization replay" for dep_id in ids}})
        code, data = run_json([sys.executable, str(SALVAGE), "cross-lang", "--graph", str(graph_path), "--root", str(root), "--coverage", str(coverage), "--output", str(cross)], root)
        results.append({"name": "cross_lang_justified_dismissal_passes", "passed": code == 0 and data.get("passed") is True})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_source(root, "dirty")
        graph_path = root / "code-graph.json"
        graph = code_graph(root, graph_path)
        hidden = root / "hidden-deps.json"
        code, data = run_json([sys.executable, str(SALVAGE), "hidden-deps", "--graph", str(graph_path), "--root", str(root), "--output", str(hidden)], root)
        results.append({"name": "undocumented_dep_fails", "passed": code != 0 and any(item.get("type") == "undocumented_hidden_dependency" for item in data.get("violations", []))})
        ids = sorted(item["id"] for item in data.get("couplings", []))
        source = root / "legacy.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n" + "\n".join(f"# MAW-DEP[{dep_id}]: fixture dependency" for dep_id in ids) + "\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "hidden-deps", "--graph", str(graph_path), "--root", str(root), "--output", str(hidden)], root)
        results.append({"name": "untested_dep_fails", "passed": code != 0 and any(item.get("type") == "untested_hidden_dependency" for item in data.get("violations", []))})
        coverage = root / "hidden-deps-tests.json"
        write_json(coverage, {"covered_dependencies": ids})
        code, data = run_json([sys.executable, str(SALVAGE), "hidden-deps", "--graph", str(graph_path), "--root", str(root), "--coverage", str(coverage), "--output", str(hidden)], root)
        results.append({"name": "documented_tested_dep_passes", "passed": code == 0 and data.get("passed") is True})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_source(root, "live_dead")
        graph_path = root / "code-graph.json"
        code_graph(root, graph_path)
        surface = root / "preserved-surface.json"
        write_surface(surface)
        removed = root / "removed-symbols.json"
        write_json(removed, {"removed_symbols": ["legacy:removed"]})
        dead = root / "dead-code.json"
        code, data = run_json([sys.executable, str(SALVAGE), "dead-code", "--graph", str(graph_path), "--preserved-surface", str(surface), "--removed", str(removed), "--output", str(dead)], root)
        results.append({"name": "live_dead_symbol_fails", "passed": code != 0 and any(item.get("type") == "removed_symbol_reachable" for item in data.get("violations", []))})
        write_source(root, "clean")
        code_graph(root, graph_path)
        code, data = run_json([sys.executable, str(SALVAGE), "dead-code", "--graph", str(graph_path), "--preserved-surface", str(surface), "--removed", str(removed), "--output", str(dead)], root)
        results.append({"name": "unreachable_removed_symbol_passes", "passed": code == 0 and data.get("passed") is True})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_source(root, "dirty")
        graph_path = root / "code-graph.json"
        code_graph(root, graph_path)
        plan = root / "duplication-plan.json"
        write_json(plan, {"groups": [{"survivor": "legacy:survivor", "duplicates": ["legacy:duplicate"], "rerouted_call_sites": ["legacy:keep"]}]})
        output = root / "duplication.json"
        code, data = run_json([sys.executable, str(SALVAGE), "duplication", "--graph", str(graph_path), "--plan", str(plan), "--output", str(output)], root)
        results.append({"name": "surviving_duplicate_fails", "passed": code != 0 and any(item.get("type") == "duplicate_symbol_survived" for item in data.get("violations", []))})
        write_source(root, "clean")
        code_graph(root, graph_path)
        code, data = run_json([sys.executable, str(SALVAGE), "duplication", "--graph", str(graph_path), "--plan", str(plan), "--output", str(output)], root)
        results.append({"name": "collapsed_duplicate_passes", "passed": code == 0 and data.get("passed") is True})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_source(root, "clean")
        graph_path = root / "code-graph.json"
        graph = code_graph(root, graph_path)
        ids = hidden_dep_ids(graph, root)
        source = root / "legacy.py"
        source.write_text(source.read_text(encoding="utf-8") + "\n" + "\n".join(f"# MAW-DEP[{dep_id}]: fixture survivor call is preserved" for dep_id in ids) + "\n", encoding="utf-8")
        coverage = root / "hidden-deps-tests.json"
        write_json(coverage, {"covered_dependencies": ids})
        surface = root / "preserved-surface.json"
        write_surface(surface)
        manifest = behavior_manifest(root)
        baseline = root / "behavior-baseline.json"
        capture_baseline(root, manifest, baseline)
        removed = root / "removed-symbols.json"
        write_json(removed, {"removed_symbols": ["legacy:removed"]})
        plan = root / "duplication-plan.json"
        write_json(plan, {"groups": [{"survivor": "legacy:survivor", "duplicates": ["legacy:duplicate"], "rerouted_call_sites": ["legacy:keep"]}]})
        output = root / "salvage-resistance.json"
        code, data = run_json([sys.executable, str(SALVAGE), "resistance", "--graph", str(graph_path), "--preserved-surface", str(surface), "--removed", str(removed), "--duplication-plan", str(plan), "--coverage", str(coverage), "--baseline", str(baseline), "--root", str(root), "--output", str(output)], root)
        names = {item.get("name"): item.get("caught") for item in data.get("mutations", [])}
        expected = {"reintroduced_hidden_dependency", "resurrected_dead_reference", "reduplicated_function", "server_preserved_surface_behavior_break", "client_preserved_surface_behavior_break", "broken_cross_language_coupling", "surface_shrink_gaming"}
        results.append({"name": "resistance_catches_all_salvage_mutations", "passed": code == 0 and data.get("passed") is True and expected <= set(names) and all(names.get(name) is True for name in expected)})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        run_dir = root / "run"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        write_surface(artifacts / "preserved-surface.json", ["legacy:keep", "legacy:survivor"])
        (artifacts / "preserved-surface.sha256").write_text(hashlib.sha256((artifacts / "preserved-surface.json").read_bytes()).hexdigest() + "\n", encoding="utf-8")
        write_json(artifacts / "code-graph.json", {"schema_version": 1, "entrypoints": ["legacy:keep"], "modules": [], "symbols": [], "edges": [], "passed": True})
        for name in ("preserve-parity.json", "hidden-deps.json", "dead-code.json", "duplication.json", "salvage-resistance.json"):
            write_json(artifacts / name, {"check": name[:-5], "schema_version": 1, "passed": True, "proof": {"entrypoints": ["legacy:keep", "legacy:survivor"]}})
        code, data = run_json([sys.executable, str(SALVAGE), "verdict", str(run_dir)], root)
        results.append({"name": "surface_shrink_gaming_fails", "passed": code != 0 and any(item.get("type") == "code_graph_entrypoints_differ_from_frozen_surface" for item in data.get("violations", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        output = Path(tmp_dir) / "js-code-graph.json"
        code, data = run_json([sys.executable, str(MAW), "code-graph", str(ROOT / "examples" / "salvage_js_ts"), "--lang", "ts", "--output", str(output)], ROOT)
        valid_graph = code == 0 and data.get("schema_version") == 1 and data.get("passed") is True and bool(data.get("symbols"))
        clean_needs_human = code != 0 and data.get("status") == "NEEDS-HUMAN" and isinstance(data.get("errors"), list)
        results.append({"name": "js_ts_adapter_emits_graph_or_needs_human", "passed": valid_graph or clean_needs_human})

    topology_root = ROOT / "examples" / "salvage_topologies"
    for fixture, expected_topology in (
        ("templated_monolith", "templated_monolith"),
        ("spa_api", "spa_api"),
        ("vanilla", "vanilla"),
    ):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "topology.json"
            code, data = run_json([sys.executable, str(SALVAGE), "topology", str(topology_root / fixture), "--output", str(output)], ROOT)
            results.append({"name": f"fixture_topology_{fixture}", "passed": code == 0 and data.get("topology") == expected_topology})

    with tempfile.TemporaryDirectory() as tmp_dir:
        output = Path(tmp_dir) / "browser-characterization.json"
        code, data = run_json([sys.executable, str(MAW), "characterize", "http://127.0.0.1:9", "--browser", "--output", str(output)], ROOT)
        results.append({"name": "browser_capture_emits_or_needs_human", "passed": (code == 0 and data.get("passed") is True) or (code != 0 and data.get("status") == "NEEDS-HUMAN" and isinstance(data.get("errors"), list))})

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "checks": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
