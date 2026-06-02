from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "maw-tools" / "scaffold_run.py"
CHECKS = ROOT / "maw-tools" / "checks.py"
VALIDATE = ROOT / "maw-tools" / "validate_handoffs.py"
ACCEPTANCE = ROOT / "maw-tools" / "acceptance_check.py"
VERDICT_CHECK = ROOT / "maw-tools" / "verdict_check.py"
TASK_GRAPH = ROOT / "maw-tools" / "task_graph.py"
WORKFLOW_TEMPLATE = ROOT / "maw-tools" / "validate_workflow_template.py"
START_WORKFLOW = ROOT / "maw-tools" / "start_workflow.py"
DEPENDENCY_AUDIT = ROOT / "maw-tools" / "dependency_risk_audit.py"
PLAN_CHECK = ROOT / "maw-tools" / "plan_check.py"
BEHAVIOR_BASELINE = ROOT / "maw-tools" / "behavior_baseline.py"
MAW = ROOT / "maw.py"
PYPROJECT = ROOT / "pyproject.toml"
ML_CHECKS = ROOT / "examples" / "ml_problems" / "ml_checks.py"
ML_CLASSIFICATION = ROOT / "examples" / "ml_problems" / "classification" / "run.py"
ML_REGRESSION = ROOT / "examples" / "ml_problems" / "regression" / "run.py"
ML_DATA_VALIDATION = ROOT / "examples" / "ml_problems" / "data_validation" / "run.py"
SPECIALIZED_AGENTS = [
    "leakage_auditor",
    "overfitting_checker",
    "baseline_enforcer",
    "calibration_checker",
    "reproducibility_checker",
    "data_quality_auditor",
    "debugger",
    "bug_hunter",
    "dependency_mapper",
    "aggregator",
    "ui_builder",
    "a11y_auditor",
    "responsive_checker",
    "perf_budgeter",
    "markup_validator",
    "ux_critic",
    "change_verifier",
    "style_drift_auditor",
    "visual_verifier",
    "plan_reviewer",
]
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


def run_tool(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=cwd or ROOT, capture_output=True, text=True)


class MawToolTests(unittest.TestCase):
    def test_scaffold_creates_run_and_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--agents", "planner,worker", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            run_dir = Path(data["run_dir"])
            self.assertTrue((run_dir / "run.md").is_file())
            self.assertTrue((run_dir / "memory.md").is_file())
            self.assertTrue((run_dir / "agents" / "planner.md").is_file())

            proc = run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(Path(proc.stdout.strip()).is_file())

    def test_validate_handoffs_passes_sample_run(self) -> None:
        proc = run_tool(str(VALIDATE), "examples/sample_run")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

    def test_validate_handoffs_rejects_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--json")
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker")

            proc = run_tool(str(VALIDATE), str(run_dir))
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(json.loads(proc.stdout)["passed"])

    def test_validate_handoffs_rejects_skipped_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--json")
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker", "--step", "1")
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "worker", "--to", "critic", "--step", "3")

            self._fill_handoff_placeholders(run_dir)

            proc = run_tool(str(VALIDATE), str(run_dir))
            result = json.loads(proc.stdout)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(result["passed"])
            self.assertTrue(any("contiguous" in error for error in result["errors"]))

    def test_validate_handoffs_rejects_duplicate_steps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--json")
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker", "--step", "1")
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "critic", "--to", "worker", "--step", "1")

            self._fill_handoff_placeholders(run_dir)

            proc = run_tool(str(VALIDATE), str(run_dir))
            result = json.loads(proc.stdout)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(result["passed"])
            self.assertTrue(any("duplicate handoff step" in error for error in result["errors"]))

    def test_validate_handoffs_requires_run_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--agents", "planner,worker", "--json")
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker")
            self._fill_handoff_placeholders(run_dir)
            (run_dir / "memory.md").unlink()
            shutil.rmtree(run_dir / "artifacts")

            proc = run_tool(str(VALIDATE), str(run_dir))
            result = json.loads(proc.stdout)

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(result["passed"])
            self.assertTrue(any("missing required file" in error and "memory.md" in error for error in result["errors"]))
            self.assertTrue(any("missing required directory" in error and "artifacts" in error for error in result["errors"]))

    def test_validate_handoffs_requires_agent_notes_for_handoff_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(str(SCAFFOLD), "init", "demo task", "--root", str(root), "--agents", "planner,worker", "--json")
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", "planner", "--to", "worker")
            self._fill_handoff_placeholders(run_dir)
            (run_dir / "agents" / "worker.md").unlink()

            proc = run_tool(str(VALIDATE), str(run_dir))
            result = json.loads(proc.stdout)

            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(result["passed"])
            self.assertTrue(any("missing required agent notes" in error and "worker.md" in error for error in result["errors"]))

    def _fill_handoff_placeholders(self, run_dir: Path) -> None:
        for handoff in (run_dir / "handoffs").glob("*.md"):
            text = handoff.read_text(encoding="utf-8")
            text = text.replace("<What we are trying to achieve, in 1-2 lines.>", "Demo task.")
            text = text.replace("<Concrete work completed in this step.>", "Created demo handoff.")
            text = text.replace("- <artifacts/...>  (what was produced)", "- artifacts/demo.txt  (demo artifact)")
            text = text.replace("<Things the next role should watch.>", "No known risks.")
            text = text.replace("<What the next role should do next.>", "Continue the demo.")
            handoff.write_text(text, encoding="utf-8")

    def test_checks_exit_code_matches_result(self) -> None:
        proc = run_tool(str(CHECKS), "gap", "--train", "0.8", "--test", "0.79", "--tol", "0.05")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

        proc = run_tool(str(CHECKS), "gap", "--train", "0.99", "--test", "0.50", "--tol", "0.05")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)["passed"])

    def test_acceptance_check_ships_sample_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "sample_run"
            shutil.copytree(ROOT / "examples" / "sample_run", run_dir)
            proc = self._run_sample_acceptance(run_dir)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            artifact = run_dir / "artifacts" / "acceptance-result.json"
            self.assertTrue(artifact.is_file())
            self.assertEqual(result["verdict"], "SHIP")
            self.assertEqual(result["task_type"], "standard-software-task")
            self.assertTrue(result["evidence"]["passed"])
            self.assertEqual(json.loads(artifact.read_text(encoding="utf-8"))["verdict"], "SHIP")

    def _run_sample_acceptance(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        return run_tool(
            str(ACCEPTANCE),
            "--run",
            str(run_dir),
            "--test-cmd",
            "python test_textutil.py",
            "--test-cwd",
            "examples/sample_app",
        )

    def test_acceptance_check_missing_required_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "sample_run"
            shutil.copytree(ROOT / "examples" / "sample_run", run_dir)
            (run_dir / "artifacts" / "test-result.json").unlink()

            proc = self._run_sample_acceptance(run_dir)

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["verdict"], "NO-SHIP")
            self.assertTrue(result["handoffs"]["passed"])
            self.assertTrue(result["test"]["passed"])
            missing = next(item for item in result["violations"] if item["type"] == "missing_required_evidence")
            self.assertEqual(missing["artifact"], "artifacts/test-result.json")

    def test_acceptance_check_failing_required_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "sample_run"
            shutil.copytree(ROOT / "examples" / "sample_run", run_dir)
            (run_dir / "artifacts" / "test-result.json").write_text(json.dumps({"passed": False}) + "\n", encoding="utf-8")

            proc = self._run_sample_acceptance(run_dir)

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["verdict"], "NO-SHIP")
            failing = next(item for item in result["violations"] if item["type"] == "failing_required_evidence")
            self.assertEqual(failing["artifact"], "artifacts/test-result.json")
            self.assertEqual(failing["reason"], "passed is false")

    def test_acceptance_check_public_tests_only_without_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "sample_run"
            shutil.copytree(ROOT / "examples" / "sample_run", run_dir)
            for artifact in (run_dir / "artifacts").glob("*.json"):
                artifact.unlink()

            proc = self._run_sample_acceptance(run_dir)

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["verdict"], "NO-SHIP")
            self.assertTrue(result["handoffs"]["passed"])
            self.assertTrue(result["test"]["passed"])
            self.assertFalse(result["evidence"]["passed"])
            self.assertTrue(any(item["type"] == "missing_required_evidence" for item in result["violations"]))

    def test_refactor_acceptance_late_behavior_baseline_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runs"
            proc = run_tool(
                str(SCAFFOLD),
                "init",
                "refactor late baseline",
                "--root",
                str(root),
                "--agents",
                "conductor,planner,worker,critic,acceptance_gate",
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            run_dir = Path(json.loads(proc.stdout)["run_dir"])
            for frm, to in (
                ("conductor", "planner"),
                ("planner", "worker"),
                ("worker", "critic"),
                ("critic", "acceptance_gate"),
            ):
                handoff = run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", frm, "--to", to)
                self.assertEqual(handoff.returncode, 0, handoff.stdout + handoff.stderr)
            self._fill_handoff_placeholders(run_dir)
            run_md = (run_dir / "run.md").read_text(encoding="utf-8")
            run_md = run_md.replace("- Status: in-progress", "- Status: in-progress\n- Workflow template: refactor-task")
            (run_dir / "run.md").write_text(run_md, encoding="utf-8")

            source = Path(tmp_dir) / "legacy.py"
            source.write_text("def public():\n    return 'edited'\n", encoding="utf-8")
            edited_mtime = source.stat().st_mtime
            late_baseline = {
                "check": "behavior_baseline",
                "passed": True,
                "metadata": {
                    "captured_at_epoch": edited_mtime + 60.0,
                    "source_paths": [str(source)],
                },
                "items": [],
            }
            (run_dir / "artifacts" / "behavior-baseline.json").write_text(json.dumps(late_baseline) + "\n", encoding="utf-8")
            (run_dir / "artifacts" / "behavior-diff.json").write_text(json.dumps({"passed": True, "diffs": []}) + "\n", encoding="utf-8")
            (run_dir / "artifacts" / "test-result.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")

            proc = run_tool(str(ACCEPTANCE), "--run", str(run_dir))

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["verdict"], "NO-SHIP")
            self.assertTrue(any(item["type"] == "late_behavior_baseline" for item in result["violations"]))

    def _write_verdict_run(self, root: Path, artifact_verdict: str | None, run_verdict: str) -> Path:
        run_dir = root / "run"
        (run_dir / "artifacts").mkdir(parents=True)
        (run_dir / "run.md").write_text(
            f"# Run demo\n\n## Final result summary\nFinal verdict: {run_verdict}\n",
            encoding="utf-8",
        )
        if artifact_verdict is not None:
            (run_dir / "artifacts" / "acceptance-result.json").write_text(
                json.dumps({"verdict": artifact_verdict}) + "\n",
                encoding="utf-8",
            )
        return run_dir

    def test_verdict_check_matching_ship_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._write_verdict_run(Path(tmp_dir), "SHIP", "SHIP")

            proc = run_tool(str(VERDICT_CHECK), str(run_dir))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(result["artifact_verdict"], "SHIP")
            self.assertEqual(result["run_verdict"], "SHIP")

    def test_verdict_check_no_ship_artifact_ship_run_fails_with_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._write_verdict_run(Path(tmp_dir), "NO-SHIP", "SHIP")

            proc = run_tool(str(VERDICT_CHECK), str(run_dir))

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertFalse(result["passed"])
            mismatch = next(item for item in result["violations"] if item["type"] == "verdict_mismatch")
            self.assertEqual(mismatch["artifact_verdict"], "NO-SHIP")
            self.assertEqual(mismatch["run_verdict"], "SHIP")

    def test_verdict_check_missing_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._write_verdict_run(Path(tmp_dir), None, "SHIP")

            proc = run_tool(str(VERDICT_CHECK), str(run_dir))

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertFalse(result["passed"])
            self.assertTrue(any(item["type"] == "missing_acceptance_artifact" for item in result["violations"]))

    def test_task_graph_plans_parallel_workers_then_aggregate_and_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = Path(tmp_dir) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "id": "api",
                                "title": "Build API",
                                "type": "worker",
                                "depends_on": [],
                                "worker": "worker_api",
                            },
                            {
                                "id": "tests",
                                "title": "Build tests",
                                "type": "worker",
                                "depends_on": [],
                                "worker": "worker_tests",
                            },
                            {
                                "id": "aggregate",
                                "title": "Collect worker output",
                                "type": "aggregate",
                                "depends_on": ["api", "tests"],
                            },
                            {
                                "id": "merge",
                                "title": "Merge final result",
                                "type": "merge",
                                "depends_on": ["aggregate"],
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = run_tool(str(TASK_GRAPH), "plan", "--file", str(graph))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(len(result["stages"]), 3)
            self.assertTrue(result["stages"][0]["parallel"])
            self.assertEqual(
                [lane["worker"] for lane in result["stages"][0]["worker_lanes"]],
                ["worker_api", "worker_tests"],
            )
            self.assertEqual(result["stages"][1]["types"], ["aggregate"])
            self.assertEqual(result["stages"][2]["types"], ["merge"])

    def test_task_graph_rejects_unknown_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = Path(tmp_dir) / "graph.json"
            graph.write_text(
                json.dumps({"tasks": [{"id": "merge", "title": "Merge", "type": "merge", "depends_on": ["missing"]}]}),
                encoding="utf-8",
            )

            proc = run_tool(str(TASK_GRAPH), "plan", "--file", str(graph))

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("unknown dependency", json.loads(proc.stdout)["error"])

    def test_task_graph_rejects_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = Path(tmp_dir) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "title": "A", "type": "worker", "depends_on": ["b"]},
                            {"id": "b", "title": "B", "type": "worker", "depends_on": ["a"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = run_tool(str(TASK_GRAPH), "plan", "--file", str(graph))

            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("cycle", json.loads(proc.stdout)["error"])

    def test_workflow_templates_validate(self) -> None:
        proc = run_tool(str(WORKFLOW_TEMPLATE))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["templates"], 7)

    def test_core_roster_stays_unchanged(self) -> None:
        template = json.loads((ROOT / "templates" / "workflows" / "standard-software-task.json").read_text(encoding="utf-8"))

        self.assertEqual(template["agents"], ["conductor", "planner", "worker", "critic", "acceptance_gate"])

    def _write_dependency_audit_fixture(self, root: Path) -> Path:
        package = root / "fixture_pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "config.py").write_text(
            "DEFAULTS = {'tax_rate': 0.1}\n"
            "SHARED = []\n",
            encoding="utf-8",
        )
        (package / "a.py").write_text(
            "import os\n"
            "import time\n"
            "import random\n"
            "from . import b\n"
            "STATE = {'count': 0}\n"
            "\n"
            "def calculate_total(config, items):\n"
            "    STATE['count'] += 1\n"
            "    items.append('audit')\n"
            "    mode = os.environ['MODE']\n"
            "    now = time.time()\n"
            "    roll = random.random()\n"
            "    return config['tax_rate'] + len(mode) + now + roll\n"
            "\n"
            "def orchestrate(x):\n"
            "    str(x)\n"
            "    int(x)\n"
            "    float(x)\n"
            "    repr(x)\n"
            "    list([x])\n"
            "    dict(value=x)\n"
            "    tuple([x])\n"
            "    set([x])\n"
            "    return b.export_invoice(x)\n",
            encoding="utf-8",
        )
        (package / "b.py").write_text(
            "from . import a\n"
            "\n"
            "def export_invoice(config):\n"
            "    return config['tax_rate']\n",
            encoding="utf-8",
        )
        return package

    def test_dependency_risk_audit_detects_required_risks_and_generates_dossiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            package = self._write_dependency_audit_fixture(Path(tmp_dir))
            docs = Path(tmp_dir) / "docs" / "bugs"
            proc = run_tool(str(DEPENDENCY_AUDIT), str(package), "--docs-dir", str(docs))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["check"], "dependency-risk-audit")
            self.assertGreater(result["summary"]["risk_count"], 0)
            risks = result["risks"]
            risk_types = {risk["risk_type"] for risk in risks}
            self.assertIn("global_state_read", risk_types)
            self.assertIn("environment_variable_dependency", risk_types)
            self.assertIn("time_or_random_dependency", risk_types)
            self.assertIn("shared_mutable_argument", risk_types)
            self.assertIn("implicit_coupling_magic_string", risk_types)
            self.assertIn("high_fan_out", risk_types)
            self.assertIn("circular_import", risk_types)
            for risk in risks:
                for field in RISK_FIELDS:
                    self.assertIn(field, risk)
                self.assertIn(risk["severity"], {"low", "medium", "high"})
                self.assertIsInstance(risk["affected_symbols_or_files"], list)
            self.assertTrue(result["dossiers"])
            self.assertTrue(any(path.suffix == ".md" for path in docs.glob("*.md")))

    def test_dependency_risk_audit_annotate_is_idempotent_and_dry_run_preserves_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            package = self._write_dependency_audit_fixture(Path(tmp_dir))
            target = package / "a.py"
            before = target.read_text(encoding="utf-8")

            dry = run_tool(str(DEPENDENCY_AUDIT), str(package), "--annotate", "--dry-run", "--no-dossiers")
            self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), before)

            first = run_tool(str(DEPENDENCY_AUDIT), str(package), "--annotate", "--no-dossiers")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            annotated_once = target.read_text(encoding="utf-8")
            self.assertIn("# MAW-DEPENDENCY-RISK:", annotated_once)

            second = run_tool(str(DEPENDENCY_AUDIT), str(package), "--annotate", "--no-dossiers")
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), annotated_once)

    def test_dependency_risk_audit_fail_on_high_and_cli_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            package = self._write_dependency_audit_fixture(Path(tmp_dir))
            proc = run_tool(str(DEPENDENCY_AUDIT), str(package), "--fail-on", "high", "--no-dossiers")
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue(json.loads(proc.stdout)["summary"]["high"] > 0)

            cli = run_tool(str(MAW), "dependency-audit", str(package), "--no-dossiers")
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertEqual(json.loads(cli.stdout)["check"], "dependency-risk-audit")

    def _run_plan_check(self, plan: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(plan, handle)
            path = Path(handle.name)
        try:
            return run_tool(str(PLAN_CHECK), "--file", str(path))
        finally:
            path.unlink(missing_ok=True)

    def test_plan_check_default_caps_allow_generic_core_plan(self) -> None:
        proc = self._run_plan_check(
            {
                "task_type": "generic",
                "roles": ["conductor", "planner", "worker", "critic", "acceptance_gate"],
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["caps"]["max_agents"], 5)

    def test_plan_check_specialist_default_caps_fail_with_clear_headroom_error(self) -> None:
        ml_default = {
            "task_type": "ml",
            "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
        }
        proc = self._run_plan_check(ml_default)
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        cap_errors = [item for item in result["violations"] if item["type"] == "insufficient_role_cap_for_required_roles"]
        self.assertEqual(len(cap_errors), 1)
        self.assertEqual(cap_errors[0]["required_role_count"], 7)
        self.assertEqual(cap_errors[0]["max_agents"], 5)
        self.assertEqual(cap_errors[0]["missing_headroom"], 2)
        self.assertEqual(cap_errors[0]["suggested_cap"], 7)

        frontend_default = {
            "task_type": "frontend",
            "roles": ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "critic", "acceptance_gate"],
        }
        proc = self._run_plan_check(frontend_default)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any(item["type"] == "insufficient_role_cap_for_required_roles" for item in json.loads(proc.stdout)["violations"]))

    def test_plan_check_template_caps_allow_specialist_workflows(self) -> None:
        ml_template_cap = {
            "task_type": "ml-validation-task",
            "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
            "caps": {"max_agents": 10, "max_parallel": 3},
        }
        proc = self._run_plan_check(ml_template_cap)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

        frontend_template_cap = {
            "task_type": "frontend-ui-task",
            "roles": ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "critic", "acceptance_gate"],
            "caps": {"max_agents": 13, "max_parallel": 3},
        }
        proc = self._run_plan_check(frontend_template_cap)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_plan_check_rejects_plans_that_drop_core_roles_to_fit_caps(self) -> None:
        dropped_planner = {
            "task_type": "ml",
            "roles": ["conductor", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
            "caps": {"max_agents": 7, "max_parallel": 3},
        }
        proc = self._run_plan_check(dropped_planner)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any(item["type"] == "missing_core_role" and item["role"] == "planner" for item in json.loads(proc.stdout)["violations"]))

    def test_plan_check_rejects_missing_ml_validator_and_accepts_corrected_plan(self) -> None:
        missing = {
            "task_type": "ml",
            "roles": ["conductor", "planner", "worker", "baseline_enforcer", "critic", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
        }
        proc = self._run_plan_check(missing)
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["type"] == "missing_required_role" and item["role"] == "leakage_auditor" for item in result["violations"]))

        corrected = {
            "task_type": "ml",
            "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
        }
        proc = self._run_plan_check(corrected)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

    def test_plan_check_rejects_duplicates_unknown_roles_missing_gate_and_caps(self) -> None:
        cases = [
            (
                {
                    "task_type": "ml",
                    "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "critic", "acceptance_gate"],
                    "caps": {"max_agents": 8, "max_parallel": 3},
                },
                "duplicate_role",
            ),
            (
                {
                    "task_type": "ml",
                    "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "mystery_agent", "acceptance_gate"],
                    "caps": {"max_agents": 8, "max_parallel": 3},
                },
                "unknown_role",
            ),
            (
                {
                    "task_type": "ml",
                    "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic"],
                    "caps": {"max_agents": 8, "max_parallel": 3},
                },
                "missing_acceptance_gate",
            ),
            (
                {
                    "task_type": "ml",
                    "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
                    "caps": {"max_agents": 3, "max_parallel": 3},
                },
                "role_cap_exceeded",
            ),
            (
                {
                    "task_type": "ml",
                    "roles": ["conductor", "planner", "worker", "leakage_auditor", "baseline_enforcer", "critic", "acceptance_gate"],
                    "parallel_roles": ["planner", "leakage_auditor"],
                    "caps": {"max_agents": 8, "max_parallel": 1},
                },
                "parallel_cap_exceeded",
            ),
        ]
        for plan, violation_type in cases:
            proc = self._run_plan_check(plan)
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            result = json.loads(proc.stdout)
            self.assertTrue(any(item["type"] == violation_type for item in result["violations"]), result["violations"])

    def test_plan_check_enforces_frontend_and_code_required_roles(self) -> None:
        frontend_missing = {
            "task_type": "frontend",
            "roles": ["conductor", "planner", "worker", "a11y_auditor", "critic", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
        }
        proc = self._run_plan_check(frontend_missing)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any(item["type"] == "missing_required_role" and item["role"] == "change_verifier" for item in json.loads(proc.stdout)["violations"]))

        frontend_ok = {
            "task_type": "frontend",
            "roles": ["conductor", "planner", "worker", "a11y_auditor", "change_verifier", "critic", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
        }
        self.assertEqual(self._run_plan_check(frontend_ok).returncode, 0)

        code_missing = {
            "task_type": "code",
            "roles": ["conductor", "planner", "worker", "critic", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
        }
        proc = self._run_plan_check(code_missing)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(any(item["type"] == "missing_required_role" and item["role"] == "dependency_mapper" for item in json.loads(proc.stdout)["violations"]))

        code_ok = {
            "task_type": "code",
            "roles": ["conductor", "planner", "worker", "critic", "dependency_mapper", "acceptance_gate"],
            "caps": {"max_agents": 8, "max_parallel": 3},
            "role_justifications": {"dependency_mapper": "Map code dependencies before execution."},
        }
        self.assertEqual(self._run_plan_check(code_ok).returncode, 0)

    def test_specialized_agent_prompts_have_required_contract_sections(self) -> None:
        required_sections = [
            "## Mission",
            "## Inputs",
            "## Outputs",
            "## Required Artifacts",
            "## Deterministic Tools / Checks Used",
            "## Pass / Fail Criteria",
        ]

        for agent in SPECIALIZED_AGENTS:
            path = ROOT / ".codex" / "agents" / f"{agent}.md"
            self.assertTrue(path.is_file(), f"missing {path}")
            text = path.read_text(encoding="utf-8")
            for section in required_sections:
                self.assertIn(section, text, f"{agent} missing {section}")

    def test_workflow_templates_activate_optional_specialized_agents(self) -> None:
        expected = {
            "ml-validation-task": {
                "leakage_auditor",
                "data_quality_auditor",
                "baseline_enforcer",
                "overfitting_checker",
                "calibration_checker",
                "reproducibility_checker",
            },
            "ml-training-task": {
                "data_quality_auditor",
                "baseline_enforcer",
                "overfitting_checker",
                "calibration_checker",
                "reproducibility_checker",
            },
            "bug-investigation": {"debugger", "bug_hunter", "dependency_mapper"},
            "multi-agent-research-task": {"aggregator"},
            "frontend-ui-task": {
                "ui_builder",
                "a11y_auditor",
                "responsive_checker",
                "perf_budgeter",
                "markup_validator",
                "ux_critic",
                "change_verifier",
                "style_drift_auditor",
                "visual_verifier",
            },
        }

        for template_id, agents in expected.items():
            template = json.loads((ROOT / "templates" / "workflows" / f"{template_id}.json").read_text(encoding="utf-8"))
            self.assertTrue(agents.issubset(set(template["agents"])))

    def test_declared_workflow_template_conforming_run_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            (run_dir / "agents").mkdir(parents=True)
            (run_dir / "handoffs").mkdir()
            (run_dir / "artifacts").mkdir()
            (run_dir / "run.md").write_text(
                "# Run demo\n\n- Workflow template: standard-software-task\n",
                encoding="utf-8",
            )
            for agent in ("conductor", "planner", "worker", "critic", "acceptance_gate"):
                (run_dir / "agents" / f"{agent}.md").write_text("notes\n", encoding="utf-8")
            handoffs = [
                ("01_conductor__to__planner.md", "conductor", "planner"),
                ("02_planner__to__worker.md", "planner", "worker"),
                ("03_worker__to__critic.md", "worker", "critic"),
                ("04_critic__to__acceptance_gate.md", "critic", "acceptance_gate"),
            ]
            for filename, _frm, _to in handoffs:
                (run_dir / "handoffs" / filename).write_text("handoff\n", encoding="utf-8")
            for artifact in ("plan.md", "test-result.json", "critic-review.md", "acceptance-result.json"):
                (run_dir / "artifacts" / artifact).write_text("{}\n", encoding="utf-8")

            proc = run_tool(str(WORKFLOW_TEMPLATE), "--run", str(run_dir))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(result["template"], "standard-software-task")

    def test_declared_workflow_template_missing_artifact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            (run_dir / "agents").mkdir(parents=True)
            (run_dir / "handoffs").mkdir()
            (run_dir / "artifacts").mkdir()
            (run_dir / "run.md").write_text(
                "# Run demo\n\n- Workflow template: standard-software-task\n",
                encoding="utf-8",
            )
            for agent in ("conductor", "planner", "worker", "critic", "acceptance_gate"):
                (run_dir / "agents" / f"{agent}.md").write_text("notes\n", encoding="utf-8")
            for filename in (
                "01_conductor__to__planner.md",
                "02_planner__to__worker.md",
                "03_worker__to__critic.md",
                "04_critic__to__acceptance_gate.md",
            ):
                (run_dir / "handoffs" / filename).write_text("handoff\n", encoding="utf-8")

            proc = run_tool(str(WORKFLOW_TEMPLATE), "--run", str(run_dir))

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertFalse(result["passed"])
            self.assertTrue(any("missing required artifact" in error for error in result["errors"]))

    def test_start_workflow_creates_run_for_each_template(self) -> None:
        templates = [
            "standard-software-task",
            "bug-investigation",
            "refactor-task",
            "ml-validation-task",
            "ml-training-task",
            "multi-agent-research-task",
            "frontend-ui-task",
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "runs"
            for template in templates:
                proc = run_tool(
                    str(START_WORKFLOW),
                    template,
                    f"demo task for {template}",
                    "--root",
                    str(run_root),
                    "--json",
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                result = json.loads(proc.stdout)
                self.assertTrue(result["passed"])
                self.assertEqual(result["template"], template)

                run_dir = Path(result["run_dir"])
                self.assertTrue((run_dir / "run.md").is_file())
                self.assertTrue((run_dir / "memory.md").is_file())
                self.assertTrue((run_dir / "artifacts" / "workflow-template.json").is_file())
                self.assertTrue((run_dir / "artifacts" / "artifact-checklist.md").is_file())
                run_md = (run_dir / "run.md").read_text(encoding="utf-8")
                self.assertIn(f"- Workflow template: {template}", run_md)

                template_data = json.loads((ROOT / "templates" / "workflows" / f"{template}.json").read_text(encoding="utf-8"))
                for agent in template_data["agents"]:
                    self.assertTrue((run_dir / "agents" / f"{agent}.md").is_file())
                self.assertEqual(len(list((run_dir / "handoffs").glob("*.md"))), len(template_data["handoffs"]))

                handoff_proc = run_tool(str(VALIDATE), str(run_dir))
                self.assertEqual(handoff_proc.returncode, 0, handoff_proc.stdout + handoff_proc.stderr)

    def test_start_workflow_unknown_template_fails_without_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "runs"
            proc = run_tool(
                str(START_WORKFLOW),
                "does-not-exist",
                "demo task",
                "--root",
                str(run_root),
                "--json",
            )

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertFalse(result["passed"])
            self.assertTrue(any("unknown workflow template" in error for error in result["errors"]))
            self.assertFalse(run_root.exists())

    def test_maw_list_templates(self) -> None:
        proc = run_tool(str(MAW), "list-templates")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["templates"]), 7)
        self.assertIn("standard-software-task", {template["id"] for template in result["templates"]})

    def test_installed_style_module_entrypoint_lists_templates(self) -> None:
        proc = run_tool("-m", "maw_cli", "list-templates")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["templates"]), 7)

    def test_installed_console_script_lists_templates_with_uv(self) -> None:
        if shutil.which("uv") is None:
            self.skipTest("uv is not available")
        with tempfile.TemporaryDirectory() as tmp_dir:
            proc = subprocess.run(
                ["uv", "run", "--with", str(ROOT), "maw", "list-templates"],
                cwd=tmp_dir,
                capture_output=True,
                text=True,
                timeout=120,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["templates"]), 6)

    def test_pyproject_declares_maw_console_script(self) -> None:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

        self.assertEqual(data["project"]["scripts"]["maw"], "maw_cli:main")
        self.assertEqual(data["project"]["name"], "codex-multi-agent-workflow")

    def test_maw_start_creates_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "runs"
            proc = run_tool(
                str(MAW),
                "start",
                "standard-software-task",
                "demo task",
                "--run-root",
                str(run_root),
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(result["template"], "standard-software-task")
            self.assertTrue((Path(result["run_dir"]) / "run.md").is_file())

    def test_maw_validate_template_one_and_all(self) -> None:
        proc = run_tool(str(MAW), "validate-template")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

        proc = run_tool(str(MAW), "validate-template", "standard-software-task")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["template"], "standard-software-task")

    def test_maw_validate_handoffs(self) -> None:
        proc = run_tool(str(MAW), "validate-handoffs", "examples/sample_run")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["passed"])

    def test_maw_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "sample_run"
            shutil.copytree(ROOT / "examples" / "sample_run", run_dir)
            proc = run_tool(
                str(MAW),
                "acceptance",
                str(run_dir),
                "--test-cmd",
                "python test_textutil.py",
                "--test-cwd",
                "examples/sample_app",
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["verdict"], "SHIP")
            self.assertTrue((run_dir / "artifacts" / "acceptance-result.json").is_file())

    def test_maw_verdict_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._write_verdict_run(Path(tmp_dir), "SHIP", "SHIP")

            proc = run_tool(str(MAW), "verdict-check", str(run_dir))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(json.loads(proc.stdout)["passed"])

    def test_maw_plan_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = Path(tmp_dir) / "graph.json"
            graph.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {"id": "a", "title": "A", "type": "worker", "depends_on": []},
                            {"id": "b", "title": "B", "type": "worker", "depends_on": []},
                            {"id": "aggregate", "title": "Aggregate", "type": "aggregate", "depends_on": ["a", "b"]},
                            {"id": "merge", "title": "Merge", "type": "merge", "depends_on": ["aggregate"]},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = run_tool(str(MAW), "plan-graph", str(graph))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertTrue(result["stages"][0]["parallel"])

    def test_ml_problem_runners_pass_shared_checks(self) -> None:
        runners = [ML_CLASSIFICATION, ML_REGRESSION, ML_DATA_VALIDATION]
        with tempfile.TemporaryDirectory() as tmp_dir:
            for runner in runners:
                output = Path(tmp_dir) / f"{runner.parent.name}.json"
                proc = run_tool(str(runner), "--output", str(output))
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                result = json.loads(output.read_text(encoding="utf-8"))
                self.assertTrue(result["acceptance"]["passed"])
                self.assertIn("metrics", result)
                self.assertIn("acceptance_criteria", result)

                check_proc = run_tool(str(ML_CHECKS), str(output))
                self.assertEqual(check_proc.returncode, 0, check_proc.stdout + check_proc.stderr)
                validation = json.loads(check_proc.stdout)
                self.assertTrue(validation["passed"])

    def test_ml_checks_detect_leakage_split_and_seed_failures(self) -> None:
        bad_result = {
            "problem": "bad",
            "seed": 1,
            "expected_seed": 2,
            "features": ["feature", "target"],
            "target": "target",
            "split": {
                "train_ids": [1, 2, 3],
                "test_ids": [3, 4],
                "expected_train_ratio": 0.8,
            },
            "metrics": {"accuracy": 0.5},
            "metric_checks": [
                {"name": "accuracy", "direction": "at_least", "threshold": 0.9}
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "bad.json"
            output.write_text(json.dumps(bad_result), encoding="utf-8")

            proc = run_tool(str(ML_CHECKS), str(output))

        self.assertNotEqual(proc.returncode, 0)
        validation = json.loads(proc.stdout)
        self.assertFalse(validation["passed"])
        failed_checks = {check["check"] for check in validation["checks"] if not check["passed"]}
        self.assertIn("seed_matches", failed_checks)
        self.assertIn("no_split_overlap", failed_checks)
        self.assertIn("no_feature_target_leakage", failed_checks)
        self.assertIn("accuracy_at_least", failed_checks)

    def _write_behavior_module(self, root: Path, changed: bool = False) -> tuple[Path, Path]:
        module = root / "legacy_surface.py"
        if changed:
            module.write_text(
                "\n".join(
                    [
                        "REGISTRY = {'mode': 'legacy'}",
                        "",
                        "def rounded(value):",
                        "    return round(value, 1)",
                        "",
                        "old_round = rounded",
                        "",
                        "class Amount:",
                        "    def __init__(self, value):",
                        "        self.value = value",
                        "    def __repr__(self):",
                        "        return f'Amount({self.value:.1f})'",
                        "    def __str__(self):",
                        "        return f'{self.value:.1f}'",
                        "",
                        "def json_report():",
                        "    return {'value': rounded(1.234), 'label': 'legacy'}",
                        "",
                        "def csv_rows():",
                        "    return [['name', 'value'], ['x', f'{rounded(1.234):.1f}']]",
                        "",
                        "def text_report():",
                        "    return f'value={rounded(1.234):.1f}\\n'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            module.write_text(
                "\n".join(
                    [
                        "REGISTRY = {'mode': 'legacy'}",
                        "",
                        "def rounded(value):",
                        "    scaled = int(value * 100 + 0.5)",
                        "    return scaled / 100",
                        "",
                        "old_round = rounded",
                        "",
                        "class Amount:",
                        "    def __init__(self, value):",
                        "        self.value = value",
                        "    def __repr__(self):",
                        "        return f'Amount(value={self.value:.2f})'",
                        "    def __str__(self):",
                        "        return f'{self.value:.2f}'",
                        "",
                        "def json_report():",
                        "    return {'value': rounded(1.234), 'label': 'legacy'}",
                        "",
                        "def csv_rows():",
                        "    return [['name', 'value'], ['x', f'{rounded(1.234):.2f}']]",
                        "",
                        "def text_report():",
                        "    return f'value={rounded(1.234):.2f}\\n'",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        manifest = root / "behavior-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "source_paths": [str(module)],
                    "modules": [{"name": "legacy_surface", "attrs": ["REGISTRY"]}],
                    "signatures": [{"module": "legacy_surface", "members": "public"}],
                    "reprs": [{"name": "amount", "expr": "legacy_surface.Amount(1.234)"}],
                    "json": [{"name": "report-json", "expr": "legacy_surface.json_report()"}],
                    "csv": [{"name": "report-csv", "expr": "legacy_surface.csv_rows()"}],
                    "text": [{"name": "report-text", "expr": "legacy_surface.text_report()"}],
                    "aliases": [{"name": "old_round_alias", "alias": "legacy_surface.old_round", "target": "legacy_surface.rounded"}],
                }
            ),
            encoding="utf-8",
        )
        return module, manifest

    def test_behavior_baseline_identical_behavior_refactor_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            module, manifest = self._write_behavior_module(root)
            baseline = root / "behavior-baseline.json"
            diff = root / "behavior-diff.json"

            capture = run_tool(str(BEHAVIOR_BASELINE), "capture", "--manifest", str(manifest), "--root", str(root), "--output", str(baseline), cwd=root)
            self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
            original_mtime = module.stat().st_mtime
            self._write_behavior_module(root, changed=False)
            os.utime(module, (original_mtime + 2.0, original_mtime + 2.0))

            verify = run_tool(str(BEHAVIOR_BASELINE), "verify", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(diff), cwd=root)

            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
            result = json.loads(verify.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(result["diffs"], [])

    def test_behavior_baseline_rounding_csv_and_repr_changes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            module, manifest = self._write_behavior_module(root)
            baseline = root / "behavior-baseline.json"
            diff = root / "behavior-diff.json"

            capture = run_tool(str(BEHAVIOR_BASELINE), "capture", "--manifest", str(manifest), "--root", str(root), "--output", str(baseline), cwd=root)
            self.assertEqual(capture.returncode, 0, capture.stdout + capture.stderr)
            original_mtime = module.stat().st_mtime
            self._write_behavior_module(root, changed=True)
            os.utime(module, (original_mtime + 2.0, original_mtime + 2.0))

            verify = run_tool(str(BEHAVIOR_BASELINE), "verify", "--manifest", str(manifest), "--baseline", str(baseline), "--root", str(root), "--output", str(diff), cwd=root)

            self.assertNotEqual(verify.returncode, 0)
            result = json.loads(verify.stdout)
            self.assertFalse(result["passed"])
            diff_types = {item["type"] for item in result["diffs"]}
            self.assertIn("repr_changed", diff_types)
            self.assertIn("csv_bytes_changed", diff_types)
            self.assertIn("json_bytes_changed", diff_types)

    def test_ml_template_start_commands_create_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "runs"
            for template in ("ml-validation-task", "ml-training-task"):
                proc = run_tool(
                    str(MAW),
                    "start",
                    template,
                    f"run toy {template}",
                    "--run-root",
                    str(run_root),
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                result = json.loads(proc.stdout)
                self.assertTrue(result["passed"])
                self.assertEqual(result["template"], template)
                self.assertTrue((Path(result["run_dir"]) / "artifacts" / "artifact-checklist.md").is_file())

    def test_ml_fit_diagnosis_healthy_classification_passes(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "classification",
            "--metrics-json",
            json.dumps({"train_score": 0.88, "validation_score": 0.84, "test_score": 0.83}),
            "--high-train-score",
            "0.9",
            "--max-generalization-gap",
            "0.12",
            "--target-score",
            "0.7",
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "healthy")

    def test_ml_fit_diagnosis_classification_overfit_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "classification",
            "--metrics-json",
            json.dumps({"train_score": 0.98, "validation_score": 0.72, "test_score": 0.69}),
            "--high-train-score",
            "0.9",
            "--max-generalization-gap",
            "0.12",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "overfit")

    def test_ml_fit_diagnosis_classification_underfit_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "classification",
            "--metrics-json",
            json.dumps({"train_score": 0.55, "validation_score": 0.54, "test_score": 0.53}),
            "--target-score",
            "0.7",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "underfit")

    def test_ml_fit_diagnosis_regression_overfit_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "regression",
            "--metrics-json",
            json.dumps({"train_error": 0.2, "validation_error": 0.8, "test_error": 0.75}),
            "--max-error-ratio",
            "2.0",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "overfit")

    def test_ml_fit_diagnosis_regression_underfit_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "regression",
            "--metrics-json",
            json.dumps({"train_error": 1.4, "validation_error": 1.5, "test_error": 1.6}),
            "--poor-error",
            "1.0",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "underfit")

    def test_ml_fit_diagnosis_missing_metrics_fail_clearly(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "fit-diagnosis",
            "--problem-type",
            "classification",
            "--metrics-json",
            json.dumps({"train_score": 0.9}),
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "invalid")
        self.assertIn("validation_score", result["missing_metrics"])
        self.assertIn("test_score", result["missing_metrics"])

    def test_ml_baseline_comparison_passes_and_fails(self) -> None:
        passing = run_tool(
            str(ML_CHECKS),
            "baseline",
            "--metrics-json",
            json.dumps({"model_score": 0.84, "baseline_score": 0.78}),
            "--min-improvement",
            "0.03",
        )
        self.assertEqual(passing.returncode, 0, passing.stdout + passing.stderr)
        self.assertTrue(json.loads(passing.stdout)["passed"])

        failing = run_tool(
            str(ML_CHECKS),
            "baseline",
            "--metrics-json",
            json.dumps({"model_score": 0.80, "baseline_score": 0.78}),
            "--min-improvement",
            "0.03",
        )
        self.assertNotEqual(failing.returncode, 0)
        self.assertFalse(json.loads(failing.stdout)["passed"])

    def test_ml_shuffled_label_clean_classification_passes(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "shuffled-label",
            "--problem-type",
            "classification",
            "--real-score",
            "0.86",
            "--shuffled-scores-json",
            json.dumps([0.49, 0.51, 0.52]),
            "--class-count",
            "2",
            "--tolerance",
            "0.05",
            "--min-real-margin",
            "0.20",
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["thresholds"]["chance_score"], 0.5)

    def test_ml_shuffled_label_leakage_case_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "shuffled-label",
            "--problem-type",
            "classification",
            "--real-score",
            "0.91",
            "--shuffled-scores-json",
            json.dumps([0.82, 0.86, 0.84]),
            "--class-count",
            "2",
            "--tolerance",
            "0.05",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("shuffled score max" in reason for reason in result["reasons"]))

    def test_ml_multi_seed_clean_case_passes(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "multi-seed",
            "--scores-json",
            json.dumps([0.82, 0.83, 0.81, 0.82]),
            "--min-score",
            "0.80",
            "--max-variance",
            "0.0002",
            "--min-seeds",
            "3",
            "--metric-name",
            "accuracy",
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["metrics"]["seed_count"], 4)

    def test_ml_multi_seed_unstable_case_fails(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "multi-seed",
            "--scores-json",
            json.dumps([0.90, 0.70, 0.88]),
            "--min-score",
            "0.70",
            "--max-variance",
            "0.0004",
            "--min-seeds",
            "3",
        )

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "fail")
        self.assertTrue(any("variance" in reason for reason in result["reasons"]))

    def test_ml_calibration_reproducibility_and_data_quality_checks(self) -> None:
        calibration = run_tool(
            str(ML_CHECKS),
            "calibration",
            "--data-json",
            json.dumps({"confidences": [0.8, 0.7, 0.2], "correct": [True, True, False]}),
            "--max-ece",
            "0.25",
        )
        self.assertEqual(calibration.returncode, 0, calibration.stdout + calibration.stderr)
        self.assertTrue(json.loads(calibration.stdout)["passed"])

        reproducibility = run_tool(
            str(ML_CHECKS),
            "reproducibility",
            "--data-json",
            json.dumps({"seed": 42, "expected_seed": 42, "deterministic": True}),
        )
        self.assertEqual(reproducibility.returncode, 0, reproducibility.stdout + reproducibility.stderr)
        self.assertTrue(json.loads(reproducibility.stdout)["passed"])

        quality = run_tool(
            str(ML_CHECKS),
            "data-quality",
            "--data-json",
            json.dumps({"row_count": 100, "missing_values": {"x": 0}, "duplicate_rows": 0}),
        )
        self.assertEqual(quality.returncode, 0, quality.stdout + quality.stderr)
        self.assertTrue(json.loads(quality.stdout)["passed"])

    def test_dependency_map_check_detects_unknown_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            graph = Path(tmp_dir) / "deps.json"
            graph.write_text(
                json.dumps({"nodes": [{"id": "api", "depends_on": ["missing"]}]}),
                encoding="utf-8",
            )

            proc = run_tool(str(CHECKS), "dependency-map", "--file", str(graph))

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertTrue(any("unknown dependency" in error for error in result["errors"]))

    def test_aggregation_check_requires_each_lane(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            aggregation = Path(tmp_dir) / "aggregation.json"
            aggregation.write_text(
                json.dumps(
                    {
                        "required_lanes": ["api", "tests"],
                        "findings": [{"lane": "api", "summary": "API implementation is complete."}],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_tool(str(CHECKS), "aggregation", "--file", str(aggregation))

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertIn("missing finding for lane: tests", result["errors"])


if __name__ == "__main__":
    unittest.main()
