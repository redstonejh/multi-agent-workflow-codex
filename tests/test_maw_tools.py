from __future__ import annotations

import json
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
TASK_GRAPH = ROOT / "maw-tools" / "task_graph.py"
WORKFLOW_TEMPLATE = ROOT / "maw-tools" / "validate_workflow_template.py"
START_WORKFLOW = ROOT / "maw-tools" / "start_workflow.py"
MAW = ROOT / "maw.py"
PYPROJECT = ROOT / "pyproject.toml"
ML_CHECKS = ROOT / "examples" / "ml_problems" / "ml_checks.py"
ML_CLASSIFICATION = ROOT / "examples" / "ml_problems" / "classification" / "run.py"
ML_REGRESSION = ROOT / "examples" / "ml_problems" / "regression" / "run.py"
ML_DATA_VALIDATION = ROOT / "examples" / "ml_problems" / "data_validation" / "run.py"
ADVANCED_AGENTS = [
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
        proc = run_tool(
            str(ACCEPTANCE),
            "--run",
            "examples/sample_run",
            "--test-cmd",
            "python test_textutil.py",
            "--test-cwd",
            "examples/sample_app",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["verdict"], "SHIP")

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
        self.assertEqual(result["templates"], 6)

    def test_parity_roster_stays_unchanged(self) -> None:
        template = json.loads((ROOT / "templates" / "workflows" / "standard-software-task.json").read_text(encoding="utf-8"))

        self.assertEqual(template["agents"], ["conductor", "planner", "worker", "critic", "acceptance_gate"])

    def test_advanced_agent_prompts_have_required_contract_sections(self) -> None:
        required_sections = [
            "## Mission",
            "## Inputs",
            "## Outputs",
            "## Required Artifacts",
            "## Deterministic Tools / Checks Used",
            "## Pass / Fail Criteria",
        ]

        for agent in ADVANCED_AGENTS:
            path = ROOT / ".codex" / "agents" / f"{agent}.md"
            self.assertTrue(path.is_file(), f"missing {path}")
            text = path.read_text(encoding="utf-8")
            for section in required_sections:
                self.assertIn(section, text, f"{agent} missing {section}")

    def test_advanced_templates_activate_optional_agents_only(self) -> None:
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
        }

        for template_id, agents in expected.items():
            template = json.loads((ROOT / "templates" / "workflows" / f"{template_id}.json").read_text(encoding="utf-8"))
            self.assertEqual(template.get("mode"), "advanced")
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
        self.assertEqual(len(result["templates"]), 6)
        self.assertIn("standard-software-task", {template["id"] for template in result["templates"]})

    def test_installed_style_module_entrypoint_lists_templates(self) -> None:
        proc = run_tool("-m", "maw_cli", "list-templates")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["templates"]), 6)

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
        proc = run_tool(
            str(MAW),
            "acceptance",
            "examples/sample_run",
            "--test-cmd",
            "python test_textutil.py",
            "--test-cwd",
            "examples/sample_app",
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["verdict"], "SHIP")

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
