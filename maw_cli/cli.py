"""Single user-facing CLI for Codex MAW."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(__file__).resolve().parent
ROOT = SOURCE_ROOT if (SOURCE_ROOT / "maw-tools").is_dir() else PACKAGE_ROOT / "data"
TOOLS = ROOT / "maw-tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import acceptance_check  # noqa: E402
import dependency_risk_audit  # noqa: E402
import plan_check  # noqa: E402
import run_report  # noqa: E402
import start_workflow  # noqa: E402
import task_graph  # noqa: E402
import validate_handoffs  # noqa: E402
import validate_workflow_template  # noqa: E402
import verdict_check  # noqa: E402
from . import ml_autopilot  # noqa: E402
from . import wilds_benchmark  # noqa: E402


def emit(data: dict) -> None:
    print(json.dumps(data, indent=2))


def cmd_list_templates(args: argparse.Namespace) -> int:
    root = Path(args.root)
    workflows = validate_workflow_template.template_dir(root)
    templates = []
    errors: list[str] = []
    for path in sorted(workflows.glob("*.json")):
        schema_errors = validate_workflow_template.validate_template(path)
        if schema_errors:
            errors.extend(schema_errors)
            continue
        data, load_errors = validate_workflow_template.load_json(path)
        if data is None:
            errors.extend(load_errors)
            continue
        templates.append(
            {
                "id": data["id"],
                "name": data["name"],
                "description": data["description"],
            }
        )
    result = {"passed": not errors, "templates": templates, "errors": errors}
    emit(result)
    return 0 if result["passed"] else 1


def cmd_start(args: argparse.Namespace) -> int:
    argv = [
        args.template,
        args.task,
        "--repo-root",
        args.root,
        "--root",
        args.run_root,
        "--json",
    ]
    if args.slug:
        argv.extend(["--slug", args.slug])
    return start_workflow.main(argv)


def cmd_validate_template(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if args.template:
        template, _path, errors = start_workflow.load_valid_template(root, args.template)
        result = {"template": args.template, "passed": not errors and template is not None, "errors": errors}
    else:
        result = validate_workflow_template.validate_all_templates(root)
    emit(result)
    return 0 if result["passed"] else 1


def cmd_validate_handoffs(args: argparse.Namespace) -> int:
    result = validate_handoffs.validate_run(Path(args.run_folder))
    emit(result)
    return 0 if result["passed"] else 1


def cmd_acceptance(args: argparse.Namespace) -> int:
    argv = ["--run", args.run_folder]
    if args.test_cmd:
        argv.extend(["--test-cmd", args.test_cmd])
    if args.test_cwd:
        argv.extend(["--test-cwd", args.test_cwd])
    argv.extend(["--timeout", str(args.timeout)])
    return acceptance_check.main(argv)


def cmd_verdict_check(args: argparse.Namespace) -> int:
    return verdict_check.main([args.run_folder])


def cmd_plan_check(args: argparse.Namespace) -> int:
    return plan_check.main(["--file", args.plan_json])


def cmd_plan_graph(args: argparse.Namespace) -> int:
    return task_graph.main(["plan", "--file", args.graph_json])


def cmd_run_report(args: argparse.Namespace) -> int:
    return run_report.main([args.run_folder])


def cmd_dependency_audit(args: argparse.Namespace) -> int:
    argv = [args.path]
    if args.annotate:
        argv.append("--annotate")
    if args.dry_run:
        argv.append("--dry-run")
    if args.fail_on:
        argv.extend(["--fail-on", args.fail_on])
    if args.docs_dir:
        argv.extend(["--docs-dir", args.docs_dir])
    if args.no_dossiers:
        argv.append("--no-dossiers")
    if args.output:
        argv.extend(["--output", args.output])
    return dependency_risk_audit.main(argv)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex MAW command-line interface.")
    parser.add_argument("--root", default=str(ROOT), help="repository or installed data root")
    sub = parser.add_subparsers(dest="command", required=True)

    list_templates = sub.add_parser("list-templates", help="list available workflow templates")
    list_templates.set_defaults(func=cmd_list_templates)

    start = sub.add_parser("start", help="start a run from a workflow template")
    start.add_argument("template")
    start.add_argument("task")
    start.add_argument("--run-root", default="runs")
    start.add_argument("--slug")
    start.set_defaults(func=cmd_start)

    validate_template = sub.add_parser("validate-template", help="validate one or all workflow templates")
    validate_template.add_argument("template", nargs="?")
    validate_template.set_defaults(func=cmd_validate_template)

    validate_handoff_cmd = sub.add_parser("validate-handoffs", help="validate run handoff files")
    validate_handoff_cmd.add_argument("run_folder")
    validate_handoff_cmd.set_defaults(func=cmd_validate_handoffs)

    acceptance = sub.add_parser("acceptance", help="run final deterministic acceptance checks")
    acceptance.add_argument("run_folder")
    acceptance.add_argument("--test-cmd")
    acceptance.add_argument("--test-cwd")
    acceptance.add_argument("--timeout", type=float, default=600)
    acceptance.set_defaults(func=cmd_acceptance)

    verdict = sub.add_parser("verdict-check", help="verify run.md final verdict matches acceptance artifact")
    verdict.add_argument("run_folder")
    verdict.set_defaults(func=cmd_verdict_check)

    plan_check_cmd = sub.add_parser("plan-check", help="validate a MAW conductor plan")
    plan_check_cmd.add_argument("plan_json")
    plan_check_cmd.set_defaults(func=cmd_plan_check)

    plan_graph = sub.add_parser("plan-graph", help="plan a MAW dependency graph")
    plan_graph.add_argument("graph_json")
    plan_graph.set_defaults(func=cmd_plan_graph)

    run_report_cmd = sub.add_parser("run-report", help="write artifacts/run-summary.md for a run")
    run_report_cmd.add_argument("run_folder")
    run_report_cmd.set_defaults(func=cmd_run_report)

    dependency_audit = sub.add_parser("dependency-audit", help="detect hidden dependency risks in Python source")
    dependency_audit.add_argument("path")
    dependency_audit.add_argument("--annotate", action="store_true")
    dependency_audit.add_argument("--dry-run", action="store_true")
    dependency_audit.add_argument("--fail-on", choices=["low", "medium", "high"])
    dependency_audit.add_argument("--docs-dir")
    dependency_audit.add_argument("--no-dossiers", action="store_true")
    dependency_audit.add_argument("--output")
    dependency_audit.set_defaults(func=cmd_dependency_audit)
    ml_autopilot.add_parser(sub, ROOT)
    wilds_benchmark.add_parser(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
