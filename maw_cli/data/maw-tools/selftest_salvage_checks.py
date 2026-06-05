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


def write_surface(path: Path, entrypoints: list[str] | None = None, source_paths: list[str] | None = None) -> None:
    payload = {"entrypoints": entrypoints or ["legacy:keep"], "entrypoints_before": entrypoints or ["legacy:keep"]}
    if source_paths is not None:
        payload["source_paths"] = source_paths
    write_json(path, payload)


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


def write_interaction_artifact(path: Path, mutate: str | None = None, omit: str | None = None) -> None:
    scenarios = [
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
    write_json(
        path,
        {
            "scenarios": [
                {
                    "name": name,
                    "passed": False if name == mutate else True,
                    "dom_sha256": hashlib.sha256(f"{name}:dom".encode()).hexdigest(),
                    "geometry_sha256": hashlib.sha256((f"{name}:handler-missing" if name == mutate else f"{name}:geometry").encode()).hexdigest(),
                    "computed_css_sha256": hashlib.sha256(f"{name}:css".encode()).hexdigest(),
                }
                for name in scenarios
                if name != omit
            ]
        },
    )


def structured_scenario(name: str, mutation: str | None = None) -> dict:
    geometry = [
        {"key": "widget-mpyo8rhs-s1ld5", "type": "widget", "rect": {"left": 10, "top": 20, "width": 100, "height": 50}},
        {"key": "widget-beta", "type": "widget", "rect": {"left": 120, "top": 20, "width": 100, "height": 50}},
        {"key": "panel-gamma", "type": "panel", "rect": {"left": 10, "top": 90, "width": 220, "height": 80}},
        {"key": "panel-delta", "type": "panel", "rect": {"left": 10, "top": 190, "width": 220, "height": 80}},
    ]
    css = [
        {"selector": ".db-panel", "color": "rgb(31, 41, 55)", "backgroundColor": "oklab(0.900 0.010 0.010)"},
        {"selector": ".widget-card", "color": "#ffffff", "backgroundColor": "rgb(10, 20, 30)"},
    ]
    extra = {"edge": {"scrollY": 38}} if name == "edge-auto-scroll" else {}
    dom = {"objects": [{"key": item["key"], "text": item["key"]} for item in geometry]}
    if mutation == "noise":
        geometry[0]["rect"]["top"] += 1
        css[0]["backgroundColor"] = "oklab(0.901 0.010 0.010)"
    elif mutation == "edge_scroll":
        geometry = [{**item, "rect": {**item["rect"], "top": item["rect"]["top"] + 9}} for item in geometry]
        extra = {"edge": {"scrollY": 47}}
    elif mutation == "single_move":
        geometry[0]["rect"]["left"] += 3
    elif mutation == "css_drift":
        css[1]["backgroundColor"] = "rgb(80, 20, 30)"
    elif mutation == "generated_ids":
        geometry[0]["key"] = "widget-mpyoq0lt-0vi9l"
        dom["objects"][0]["key"] = "widget-mpyoq0lt-0vi9l"
    return {"name": name, "passed": True, "evidence": {"dom": dom, "geometry": geometry, "computed_css": css}, "extra": extra}


def write_structured_interaction_artifact(path: Path, mutation: str | None = None, omit: str | None = None) -> None:
    scenarios = [
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
    mutation_target = {
        "noise": "collapse",
        "edge_scroll": "edge-auto-scroll",
        "single_move": "drag-with-live-ghost",
        "css_drift": "recolor",
        "generated_ids": "rename",
    }.get(mutation)
    write_json(path, {"scenarios": [structured_scenario(name, mutation if name == mutation_target else None) for name in scenarios if name != omit]})


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
        static_only_failed = code != 0 and any("interaction" in str(error) for error in data.get("errors", []))
        interaction = root / "interaction-baseline.json"
        write_interaction_artifact(interaction)
        cmd = f"{sys.executable} -c \"print('interaction ok')\""
        code, data = run_json([sys.executable, str(SALVAGE), "characterize", str(root), "--test-cmd", cmd, "--interaction-artifact", str(interaction), "--output", str(baseline)], root)
        results.append({"name": "characterization_baseline_captures_files", "passed": static_only_failed and code == 0 and data.get("passed") is True and data.get("interaction_scenario_count") == 13})
        parity = root / "preserve-parity.json"
        current_interaction = root / "interaction-current.json"
        write_interaction_artifact(current_interaction)
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current_interaction), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "characterization_parity_clean_passes", "passed": code == 0 and data.get("passed") is True})
        results.append({"name": "hollow_port_reproduced_interactions_pass", "passed": code == 0 and data.get("passed") is True})
        hollow_interaction = root / "interaction-hollow.json"
        write_interaction_artifact(hollow_interaction, mutate="drag-with-live-ghost")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(hollow_interaction), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "hollow_port_static_identical_missing_interactions_fails", "passed": code != 0 and any(item.get("type") == "preserved_surface_behavior_drift" for item in data.get("violations", []))})
        (root / "static" / "app.css").write_text("#keep-root { color: #222222; }\n.screen { display: block; }\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current_interaction), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "characterization_parity_ignores_static_css_hash_drift", "passed": code == 0 and data.get("passed") is True})
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
        write_web_fixture(root)
        graph_path = root / "html-code-graph.json"
        code, graph_data = run_json([sys.executable, str(GRAPH_HTML), str(root), "--output", str(graph_path)], root)
        surface = root / "preserved-surface.json"
        write_surface(surface, [item["id"] for item in graph_data.get("symbols", []) if item.get("name") == "#keep-root"][:1] or ["dom:#keep-root"])
        baseline = root / "characterization-baseline.json"
        baseline_interaction = root / "structured-baseline.json"
        write_structured_interaction_artifact(baseline_interaction)
        cmd = f"{sys.executable} -c \"import time; print('Running 2 tests'); print('2 passed (' + str(time.time()) + 's)')\""
        code, data = run_json([sys.executable, str(SALVAGE), "characterize", str(root), "--test-cmd", cmd, "--interaction-artifact", str(baseline_interaction), "--output", str(baseline)], root)
        current = root / "structured-current.json"
        write_structured_interaction_artifact(current)
        parity = root / "preserve-parity.json"
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "characterization_parity_ignores_stdout_timing_only", "passed": code == 0 and data.get("passed") is True and data.get("diff_count") == 0})
        write_structured_interaction_artifact(current, mutation="noise")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "field_parity_tolerates_single_px_and_subepsilon_color_noise", "passed": code == 0 and data.get("passed") is True})
        write_structured_interaction_artifact(current, mutation="edge_scroll")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "field_parity_catches_edge_scroll_viewport_drift", "passed": code != 0 and any(item.get("diff", {}).get("type") == "viewport_scroll_drift" for item in data.get("violations", []))})
        write_structured_interaction_artifact(current, mutation="single_move")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "field_parity_catches_real_single_object_move", "passed": code != 0 and any(item.get("diff", {}).get("type") == "field_drift" for item in data.get("violations", []))})
        write_structured_interaction_artifact(current, mutation="css_drift")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "field_parity_catches_real_computed_css_drift", "passed": code != 0 and any(item.get("diff", {}).get("path", "").startswith("evidence.computed_css") for item in data.get("violations", []))})
        write_structured_interaction_artifact(current, mutation="generated_ids")
        code, data = run_json([sys.executable, str(SALVAGE), "preserve-parity", "--characterization-baseline", str(baseline), "--target", str(root), "--test-cmd", cmd, "--interaction-artifact", str(current), "--preserved-surface", str(surface), "--output", str(parity)], root)
        results.append({"name": "field_parity_normalizes_generated_ids", "passed": code == 0 and data.get("passed") is True})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_json(
            root / "code-graph.json",
            {
                "modules": [{"id": "app", "path": "app.py", "language": "python"}],
                "symbols": [
                    {"id": "app:keep_feature", "module_id": "app", "name": "keep_feature", "qualname": "keep_feature", "kind": "function"},
                    {"id": "app:another_keep", "module_id": "app", "name": "another_keep", "qualname": "another_keep", "kind": "function"},
                ],
                "edges": [],
                "entrypoints": ["app:keep_feature", "app:another_keep"],
            },
        )
        write_json(root / "salvage-plan.json", {"keep": ["keep_feature", "another_keep"], "cut": ["cut_feature", "removed_symbol"]})
        (root / "test_active.py").write_text("def test_keep_feature():\n    keep_feature()\n", encoding="utf-8")
        (root / "test_cut.py").write_text("def test_cut_feature():\n    cut_feature()\n", encoding="utf-8")
        (root / "test_legacy.py").write_text("import pytest\n@pytest.mark.skip(reason='removed legacy')\ndef test_removed_symbol():\n    removed_symbol()\n", encoding="utf-8")
        runner = root / "runner.py"
        runner.write_text(
            "import json, sys\nfrom pathlib import Path\nPath('executed.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\nsys.exit(0)\n",
            encoding="utf-8",
        )
        triage = root / "test-triage.json"
        provenance = root / "test-provenance.md"
        code, data = run_json([sys.executable, str(SALVAGE), "test-triage", "--root", str(root), "--graph", str(root / "code-graph.json"), "--plan", str(root / "salvage-plan.json"), "--test-cmd", f"{sys.executable} {runner} {{tests}}", "--provenance", str(provenance), "--output", str(triage)], root)
        executed = json.loads((root / "executed.json").read_text(encoding="utf-8"))
        results.append({"name": "test_triage_active_keep_executes", "passed": code == 0 and any("test_active.py::test_keep_feature" in item for item in executed)})
        results.append({"name": "test_triage_cut_bound_scrapped_unexecuted", "passed": code == 0 and not any("test_cut.py::test_cut_feature" in item for item in executed) and any(test.get("id", "").endswith("test_cut.py::test_cut_feature") for test in data.get("scrap_tests", []))})
        results.append({"name": "test_triage_legacy_do_not_resurrect_recorded", "passed": code == 0 and "removed_symbol" in data.get("do_not_resurrect", []) and provenance.is_file()})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_json(root / "code-graph.json", {"modules": [], "symbols": [{"id": "app:keep_feature", "module_id": "app", "name": "keep_feature", "qualname": "keep_feature", "kind": "function"}], "edges": [], "entrypoints": ["app:keep_feature"]})
        write_json(root / "salvage-plan.json", {"keep": ["keep_feature"], "cut": ["cut_feature"]})
        (root / "test_mixed.py").write_text("def test_mixed():\n    keep_feature(); cut_feature()\n", encoding="utf-8")
        triage = root / "test-triage.json"
        code, data = run_json([sys.executable, str(SALVAGE), "test-triage", "--root", str(root), "--graph", str(root / "code-graph.json"), "--plan", str(root / "salvage-plan.json"), "--output", str(triage)], root)
        results.append({"name": "test_triage_mixed_not_scrapped_blocks", "passed": code != 0 and data.get("status") == "NEEDS-HUMAN" and any(test.get("partition") == "MIXED" for test in data.get("mixed_tests", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_json(root / "code-graph.json", {"modules": [], "symbols": [{"id": "app:keep_feature", "module_id": "app", "name": "keep_feature", "qualname": "keep_feature", "kind": "function"}], "edges": [], "entrypoints": ["app:keep_feature"]})
        write_json(root / "salvage-plan.json", {"keep": ["keep_feature"], "cut": []})
        (root / "test_failing_live.py").write_text("def test_failing_live():\n    keep_feature()\n", encoding="utf-8")
        runner = root / "runner.py"
        runner.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "test-triage", "--root", str(root), "--graph", str(root / "code-graph.json"), "--plan", str(root / "salvage-plan.json"), "--test-cmd", f"{sys.executable} {runner} {{tests}}", "--output", str(root / "test-triage.json")], root)
        results.append({"name": "test_triage_failing_live_keep_is_regression", "passed": code != 0 and any(item.get("type") == "active_keep_tests_failed" for item in data.get("violations", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_json(root / "code-graph.json", {"modules": [], "symbols": [{"id": "legacy:removed_symbol", "module_id": "legacy", "name": "removed_symbol", "qualname": "removed_symbol", "kind": "function"}], "edges": [], "entrypoints": ["legacy:removed_symbol"]})
        (root / "test_legacy.py").write_text("import pytest\n@pytest.mark.skip(reason='removed legacy')\ndef test_removed_symbol():\n    removed_symbol()\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "test-triage", "--root", str(root), "--graph", str(root / "code-graph.json"), "--output", str(root / "test-triage.json")], root)
        results.append({"name": "test_triage_resurrected_legacy_test_trips", "passed": code != 0 and any(item.get("type") == "legacy_symbol_resurrected" for item in data.get("violations", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        write_json(root / "code-graph.json", {"modules": [], "symbols": [{"id": "app:keep_feature", "module_id": "app", "name": "keep_feature", "qualname": "keep_feature", "kind": "function"}], "edges": [], "entrypoints": ["app:keep_feature"]})
        write_json(root / "salvage-plan.json", {"keep": ["keep_feature"], "cut": ["cut_feature"]})
        (root / "test_sole_coverage.py").write_text("def test_sole_coverage():\n    keep_feature(); cut_feature()\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "test-triage", "--root", str(root), "--graph", str(root / "code-graph.json"), "--plan", str(root / "salvage-plan.json"), "--output", str(root / "test-triage.json")], root)
        results.append({"name": "test_triage_dropped_sole_keep_coverage_trips", "passed": code != 0 and any(item.get("type") == "dropped_sole_keep_coverage" for item in data.get("violations", []))})

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
        run_dir = root / "run"
        artifacts = run_dir / "artifacts"
        artifacts.mkdir(parents=True)
        graph = {
            "schema_version": 1,
            "passed": True,
            "entrypoints": ["ui:start"],
            "modules": [{"id": "ui", "path": "src/ui.js", "language": "javascript"}],
            "symbols": [{"id": "ui:start", "module_id": "ui", "name": "start", "kind": "function"}],
            "edges": [],
        }
        write_json(artifacts / "code-graph.json", graph)
        write_surface(artifacts / "preserved-surface.json", ["ui:start"], [])
        (artifacts / "preserved-surface.sha256").write_text(hashlib.sha256((artifacts / "preserved-surface.json").read_bytes()).hexdigest() + "\n", encoding="utf-8")
        for name in ("topology.json", "test-triage.json", "characterization-baseline.json", "preserve-parity.json", "hidden-deps.json", "cross-lang-couplings.json", "duplication.json", "complexity-candidates.json", "complexity-reduced.json", "stale-code.json", "interdependency-dossier.json", "salvage-resistance.json"):
            write_json(artifacts / name, {"check": name[:-5], "schema_version": 1, "passed": True})
        write_json(artifacts / "dead-code.json", {"check": "dead-code", "schema_version": 1, "passed": True, "proof": {"entrypoints": ["ui:start"]}})
        code, data = run_json([sys.executable, str(SALVAGE), "verdict", str(run_dir)], root)
        results.append({"name": "reachable_source_path_missing_fails_surface_freeze", "passed": code != 0 and any(item.get("type") == "preserved_surface_missing_reachable_source_paths" and item.get("missing") == ["src/ui.js"] for item in data.get("violations", []))})
        write_surface(artifacts / "preserved-surface.json", ["ui:start"], ["src/ui.js"])
        (artifacts / "preserved-surface.sha256").write_text(hashlib.sha256((artifacts / "preserved-surface.json").read_bytes()).hexdigest() + "\n", encoding="utf-8")
        code, data = run_json([sys.executable, str(SALVAGE), "verdict", str(run_dir)], root)
        results.append({"name": "reachable_source_path_complete_passes_surface_freeze", "passed": code == 0 and data.get("passed") is True})

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
        baseline = root / "characterization-baseline.json"
        interaction = root / "interaction-baseline.json"
        write_interaction_artifact(interaction)
        cmd = f"{sys.executable} -c \"print('interaction ok')\""
        code, data = run_json([sys.executable, str(SALVAGE), "characterize", str(root), "--test-cmd", cmd, "--interaction-artifact", str(interaction), "--output", str(baseline)], root)
        assert code == 0, data
        removed = root / "removed-symbols.json"
        write_json(removed, {"removed_symbols": ["legacy:removed"]})
        plan = root / "duplication-plan.json"
        write_json(plan, {"groups": [{"survivor": "legacy:survivor", "duplicates": ["legacy:duplicate"], "rerouted_call_sites": ["legacy:keep"]}]})
        output = root / "salvage-resistance.json"
        code, data = run_json([sys.executable, str(SALVAGE), "resistance", "--graph", str(graph_path), "--preserved-surface", str(surface), "--removed", str(removed), "--duplication-plan", str(plan), "--coverage", str(coverage), "--baseline", str(baseline), "--root", str(root), "--output", str(output)], root)
        names = {item.get("name"): item.get("caught") for item in data.get("mutations", [])}
        expected = {"reintroduced_hidden_dependency", "resurrected_dead_reference", "reduplicated_function", "server_preserved_surface_behavior_break", "client_preserved_surface_behavior_break", "broken_cross_language_coupling", "surface_shrink_gaming", "edge_scroll_viewport_drift", "real_single_object_move", "resurrected_legacy_test", "dropped_sole_keep_coverage"}
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
