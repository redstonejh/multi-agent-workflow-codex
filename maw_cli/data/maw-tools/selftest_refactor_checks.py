#!/usr/bin/env python3
"""Self-tests for refactor behavior-preservation checks."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


TOOL = Path(__file__).resolve().with_name("behavior_baseline.py")


def run(*args: str, cwd: Path) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd, capture_output=True, text=True)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"passed": False, "stdout": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def run_structure(root: Path, plan: dict) -> tuple[int, dict]:
    manifest = root / "structure-manifest.json"
    plan_path = root / "refactor-plan.json"
    output = root / "refactor-structure.json"
    write_json(manifest, {"source_paths": sorted(str(path.relative_to(root)) for path in root.rglob("*.py"))})
    write_json(plan_path, plan)
    return run("structure", "--plan", str(plan_path), "--manifest", str(manifest), "--root", str(root), "--output", str(output), cwd=root)


def run_complexity(root: Path, plan: dict, manifest: Path, baseline: Path) -> tuple[int, dict]:
    plan_path = root / "complexity-plan.json"
    output = root / "complexity-report.json"
    write_json(plan_path, plan)
    return run("complexity", "--plan", str(plan_path), "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(output), cwd=root)


def run_perf(root: Path, plan: dict, manifest: Path, baseline: Path) -> tuple[int, dict]:
    plan_path = root / "perf-plan.json"
    output = root / "perf-budget.json"
    write_json(plan_path, plan)
    return run("perf", "--plan", str(plan_path), "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(output), cwd=root)


def write_complexity_fixture(root: Path, variant: str) -> tuple[Path, Path]:
    source = root / "complexity_case.py"
    if variant == "base":
        text = '''def classify(value):
    if value > 10:
        if value > 20:
            return "large"
        return "medium"
    return "small"
'''
    elif variant == "simple":
        text = '''def classify(value):
    if value > 20:
        return "large"
    if value > 10:
        return "medium"
    return "small"
'''
    elif variant == "worse":
        text = '''def classify(value):
    if value > 0:
        if value > 10:
            if value > 20:
                return "large"
            return "medium"
        return "positive"
    return "small"
'''
    else:
        raise AssertionError(variant)
    source.write_text(text, encoding="utf-8")
    manifest = root / "complexity-manifest.json"
    write_json(manifest, {"source_paths": ["complexity_case.py"]})
    return source, manifest


def write_perf_fixture(root: Path, variant: str) -> tuple[Path, Path]:
    source = root / "perf_case.py"
    iterations = 12 if variant in {"base", "normal"} else 12000
    source.write_text(
        f'''def work():
    total = 0
    for index in range({iterations}):
        total += index
    return 7
''',
        encoding="utf-8",
    )
    manifest = root / "perf-manifest.json"
    write_json(
        manifest,
        {
            "performance_repeats": 3,
            "source_paths": ["perf_case.py"],
            "modules": ["perf_case"],
            "json": [{"name": "work", "expr": "perf_case.work()"}],
        },
    )
    return source, manifest


def write_structure_case(root: Path, refactor_type: str, bad: bool = False) -> dict:
    for path in root.glob("*.py"):
        path.unlink()
    if refactor_type == "rename":
        (root / "mod.py").write_text("def new_name():\n    return 1\n\nvalue = new_name()\n" + ("old_name = 2\n" if bad else ""), encoding="utf-8")
        return {"refactor_type": "rename", "structure": {"old_name": "old_name", "new_name": "new_name"}}
    if refactor_type == "extract-function":
        body = "return value * 2"
        if bad:
            (root / "mod.py").write_text("def caller(value):\n    return value * 2\n", encoding="utf-8")
        else:
            (root / "mod.py").write_text("def extracted(value):\n    doubled = value * 2\n    return doubled\n\ndef caller(value):\n    return extracted(value)\n", encoding="utf-8")
        return {"refactor_type": "extract-function", "structure": {"extracted_name": "extracted", "inlined_body_text": body}}
    if refactor_type == "inline":
        if bad:
            (root / "mod.py").write_text("def helper(x):\n    return x + 1\n\ndef caller(x):\n    return helper(x)\n", encoding="utf-8")
        else:
            (root / "mod.py").write_text("def caller(x):\n    return x + 1\n", encoding="utf-8")
        return {"refactor_type": "inline", "structure": {"symbol": "helper"}}
    if refactor_type == "move-module":
        if bad:
            (root / "old_mod.py").write_text("def moved():\n    return 1\n", encoding="utf-8")
        else:
            (root / "old_mod.py").write_text("from new_mod import moved\n", encoding="utf-8")
        (root / "new_mod.py").write_text("def moved():\n    return 1\n", encoding="utf-8")
        return {"refactor_type": "move-module", "structure": {"symbol": "moved", "old_path": "old_mod.py", "new_path": "new_mod.py", "compatibility_alias": not bad}}
    if refactor_type == "dedupe":
        if bad:
            (root / "mod.py").write_text("def survivor(x):\n    return x + 1\n\ndef duplicate(x):\n    return x + 1\n\ndef caller(x):\n    return duplicate(x)\n", encoding="utf-8")
        else:
            (root / "mod.py").write_text("def survivor(x):\n    return x + 1\n\ndef caller_a(x):\n    return survivor(x)\n\ndef caller_b(x):\n    value = survivor(x)\n    return value\n", encoding="utf-8")
        return {"refactor_type": "dedupe", "structure": {"survivor": "survivor", "baseline_duplicate_count": 2}}
    raise AssertionError(refactor_type)


def write_fixture(root: Path, variant: str = "base") -> tuple[Path, Path]:
    source = root / "surface.py"
    if variant == "base":
        text = '''import sys

__all__ = ["choose", "add", "constant", "Widget", "exit_status", "explode", "write_report"]

def choose(value, flag=True):
    if flag:
        return value + 1
    return value - 1

def add(a, b=2):
    return a + b

def constant():
    return 10

def exit_status():
    print("ok")
    print("warn", file=sys.stderr)
    return 0

def explode():
    raise ValueError("legacy message")

def write_report(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("stable-bytes")
    return path

class Widget:
    def __init__(self, value=3):
        self.value = value

    def label(self):
        return f"W{self.value}"
'''
    elif variant == "clean":
        text = '''import sys

__all__ = ["choose", "add", "constant", "Widget", "exit_status", "explode", "write_report"]

def choose(value, flag=True):
    if flag:
        return value + 1
    return value - 1

def add(a, b=2):
    total = a + b
    return total

def constant():
    return 10

def exit_status():
    print("ok")
    print("warn", file=sys.stderr)
    return 0

def explode():
    raise ValueError("legacy message")

def write_report(path):
    report = "stable-bytes"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(report)
    return path

class Widget:
    def __init__(self, value=3):
        self.value = value

    def label(self):
        text = f"W{self.value}"
        return text
'''
    elif variant == "uncovered":
        text = '''import sys

__all__ = ["choose", "add", "constant", "Widget", "exit_status", "explode", "write_report"]

def choose(value, flag=True):
    if flag:
        return value + 1
    return value - 1

def add(a, b=2):
    return a + b

def constant():
    return 10

def _hidden_uncovered():
    return 99

def exit_status():
    print("ok")
    print("warn", file=sys.stderr)
    return 0

def explode():
    raise ValueError("legacy message")

def write_report(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("stable-bytes")
    return path

class Widget:
    def __init__(self, value=3):
        self.value = value

    def label(self):
        return f"W{self.value}"
'''
    elif variant == "api":
        text = write_fixture_text_with_replacements("def add(a, b=2):", "def add(a, b=5):")
    elif variant == "exit":
        text = write_fixture_text_with_replacements("return 0", "return 1")
    elif variant == "exception":
        text = write_fixture_text_with_replacements("legacy message", "changed message")
    elif variant == "file_effect":
        text = write_fixture_text_with_replacements('handle.write("stable-bytes")', 'handle.write("changed-bytes")')
    else:
        raise AssertionError(variant)
    source.write_text(text, encoding="utf-8")
    manifest = root / "behavior-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "source_paths": ["surface.py"],
                "modules": ["surface"],
                "signatures": [{"module": "surface", "members": "public"}],
                "json": [
                    {"name": "choose-true", "expr": "surface.choose(4, True)"},
                    {"name": "choose-false", "expr": "surface.choose(4, False)"},
                    {"name": "add", "expr": "surface.add(4)"},
                    {"name": "constant", "expr": "surface.constant()"},
                    {"name": "widget", "expr": "surface.Widget().label()"},
                ],
                "processes": [
                    {"name": "exit-status", "command": ["{python}", "-c", "import surface, sys; raise SystemExit(surface.exit_status())"]}
                ],
                "exceptions": [
                    {"name": "explode", "expr": "surface.explode()"}
                ],
                "file_effects": [
                    {"name": "write-report", "expr": "surface.write_report('artifact.txt')", "files": ["artifact.txt"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    return source, manifest


def write_fixture_text_with_replacements(before: str, after: str) -> str:
    text = '''import sys

__all__ = ["choose", "add", "constant", "Widget", "exit_status", "explode", "write_report"]

def choose(value, flag=True):
    if flag:
        return value + 1
    return value - 1

def add(a, b=2):
    return a + b

def constant():
    return 10

def exit_status():
    print("ok")
    print("warn", file=sys.stderr)
    return 0

def explode():
    raise ValueError("legacy message")

def write_report(path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("stable-bytes")
    return path

class Widget:
    def __init__(self, value=3):
        self.value = value

    def label(self):
        return f"W{self.value}"
'''
    return text.replace(before, after)


def main() -> int:
    results: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        _source, manifest = write_fixture(root, "base")
        baseline = root / "behavior-baseline.json"
        code, data = run("capture", "--manifest", str(manifest), "--root", str(root), "--output", str(baseline), cwd=root)
        results.append({"name": "deterministic_capture", "passed": code == 0 and data.get("determinism", {}).get("passed") is True})

        write_fixture(root, "clean")
        diff = root / "behavior-diff.json"
        code, data = run("verify", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(diff), cwd=root)
        results.append({"name": "clean_refactor_behavior_passes", "passed": code == 0 and data.get("passed") is True})

        coverage = root / "refactor-coverage.json"
        code, data = run("coverage", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(coverage), cwd=root)
        results.append({"name": "changed_lines_covered", "passed": code == 0 and data.get("passed") is True})

        api = root / "api-surface-diff.json"
        code, data = run("api", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(api), cwd=root)
        results.append({"name": "api_stable_passes", "passed": code == 0 and data.get("passed") is True})

        resistance = root / "refactor-resistance.json"
        code, data = run("resistance", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(resistance), cwd=root)
        mutation_names = {item.get("name") for item in data.get("mutations", [])}
        results.append({"name": "planted_mutations_caught", "passed": code == 0 and data.get("summary", {}).get("caught") == data.get("summary", {}).get("total")})
        results.append({"name": "resistance_covers_new_probe_fields", "passed": {"process_exit_code", "exception_message", "file_effect_bytes"} <= mutation_names})

        write_fixture(root, "uncovered")
        code, data = run("coverage", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(coverage), cwd=root)
        results.append({"name": "uncovered_changed_line_fails", "passed": code != 0 and data.get("passed") is False and data.get("uncovered_count", 0) > 0})

        write_fixture(root, "api")
        code, data = run("api", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(api), cwd=root)
        results.append({"name": "silent_default_change_fails_api_gate", "passed": code != 0 and any(item.get("type") == "api_functions_changed" for item in data.get("diffs", []))})

        for variant, diff_type in (
            ("exit", "process_exit_code_changed"),
            ("exception", "exception_message_changed"),
            ("file_effect", "written_file_bytes_changed"),
        ):
            write_fixture(root, variant)
            code, data = run("verify", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(diff), cwd=root)
            results.append({"name": f"{variant}_change_fails_behavior_diff", "passed": code != 0 and any(item.get("type") == diff_type for item in data.get("diffs", []))})

        weak_manifest = root / "weak-manifest.json"
        weak_manifest.write_text(json.dumps({"source_paths": ["surface.py"], "modules": ["surface"]}), encoding="utf-8")
        weak_baseline = root / "weak-baseline.json"
        run("capture", "--manifest", str(weak_manifest), "--root", str(root), "--output", str(weak_baseline), cwd=root)
        write_fixture(root, "clean")
        code, data = run("resistance", "--manifest", str(weak_manifest), "--baseline", str(weak_baseline), "--root", str(root), "--output", str(resistance), cwd=root)
        results.append({"name": "baseline_that_catches_nothing_fails", "passed": code != 0 and data.get("passed") is False})

    for refactor_type in ("rename", "extract-function", "inline", "move-module", "dedupe"):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan = write_structure_case(root, refactor_type, bad=False)
            code, data = run_structure(root, plan)
            results.append({"name": f"structure_{refactor_type}_clean_passes", "passed": code == 0 and data.get("passed") is True and data.get("refactor_type") == refactor_type})

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            plan = write_structure_case(root, refactor_type, bad=True)
            code, data = run_structure(root, plan)
            results.append({"name": f"structure_{refactor_type}_planted_failure_fails", "passed": code != 0 and data.get("passed") is False and bool(data.get("violations"))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        _source, manifest = write_complexity_fixture(root, "base")
        baseline = root / "complexity-baseline.json"
        code, data = run("capture", "--manifest", str(manifest), "--root", str(root), "--output", str(baseline), cwd=root)
        results.append({"name": "complexity_baseline_captures", "passed": code == 0 and data.get("passed") is True})
        write_complexity_fixture(root, "simple")
        code, data = run_complexity(root, {"complexity_tolerance": 0}, manifest, baseline)
        results.append({"name": "complexity_simplification_passes", "passed": bool(code == 0 and data.get("passed") is True and data.get("functions"))})
        write_complexity_fixture(root, "worse")
        code, data = run_complexity(root, {"complexity_tolerance": 0}, manifest, baseline)
        results.append({"name": "complexity_planted_regression_fails", "passed": code != 0 and data.get("passed") is False and any(item.get("type") == "complexity_increase" for item in data.get("violations", []))})

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        _source, manifest = write_perf_fixture(root, "base")
        baseline = root / "perf-baseline.json"
        code, data = run("capture", "--manifest", str(manifest), "--root", str(root), "--output", str(baseline), cwd=root)
        results.append({"name": "perf_baseline_captures", "passed": bool(code == 0 and data.get("metadata", {}).get("performance", {}).get("probes"))})
        write_perf_fixture(root, "normal")
        code, data = run_perf(root, {"performance_budget": {"repeats": 3, "max_regression_ratio": 10.0}}, manifest, baseline)
        results.append({"name": "perf_normal_variance_passes", "passed": bool(code == 0 and data.get("passed") is True and data.get("probes"))})
        write_perf_fixture(root, "slow")
        code, data = run_perf(root, {"performance_budget": {"repeats": 3, "max_regression_ratio": 2.0, "clear_regression_ratio": 3.0}}, manifest, baseline)
        results.append({"name": "perf_planted_slow_path_fails", "passed": code != 0 and data.get("passed") is False and any(item.get("type") in {"wall_time_regression", "line_count_regression"} for item in data.get("violations", []))})

    ok = sum(1 for item in results if item["passed"])
    result = {"passed": ok == len(results), "checks": len(results), "ok": ok, "results": results}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
