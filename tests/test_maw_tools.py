from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
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
RUN_REPORT = ROOT / "maw-tools" / "run_report.py"
TASK_GRAPH = ROOT / "maw-tools" / "task_graph.py"
WORKFLOW_TEMPLATE = ROOT / "maw-tools" / "validate_workflow_template.py"
START_WORKFLOW = ROOT / "maw-tools" / "start_workflow.py"
DEPENDENCY_AUDIT = ROOT / "maw-tools" / "dependency_risk_audit.py"
PLAN_CHECK = ROOT / "maw-tools" / "plan_check.py"
REGISTRY = ROOT / "maw-tools" / "registry.py"
BEHAVIOR_BASELINE = ROOT / "maw-tools" / "behavior_baseline.py"
CHECKLIST_CHECK = ROOT / "maw-tools" / "checklist_check.py"
MAW = ROOT / "maw.py"
PYPROJECT = ROOT / "pyproject.toml"
ML_CHECKS = ROOT / "examples" / "ml_problems" / "ml_checks.py"
WILDS_BENCHMARK = ROOT / "maw_cli" / "wilds_benchmark.py"
BASELINE_MODEL = ROOT / "model.py"
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
    def _load_tool_module(self, name: str, path: Path):
        tools_dir = str(path.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        spec = importlib.util.spec_from_file_location(name, path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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

    def _create_ml_acceptance_run(self, root: Path) -> Path:
        proc = run_tool(
            str(SCAFFOLD),
            "init",
            "ml acceptance fixture",
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
        run_md = run_md.replace("- Status: in-progress", "- Status: in-progress\n- Task type: ml")
        (run_dir / "run.md").write_text(run_md, encoding="utf-8")

        artifacts = run_dir / "artifacts"
        for name in (
            "leakage-audit.json",
            "data-quality-report.json",
            "reproducibility-check.json",
            "baseline-comparison.json",
            "fit-diagnosis.json",
            "calibration-report.json",
            "shuffled-label-check.json",
            "multi-seed-stability.json",
            "drift-report.json",
            "classification-metrics.json",
        ):
            (artifacts / name).write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
        (artifacts / "ml-validator.json").write_text(
            json.dumps(
                {
                    "check": "ml_validator",
                    "schema_version": 1,
                    "passed": True,
                    "required_evidence": ["leakage", "drift", "baseline", "multi_seed", "shuffled_label"],
                    "evidence": {
                        "leakage": {"artifact": "artifacts/leakage-audit.json", "passed": True},
                        "drift": {"artifact": "artifacts/drift-report.json", "passed": True},
                        "baseline": {"artifact": "artifacts/baseline-comparison.json", "passed": True},
                        "multi_seed": {"artifact": "artifacts/multi-seed-stability.json", "passed": True},
                        "shuffled_label": {"artifact": "artifacts/shuffled-label-check.json", "passed": True},
                    },
                    "checks": [
                        {"check": "leakage", "passed": True},
                        {"check": "drift", "passed": True},
                        {"check": "baseline", "passed": True},
                        {"check": "multi_seed", "passed": True},
                        {"check": "shuffled_label", "passed": True},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (artifacts / "regression-resistance.json").write_text(
            json.dumps(
                {
                    "check": "regression_resistance",
                    "schema_version": 1,
                    "passed": True,
                    "clean": {"passed": True, "checks": [{"check": "clean", "passed": True}]},
                    "mutations": [
                        {"name": "leaky_feature", "caught": True, "mutant_passed": False, "failed_checks": ["no_feature_target_leakage"]},
                        {"name": "shuffled_labels", "caught": True, "mutant_passed": False, "failed_checks": ["labels_not_shuffled"]},
                        {"name": "train_test_overlap", "caught": True, "mutant_passed": False, "failed_checks": ["no_split_overlap"]},
                        {"name": "preprocessing_fit_full_data", "caught": True, "mutant_passed": False, "failed_checks": ["preprocessing_fit_on_train_only"]},
                        {"name": "missing_metric", "caught": True, "mutant_passed": False, "failed_checks": ["accuracy_at_least"]},
                        {"name": "weak_baseline_ci", "caught": True, "mutant_passed": False, "failed_checks": ["baseline_comparison"]},
                        {"name": "unstable_multi_seed", "caught": True, "mutant_passed": False, "failed_checks": ["multi_seed"]},
                        {"name": "bad_calibration_stats", "caught": True, "mutant_passed": False, "failed_checks": ["calibration"]},
                        {"name": "insignificant_shuffled_label", "caught": True, "mutant_passed": False, "failed_checks": ["shuffled_label"]},
                        {"name": "content_duplicate_leakage", "caught": True, "mutant_passed": False, "failed_checks": ["content_duplicate_leakage"]},
                        {"name": "group_entity_leakage", "caught": True, "mutant_passed": False, "failed_checks": ["group_entity_leakage"]},
                        {"name": "temporal_leakage", "caught": True, "mutant_passed": False, "failed_checks": ["temporal_leakage"]},
                        {"name": "high_feature_target_correlation", "caught": True, "mutant_passed": False, "failed_checks": ["high_feature_target_correlation"]},
                        {"name": "distribution_drift", "caught": True, "mutant_passed": False, "failed_checks": ["distribution_drift"]},
                        {"name": "hard_imbalanced_majority", "caught": True, "mutant_passed": False, "failed_checks": ["classification_metrics"]},
                        {"name": "hard_content_duplicate", "caught": True, "mutant_passed": False, "failed_checks": ["content_duplicate_leakage"]},
                        {"name": "hard_temporal_leak", "caught": True, "mutant_passed": False, "failed_checks": ["temporal_leakage"]},
                    ],
                    "summary": {"total": 17, "caught": 17},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return run_dir

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

    def _create_code_acceptance_run(self, root: Path) -> Path:
        proc = run_tool(
            str(SCAFFOLD),
            "init",
            "code acceptance fixture",
            "--root",
            str(root),
            "--agents",
            "conductor,planner,worker,dependency_mapper,critic,acceptance_gate",
            "--json",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        run_dir = Path(json.loads(proc.stdout)["run_dir"])
        for frm, to in (
            ("conductor", "planner"),
            ("planner", "dependency_mapper"),
            ("dependency_mapper", "worker"),
            ("worker", "critic"),
            ("critic", "acceptance_gate"),
        ):
            handoff = run_tool(str(SCAFFOLD), "handoff", "--run", str(run_dir), "--from", frm, "--to", to)
            self.assertEqual(handoff.returncode, 0, handoff.stdout + handoff.stderr)
        self._fill_handoff_placeholders(run_dir)
        run_md = (run_dir / "run.md").read_text(encoding="utf-8")
        run_md = run_md.replace("- Status: in-progress", "- Status: in-progress\n- Task type: code")
        (run_dir / "run.md").write_text(run_md, encoding="utf-8")

        artifacts = run_dir / "artifacts"
        (artifacts / "test-result.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
        (artifacts / "artifact-parse-report.json").write_text(json.dumps({"passed": True, "items": [{"artifact": "artifacts/test-result.json", "passed": True}]}) + "\n", encoding="utf-8")
        (artifacts / "checklist-validation.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
        (artifacts / "dependency-map.json").write_text(json.dumps({"passed": True, "nodes": [{"id": "harness", "depends_on": []}]}) + "\n", encoding="utf-8")
        (artifacts / "dependency-risk-report.json").write_text(json.dumps({"passed": True, "summary": {"parse_errors": 0}}) + "\n", encoding="utf-8")
        return run_dir

    def test_code_acceptance_requires_parseable_artifact_parse_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._create_code_acceptance_run(Path(tmp_dir) / "runs")
            proc = run_tool(str(ACCEPTANCE), "--run", str(run_dir))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["verdict"], "SHIP")

            (run_dir / "artifacts" / "artifact-parse-report.json").write_text("{not json", encoding="utf-8")
            proc = run_tool(str(ACCEPTANCE), "--run", str(run_dir))
            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertEqual(result["verdict"], "NO-SHIP")
            failing = next(item for item in result["violations"] if item["type"] == "failing_required_evidence")
            self.assertEqual(failing["artifact"], "artifacts/artifact-parse-report.json")

    def test_run_report_summarizes_fixture_run_and_acceptance_writes_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = self._create_code_acceptance_run(Path(tmp_dir) / "runs")
            artifacts = run_dir / "artifacts"
            (artifacts / "conductor-plan.json").write_text(
                json.dumps(
                    {
                        "task_type": "code",
                        "roles": ["conductor", "planner", "worker", "dependency_mapper", "critic", "acceptance_gate"],
                        "caps": {"max_agents": 6, "max_parallel": 3, "max_iters": 3},
                        "deterministic_checks": [
                            {"name": "plan-check", "command": "python maw-tools/plan_check.py --file artifacts/conductor-plan.json"},
                            {"name": "unit-tests", "command": "python -m unittest discover -s tests"},
                            {"name": "readme-check", "command": "python maw-tools/readme_check.py"},
                            {"name": "dependency-boundary", "command": "python -m unittest tests.test_maw_tools.MawToolTests.test_maw_tools_never_import_wilds_or_torch"},
                            {"name": "offline-fake-wilds-e2e", "command": "python -m unittest tests.test_maw_tools.MawToolTests.test_wilds_export_runs_model_and_scores_with_fake_wilds"},
                            {"name": "dependency-map", "command": "python maw-tools/checks.py dependency-map --file artifacts/dependency-map.json"},
                            {"name": "artifact-parse", "command": "python maw-tools/checks.py artifacts-parse --run <run> --artifacts artifacts/test-result.json"},
                            {"name": "acceptance", "command": "python maw-tools/acceptance_check.py --run <run>"},
                            {"name": "verdict-check", "command": "python maw-tools/verdict_check.py <run>"},
                            {"name": "custom-manual-review", "command": "manual review"},
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (artifacts / "plan-check-result.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
            (artifacts / "readme-check-result.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
            (artifacts / "wilds-export-result.json").write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")

            proc = run_tool(str(ACCEPTANCE), "--run", str(run_dir))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            summary = artifacts / "run-summary.md"
            self.assertTrue(summary.is_file())
            text = summary.read_text(encoding="utf-8")
            self.assertIn("Task type: `code`", text)
            self.assertIn("max_agents=6", text)
            self.assertIn("planner -> dependency_mapper", text)
            self.assertIn("| plan-check | PASS |", text)
            self.assertIn("| readme-check | PASS | artifacts/readme-check-result.json |", text)
            self.assertIn("| dependency-boundary | PASS | artifacts/dependency-risk-report.json |", text)
            self.assertIn("| offline-fake-wilds-e2e | PASS | artifacts/wilds-export-result.json |", text)
            self.assertIn("| acceptance | PASS | artifacts/acceptance-result.json |", text)
            self.assertIn("| verdict-check | PASS | artifacts/verdict-check-result.json |", text)
            self.assertIn("| custom-manual-review | not recorded | planned check produced no artifact |", text)
            self.assertNotIn("UNKNOWN", text)
            self.assertIn("| required-evidence | PASS |", text)
            self.assertIn("artifacts/dependency-map.json", text)
            self.assertIn("Final verdict: `SHIP`", text)
            self.assertEqual(json.loads((artifacts / "acceptance-result.json").read_text(encoding="utf-8"))["run_summary"], str(summary))
            self.assertTrue((artifacts / "handoff-validation.json").is_file())
            self.assertTrue((artifacts / "verdict-check-result.json").is_file())
            self.assertTrue((artifacts / "run-report-result.json").is_file())

            summary.unlink()
            cli = run_tool(str(MAW), "run-report", str(run_dir))
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertTrue(summary.is_file())
            self.assertEqual(json.loads(cli.stdout)["summary"], str(summary))

    def test_ml_acceptance_missing_validator_or_regression_resistance_fails(self) -> None:
        for artifact in ("ml-validator.json", "regression-resistance.json"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as tmp_dir:
                run_dir = self._create_ml_acceptance_run(Path(tmp_dir) / "runs")
                (run_dir / "artifacts" / artifact).unlink()

                proc = run_tool(str(ACCEPTANCE), "--run", str(run_dir))

                self.assertNotEqual(proc.returncode, 0)
                result = json.loads(proc.stdout)
                self.assertEqual(result["verdict"], "NO-SHIP")
                self.assertTrue(result["handoffs"]["passed"])
                missing = next(item for item in result["violations"] if item["type"] == "missing_required_evidence")
                self.assertEqual(missing["artifact"], f"artifacts/{artifact}")

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
        self.assertEqual(result["templates"], 8)

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

    def test_registry_loads_pack_fixture(self) -> None:
        registry_module = self._load_tool_module("registry_fixture_test", REGISTRY)
        with tempfile.TemporaryDirectory() as tmp_dir:
            packs = Path(tmp_dir) / "packs"
            alpha = packs / "alpha"
            beta = packs / "beta"
            alpha.mkdir(parents=True)
            beta.mkdir(parents=True)
            (alpha / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "alpha",
                        "task_types": ["generic"],
                        "core_roles": ["conductor"],
                        "roles": ["worker"],
                        "role_aliases": {"builder": "worker"},
                        "caps": {"max_agents": 2, "max_parallel": 1},
                        "required_roles": {"generic": ["worker"]},
                        "required_evidence": [
                            {"artifact": "artifacts/alpha.json", "check": "alpha", "schema": "schemas/check-result.json"}
                        ],
                        "depends_on": [],
                    }
                ),
                encoding="utf-8",
            )
            (beta / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "beta",
                        "task_types": ["code"],
                        "task_type_aliases": {"standard": "generic"},
                        "roles": ["critic"],
                        "role_aliases": {"reviewer": "critic"},
                        "caps": {"max_agents": 3, "max_parallel": 2},
                        "required_roles": ["critic"],
                        "required_evidence": [
                            {"artifact": "artifacts/beta.json", "check": "beta", "schema": "schemas/check-result.json"}
                        ],
                        "depends_on": ["alpha"],
                    }
                ),
                encoding="utf-8",
            )

            data = registry_module.load_registry(packs)

        self.assertEqual(data["core_roles"], {"conductor"})
        self.assertEqual(data["known_roles"], {"conductor", "worker", "critic"})
        self.assertEqual(data["role_aliases"], {"builder": "worker", "reviewer": "critic"})
        self.assertEqual(data["task_type_aliases"], {"standard": "generic"})
        self.assertEqual(data["required_role_rules"], {"generic": ["worker"], "code": ["critic"]})
        self.assertEqual(data["default_caps"], {"max_agents": 2, "max_parallel": 1})
        self.assertEqual(data["task_type_caps"]["generic"], {"max_agents": 2, "max_parallel": 1})
        self.assertEqual(data["task_type_caps"]["code"], {"max_agents": 3, "max_parallel": 2})
        self.assertEqual(data["required_evidence"]["generic"][0]["artifact"], "artifacts/alpha.json")
        self.assertEqual(data["required_evidence"]["code"][0]["schema"], "schemas/check-result.json")

    def test_plan_check_registry_tables_match_previous_literals(self) -> None:
        plan_check = self._load_tool_module("plan_check_registry_parity_test", PLAN_CHECK)

        self.assertEqual(plan_check.CORE_ROLES, {"conductor", "planner", "worker", "critic", "acceptance_gate"})
        self.assertEqual(
            plan_check.KNOWN_ROLES,
            {
                "a11y_auditor",
                "acceptance_gate",
                "aggregator",
                "baseline_enforcer",
                "bug_hunter",
                "calibration_checker",
                "change_verifier",
                "conductor",
                "critic",
                "data_quality_auditor",
                "debugger",
                "dependency_mapper",
                "leakage_auditor",
                "markup_validator",
                "overfitting_checker",
                "perf_budgeter",
                "plan_reviewer",
                "planner",
                "reproducibility_checker",
                "responsive_checker",
                "style_drift_auditor",
                "ui_builder",
                "ux_critic",
                "visual_verifier",
                "worker",
            },
        )
        self.assertEqual(plan_check.ROLE_ALIASES, {"code_reviewer": "critic", "dep_mapper": "dependency_mapper"})
        self.assertEqual(
            plan_check.TASK_TYPE_ALIASES,
            {
                "bug-investigation": "debugging",
                "frontend-ui-task": "frontend",
                "ml-training-task": "ml",
                "ml-validation-task": "ml",
                "refactor-task": "refactor",
                "standard-software-task": "generic",
            },
        )
        self.assertEqual(
            plan_check.REQUIRED_ROLE_RULES,
            {
                "debugging": ["debugger", "bug_hunter", "dependency_mapper"],
                "generic": [],
                "ml": ["leakage_auditor", "baseline_enforcer"],
                "frontend": ["a11y_auditor", "change_verifier"],
                "code": ["critic", "dependency_mapper"],
                "refactor": [],
            },
        )
        self.assertEqual(plan_check.DEFAULT_CAPS, {"max_agents": 5, "max_parallel": 3})

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

    def test_task_type_checklists_validate(self) -> None:
        proc = run_tool(str(CHECKLIST_CHECK), "--root", str(ROOT))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(set(result["checklists"]), {"refactor", "ml", "frontend", "debugging", "code", "generic"})

    def test_task_type_checklists_reject_unknown_deterministic_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            checklist_dir = root / ".codex" / "checklists"
            checklist_dir.mkdir(parents=True)
            for name in ("refactor", "ml", "frontend", "debugging", "code", "generic"):
                artifact = "artifacts/not-a-real-check.json" if name == "code" else "artifacts/test-result.json"
                (checklist_dir / f"{name}.md").write_text(
                    f"# {name}\n\n- Demo invariant. Evidence: `{artifact}`\n",
                    encoding="utf-8",
                )

            proc = run_tool(str(CHECKLIST_CHECK), "--root", str(root))

            self.assertNotEqual(proc.returncode, 0)
            result = json.loads(proc.stdout)
            self.assertFalse(result["passed"])
            self.assertTrue(any(item["type"] == "unknown_deterministic_artifact" for item in result["violations"]))

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
            "wilds-benchmark-task",
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
        self.assertEqual(len(result["templates"]), 8)
        self.assertIn("standard-software-task", {template["id"] for template in result["templates"]})
        self.assertIn("wilds-benchmark-task", {template["id"] for template in result["templates"]})

    def test_installed_style_module_entrypoint_lists_templates(self) -> None:
        proc = run_tool("-m", "maw_cli", "list-templates")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["templates"]), 8)

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
        self.assertEqual(len(result["templates"]), 8)

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

    def test_maw_plan_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            plan = Path(tmp_dir) / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "task_type": "generic",
                        "roles": ["conductor", "planner", "worker", "critic", "acceptance_gate"],
                    }
                ),
                encoding="utf-8",
            )

            proc = run_tool(str(MAW), "plan-check", str(plan))

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["passed"])
            self.assertEqual(result["task_type"], "generic")

    def test_documented_maw_subcommands_exist(self) -> None:
        import maw_cli.cli as maw_cli_module

        documented: set[str] = set()
        for path in (ROOT / "README.md", ROOT / ".codex" / "skills" / "maw" / "SKILL.md"):
            documented.update(re.findall(r"(?m)^\s*maw\s+([a-z][a-z0-9-]+)\b", path.read_text(encoding="utf-8")))

        parser = maw_cli_module.build_parser()
        subcommands = set()
        for action in parser._actions:
            choices = getattr(action, "choices", None)
            if choices:
                subcommands.update(choices)

        self.assertTrue(documented)
        self.assertEqual(set(), documented - subcommands)

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

    def test_ml_validator_artifact_schema_matches_expected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files = {}
            for name in ("leakage", "drift", "baseline", "multi_seed", "shuffled_label"):
                path = root / f"{name}.json"
                path.write_text(json.dumps({"passed": True}) + "\n", encoding="utf-8")
                files[name] = path
            output = root / "ml-validator.json"

            proc = run_tool(
                str(ML_CHECKS),
                "validator",
                "--leakage-file",
                str(files["leakage"]),
                "--drift-file",
                str(files["drift"]),
                "--baseline-file",
                str(files["baseline"]),
                "--multi-seed-file",
                str(files["multi_seed"]),
                "--shuffled-label-file",
                str(files["shuffled_label"]),
                "--output",
                str(output),
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["check"], "ml_validator")
            self.assertEqual(result["schema_version"], 1)
            self.assertTrue(result["passed"])
            self.assertEqual(result["required_evidence"], ["leakage", "drift", "baseline", "multi_seed", "shuffled_label"])
            self.assertEqual(result["evidence"]["leakage"]["expected_artifact"], "artifacts/leakage-audit.json")
            self.assertTrue(all(item["passed"] for item in result["checks"]))

    def test_ml_regression_resistance_mutations_are_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clean = root / "clean.json"
            run_proc = run_tool(str(ML_CLASSIFICATION), "--output", str(clean))
            self.assertEqual(run_proc.returncode, 0, run_proc.stdout + run_proc.stderr)

            validate_proc = run_tool(str(ML_CHECKS), str(clean))
            self.assertEqual(validate_proc.returncode, 0, validate_proc.stdout + validate_proc.stderr)

            result = json.loads(clean.read_text(encoding="utf-8"))
            mutations = {
                "leaky_feature": lambda data: data["features"].append(data["target"]),
                "shuffled_labels": lambda data: data.update({"labels_shuffled": True}),
                "train_test_overlap": lambda data: data["split"]["test_ids"].insert(0, data["split"]["train_ids"][0]),
                "preprocessing_fit_full_data": lambda data: data.update({"preprocessing": {"fit_scope": "full_data"}}),
            }
            for name, mutate in mutations.items():
                bad = json.loads(json.dumps(result))
                mutate(bad)
                bad_path = root / f"{name}.json"
                bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")

                bad_proc = run_tool(str(ML_CHECKS), str(bad_path))

                self.assertNotEqual(bad_proc.returncode, 0, name)
                validation = json.loads(bad_proc.stdout)
                self.assertFalse(validation["passed"])

            output = root / "regression-resistance.json"
            resistance_proc = run_tool(str(ML_CHECKS), "regression-resistance", "--result-file", str(clean), "--output", str(output))

            self.assertEqual(resistance_proc.returncode, 0, resistance_proc.stdout + resistance_proc.stderr)
            resistance = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(resistance["passed"])
            self.assertEqual(resistance["summary"], {"total": 17, "caught": 17})
            self.assertEqual(
                {item["name"] for item in resistance["mutations"]},
                {
                    "leaky_feature",
                    "shuffled_labels",
                    "train_test_overlap",
                    "preprocessing_fit_full_data",
                    "missing_metric",
                    "insignificant_shuffled_label",
                    "unstable_multi_seed",
                    "weak_baseline_ci",
                    "bad_calibration_stats",
                    "content_duplicate_leakage",
                    "group_entity_leakage",
                    "temporal_leakage",
                    "high_feature_target_correlation",
                    "distribution_drift",
                    "hard_imbalanced_majority",
                    "hard_content_duplicate",
                    "hard_temporal_leak",
                },
            )
            self.assertTrue(all(item["caught"] and item["mutant_passed"] is False for item in resistance["mutations"]))

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


    def test_ml_classification_metrics_imbalance_auc_and_slices(self) -> None:
        proc = run_tool(
            str(ML_CHECKS),
            "classification-metrics",
            "--data-json",
            json.dumps({"labels": [0, 0, 0, 0, 1], "predictions": [0, 0, 0, 0, 0], "scores": [0.1, 0.2, 0.1, 0.3, 0.2]}),
            "--metric-name",
            "macro_f1",
            "--min-metric",
            "0.7",
        )
        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertEqual(result["metrics"]["accuracy"], 0.8)
        self.assertLess(result["metrics"]["macro_f1"], 0.7)
        self.assertIn("confusion_matrix", result)
        self.assertIn("roc_auc", result["metrics"])
        self.assertIn("pr_auc", result["metrics"])

    def test_ml_hard_examples_are_required_failures(self) -> None:
        for filename, expected in [
            ("imbalanced_majority_model.json", "classification_metrics"),
            ("content_duplicate_leaky.json", "content_duplicate_leakage"),
            ("temporal_leak.json", "temporal_leakage"),
        ]:
            with self.subTest(filename=filename):
                proc = run_tool(str(ML_CHECKS), str(ROOT / "examples" / "ml_problems" / "hard_examples" / filename))
                self.assertNotEqual(proc.returncode, 0)
                failed = {item["check"] for item in json.loads(proc.stdout)["checks"] if not item["passed"]}
                self.assertIn(expected, failed)

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
            json.dumps([0.49, 0.50, 0.51, 0.52] * 10),
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


    def test_ml_leakage_and_drift_checks_catch_real_failures(self) -> None:
        clean = {
            "seed": 1,
            "expected_seed": 1,
            "features": ["x1", "x2"],
            "target": "target",
            "group_column": "group_id",
            "time_column": "timestamp",
            "split": {"train_ids": [1, 2, 3], "test_ids": [4, 5, 6], "expected_train_ratio": 0.5},
            "rows": [
                {"id": 1, "x1": 1.0, "x2": 2.0, "target": 0, "group_id": "a", "timestamp": "2024-01-01"},
                {"id": 2, "x1": 2.0, "x2": 3.0, "target": 1, "group_id": "b", "timestamp": "2024-01-02"},
                {"id": 3, "x1": 3.0, "x2": 5.0, "target": 0, "group_id": "c", "timestamp": "2024-01-03"},
                {"id": 4, "x1": 4.0, "x2": 7.0, "target": 1, "group_id": "d", "timestamp": "2024-01-04"},
                {"id": 5, "x1": 5.0, "x2": 11.0, "target": 0, "group_id": "e", "timestamp": "2024-01-05"},
                {"id": 6, "x1": 6.0, "x2": 13.0, "target": 1, "group_id": "f", "timestamp": "2024-01-06"},
            ],
            "metrics": {"accuracy": 0.9},
            "metric_checks": [{"name": "accuracy", "direction": "at_least", "threshold": 0.8}],
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            clean_path = root / "clean.json"
            clean_path.write_text(json.dumps(clean), encoding="utf-8")
            clean_proc = run_tool(str(ML_CHECKS), str(clean_path))
            self.assertEqual(clean_proc.returncode, 0, clean_proc.stdout + clean_proc.stderr)
            for name, mutate, failed_check in [
                ("content", lambda data: data["rows"][3].update({"x1": 1.0, "x2": 2.0}), "content_duplicate_leakage"),
                ("group", lambda data: data["rows"][3].update({"group_id": "a"}), "group_entity_leakage"),
                ("temporal", lambda data: data["rows"][3].update({"timestamp": "2024-01-02"}), "temporal_leakage"),
                ("correlation", lambda data: (data.update({"features": ["leaky_score"], "max_abs_feature_target_correlation": 0.95}), [row.update({"leaky_score": float(row["target"])}) for row in data["rows"]]), "high_feature_target_correlation"),
            ]:
                bad = json.loads(json.dumps(clean))
                mutate(bad)
                path = root / f"{name}.json"
                path.write_text(json.dumps(bad), encoding="utf-8")
                proc = run_tool(str(ML_CHECKS), str(path))
                self.assertNotEqual(proc.returncode, 0, name)
                failed = {item["check"] for item in json.loads(proc.stdout)["checks"] if not item["passed"]}
                self.assertIn(failed_check, failed)
            drift = run_tool(str(ML_CHECKS), "drift", "--data-json", json.dumps({"train": {"x": [1, 1, 1, 2, 2]}, "test": {"x": [10, 11, 12, 13, 14]}}))
            self.assertNotEqual(drift.returncode, 0)
            self.assertFalse(json.loads(drift.stdout)["passed"])

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

    def test_artifacts_parse_check_parses_json_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            artifacts = run_dir / "artifacts"
            artifacts.mkdir()
            (artifacts / "good.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
            (artifacts / "bad.json").write_text("{bad json", encoding="utf-8")
            output = artifacts / "artifact-parse-report.json"

            proc = run_tool(
                str(CHECKS),
                "artifacts-parse",
                "--run",
                str(run_dir),
                "--artifacts",
                "artifacts/good.json",
                "artifacts/bad.json",
                "--output",
                str(output),
            )
            self.assertTrue(output.is_file())

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertTrue(any("bad.json" in error for error in result["errors"]))

    def test_wilds_benchmark_joins_out_of_order_predictions_by_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "manifest.json"
            predictions = root / "predictions.json"
            output = root / "wilds-harness-result.json"
            manifest.write_text(
                json.dumps(
                    {
                        "dataset": {"name": "fixture-wilds", "version": "1"},
                        "fixed_splits": True,
                        "examples": [
                            {"id": "a", "split": "train", "label": "0"},
                            {"id": "b", "split": "val", "label": "1"},
                            {"id": "c", "split": "test", "label": "1"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            predictions.write_text(
                json.dumps({"predictions": [{"id": "c", "prediction": "1"}, {"id": "a", "prediction": "0"}, {"id": "b", "prediction": "1"}]}),
                encoding="utf-8",
            )

            proc = run_tool(str(MAW), "wilds-benchmark", str(manifest), str(predictions), "--output", str(output))
            self.assertTrue(output.is_file())
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual(result["prediction_alignment"], "example_id")
        self.assertEqual(result["splits"]["test"]["accuracy"], 1.0)
        self.assertEqual(result["examples"]["joined_count"], 3)

    def test_wilds_benchmark_rejects_missing_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "manifest.json"
            predictions = root / "predictions.json"
            manifest.write_text(json.dumps({"examples": [{"id": "a", "split": "test", "label": "0"}]}), encoding="utf-8")
            predictions.write_text(json.dumps({"predictions": []}), encoding="utf-8")

            proc = run_tool(str(MAW), "wilds-benchmark", str(manifest), str(predictions))

        self.assertNotEqual(proc.returncode, 0)
        result = json.loads(proc.stdout)
        self.assertFalse(result["passed"])
        self.assertEqual(result["problems"][0]["type"], "missing_predictions")

    def test_wilds_benchmark_uses_dataset_eval_with_fake_wilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_wilds = root / "wilds"
            fake_wilds.mkdir()
            (fake_wilds / "__init__.py").write_text(
                "\n".join(
                    [
                        "class FakeSubset:",
                        "    ids = ['b', 'a']",
                        "    y_array = ['label-b', 'label-a']",
                        "    metadata_array = [{'group': 'g2'}, {'group': 'g1'}]",
                        "",
                        "class FakeDataset:",
                        "    version = 'offline-test'",
                        "    def get_subset(self, split, transform=None):",
                        "        assert split == 'test'",
                        "        assert transform is None",
                        "        return FakeSubset()",
                        "    def eval(self, all_y_pred, all_y_true, all_metadata):",
                        "        assert all_y_pred == ['pred-b', 'pred-a']",
                        "        assert all_y_true == ['label-b', 'label-a']",
                        "        assert all_metadata == [{'group': 'g2'}, {'group': 'g1'}]",
                        "        return {'official_metric': 0.123, 'local_accuracy_would_differ': 999}, 'official eval used'",
                        "",
                        "def get_dataset(dataset, download=False, root_dir=None):",
                        "    assert dataset == 'fake-wilds'",
                        "    assert download is False",
                        "    assert root_dir is None",
                        "    return FakeDataset()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            predictions = root / "predictions.json"
            output = root / "result.json"
            predictions.write_text(
                json.dumps({"predictions": [{"id": "a", "prediction": "pred-a"}, {"id": "b", "prediction": "pred-b"}]}),
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [sys.executable, str(MAW), "wilds-benchmark", str(predictions), "--wilds-dataset", "fake-wilds", "--split", "test", "--output", str(output)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertTrue(output.is_file())
            result = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics_source"], "wilds.dataset.eval")
        self.assertEqual(result["metrics"]["official_metric"], 0.123)
        self.assertEqual(result["metrics_summary"], "official eval used")
        self.assertNotIn("splits", result)

    def test_wilds_export_runs_model_and_scores_with_fake_wilds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_wilds = root / "wilds"
            fake_wilds.mkdir()
            (fake_wilds / "__init__.py").write_text(
                "\n".join(
                    [
                        "class FakeSubset:",
                        "    ids = ['b', 'a']",
                        "    y_array = ['label-b', 'label-a']",
                        "    metadata_array = [{'group': 'g2'}, {'group': 'g1'}]",
                        "    examples = ['text for b', {'tokens': ['text', 'for', 'a']}]",
                        "    def __len__(self):",
                        "        return 2",
                        "    def __getitem__(self, index):",
                        "        return self.examples[index], self.y_array[index], self.metadata_array[index]",
                        "",
                        "class FakeDataset:",
                        "    version = 'offline-export-test'",
                        "    def get_subset(self, split, transform=None):",
                        "        assert split == 'test'",
                        "        assert transform is None",
                        "        return FakeSubset()",
                        "    def eval(self, all_y_pred, all_y_true, all_metadata):",
                        "        assert all_y_pred == ['pred-b', 'pred-a']",
                        "        assert all_y_true == ['label-b', 'label-a']",
                        "        assert all_metadata == [{'group': 'g2'}, {'group': 'g1'}]",
                        "        return {'official_metric': 0.456, 'local_accuracy_would_differ': 999}, 'official export eval used'",
                        "",
                        "def get_dataset(dataset, download=False, root_dir=None):",
                        "    assert dataset == 'fake-wilds'",
                        "    assert download is False",
                        "    assert root_dir is None",
                        "    return FakeDataset()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            model = root / "fake_model.py"
            model.write_text(
                "\n".join(
                    [
                        "import json",
                        "import sys",
                        "",
                        "rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]",
                        "assert rows[0]['id'] == 'b'",
                        "assert rows[0]['text'] == 'text for b'",
                        "assert rows[1]['id'] == 'a'",
                        "assert rows[1]['x'] == {'tokens': ['text', 'for', 'a']}",
                        "predictions = [{'id': 'a', 'prediction': 'pred-a'}, {'id': 'b', 'prediction': 'pred-b'}]",
                        "with open(sys.argv[2], 'w', encoding='utf-8') as handle:",
                        "    json.dump({'predictions': predictions}, handle)",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            export = root / "examples.jsonl"
            predictions = root / "predictions.json"
            score = root / "score.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(MAW),
                    "wilds-export",
                    "--wilds-dataset",
                    "fake-wilds",
                    "--split",
                    "test",
                    "--output",
                    str(export),
                    "--model-cmd",
                    f"{sys.executable} {model} {{input}} {{output}}",
                    "--predictions-output",
                    str(predictions),
                    "--score-output",
                    str(score),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            exported_rows = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines()]
            prediction_data = json.loads(predictions.read_text(encoding="utf-8"))
            score_data = json.loads(score.read_text(encoding="utf-8"))
            result = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual(result["export"]["example_count"], 2)
        self.assertEqual([row["id"] for row in exported_rows], ["b", "a"])
        self.assertEqual(exported_rows[0]["text"], "text for b")
        self.assertIn("x", exported_rows[1])
        self.assertEqual([row["id"] for row in prediction_data["predictions"]], ["a", "b"])
        self.assertTrue(score_data["passed"])
        self.assertEqual(score_data["metrics_source"], "wilds.dataset.eval")
        self.assertEqual(score_data["metrics"]["official_metric"], 0.456)
        self.assertNotIn("splits", score_data)

    def test_wilds_export_limit_accepts_jsonl_predictions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_wilds = root / "wilds"
            fake_wilds.mkdir()
            (fake_wilds / "__init__.py").write_text(
                "\n".join(
                    [
                        "class FakeSubset:",
                        "    ids = ['c', 'b', 'a']",
                        "    y_array = ['label-c', 'label-b', 'label-a']",
                        "    metadata_array = [{'group': 'g3'}, {'group': 'g2'}, {'group': 'g1'}]",
                        "    examples = ['text c', 'text b', 'text a']",
                        "    def __len__(self):",
                        "        return 3",
                        "    def __getitem__(self, index):",
                        "        return self.examples[index], self.y_array[index], self.metadata_array[index]",
                        "",
                        "class FakeDataset:",
                        "    version = 'offline-limit-test'",
                        "    def get_subset(self, split, transform=None):",
                        "        assert split == 'val'",
                        "        assert transform is None",
                        "        return FakeSubset()",
                        "    def eval(self, all_y_pred, all_y_true, all_metadata):",
                        "        assert all_y_pred == ['pred-c', 'pred-b']",
                        "        assert all_y_true == ['label-c', 'label-b']",
                        "        assert all_metadata == [{'group': 'g3'}, {'group': 'g2'}]",
                        "        return {'official_metric': 0.789}, 'limited official eval used'",
                        "",
                        "def get_dataset(dataset, download=False, root_dir=None):",
                        "    assert dataset == 'fake-wilds'",
                        "    assert download is False",
                        "    return FakeDataset()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            model = root / "fake_model_jsonl.py"
            model.write_text(
                "\n".join(
                    [
                        "import json",
                        "import sys",
                        "rows = [json.loads(line) for line in open(sys.argv[1], encoding='utf-8') if line.strip()]",
                        "assert [row['id'] for row in rows] == ['c', 'b']",
                        "with open(sys.argv[2], 'w', encoding='utf-8') as handle:",
                        "    handle.write(json.dumps({'id': 'b', 'prediction': 'pred-b'}) + '\\n')",
                        "    handle.write(json.dumps({'id': 'c', 'prediction': 'pred-c'}) + '\\n')",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            export = root / "examples.jsonl"
            predictions = root / "examples-predictions.jsonl"
            score = root / "score.json"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(MAW),
                    "wilds-export",
                    "--wilds-dataset",
                    "fake-wilds",
                    "--split",
                    "val",
                    "--limit",
                    "2",
                    "--output",
                    str(export),
                    "--model-cmd",
                    f"{sys.executable} {model} {{input}} {{output}}",
                    "--score-output",
                    str(score),
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            result = json.loads(proc.stdout)
            exported_rows = [json.loads(line) for line in export.read_text(encoding="utf-8").splitlines()]
            prediction_rows = [json.loads(line) for line in predictions.read_text(encoding="utf-8").splitlines()]
            score_data = json.loads(score.read_text(encoding="utf-8"))

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual(result["limit"], 2)
        self.assertEqual([row["id"] for row in exported_rows], ["c", "b"])
        self.assertEqual([row["id"] for row in prediction_rows], ["b", "c"])
        self.assertEqual(score_data["limit"], 2)
        self.assertEqual(score_data["metrics_source"], "wilds.dataset.eval")
        self.assertEqual(score_data["metrics"]["official_metric"], 0.789)

    def test_civilcomments_model_preserves_ids_with_fake_wilds_and_sklearn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fake_wilds = root / "wilds"
            fake_wilds.mkdir()
            (fake_wilds / "__init__.py").write_text(
                "\n".join(
                    [
                        "class FakeSubset:",
                        "    y_array = [0, 1, 0]",
                        "    examples = ['clean comment', 'toxic comment', 'another clean comment']",
                        "    def __len__(self):",
                        "        return 3",
                        "    def __getitem__(self, index):",
                        "        return self.examples[index], self.y_array[index], {}",
                        "",
                        "class FakeDataset:",
                        "    def get_subset(self, split, transform=None):",
                        "        assert split == 'train'",
                        "        return FakeSubset()",
                        "",
                        "def get_dataset(dataset, download=False, root_dir=None):",
                        "    assert dataset == 'civilcomments'",
                        "    assert download is False",
                        "    return FakeDataset()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            sklearn_root = root / "sklearn"
            (sklearn_root / "feature_extraction").mkdir(parents=True)
            (sklearn_root / "linear_model").mkdir()
            (sklearn_root / "pipeline").mkdir()
            (sklearn_root / "__init__.py").write_text("", encoding="utf-8")
            (sklearn_root / "feature_extraction" / "__init__.py").write_text("", encoding="utf-8")
            (sklearn_root / "feature_extraction" / "text.py").write_text(
                "class TfidfVectorizer:\n    def __init__(self, **kwargs):\n        self.kwargs = kwargs\n",
                encoding="utf-8",
            )
            (sklearn_root / "linear_model" / "__init__.py").write_text(
                "class LogisticRegression:\n    def __init__(self, **kwargs):\n        self.kwargs = kwargs\n",
                encoding="utf-8",
            )
            (sklearn_root / "pipeline" / "__init__.py").write_text(
                "\n".join(
                    [
                        "class Pipeline:",
                        "    def __init__(self, steps):",
                        "        self.steps = steps",
                        "    def fit(self, texts, labels):",
                        "        assert texts == ['clean comment', 'toxic comment', 'another clean comment']",
                        "        assert labels == [0, 1, 0]",
                        "        return self",
                        "    def predict(self, texts):",
                        "        return [1 if 'toxic' in text else 0 for text in texts]",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            export = root / "examples.jsonl"
            export.write_text(
                "\n".join(
                    [
                        json.dumps({"id": "x1", "text": "not toxic"}),
                        json.dumps({"id": "x2", "x": "very toxic"}),
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            output = root / "predictions.jsonl"
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [sys.executable, str(BASELINE_MODEL), str(export), str(output)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
            result = json.loads(proc.stdout)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(result["passed"])
        self.assertEqual([row["id"] for row in rows], ["x1", "x2"])
        self.assertEqual([row["prediction"] for row in rows], [1, 1])

    def test_maw_tools_never_import_wilds_or_torch(self) -> None:
        forbidden = {"wilds", "torch"}
        violations: list[tuple[Path, str]] = []
        for path in (ROOT / "maw-tools").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in forbidden:
                            violations.append((path, alias.name))
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden:
                    violations.append((path, node.module))
        self.assertEqual(violations, [])

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
