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
import archive_run  # noqa: E402
import apply_design  # noqa: E402
import code_graph_html  # noqa: E402
import code_graph_py  # noqa: E402
import design_parity  # noqa: E402
import dependency_risk_audit  # noqa: E402
import plan_check  # noqa: E402
import run_report  # noqa: E402
import salvage_check  # noqa: E402
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


def cmd_archive_run(args: argparse.Namespace) -> int:
    argv = [args.run_folder]
    if args.archive_root:
        argv.extend(["--archive-root", args.archive_root])
    if args.target_repo:
        argv.extend(["--target-repo", args.target_repo])
    if args.maw_commit:
        argv.extend(["--maw-commit", args.maw_commit])
    if args.output:
        argv.extend(["--output", args.output])
    return archive_run.main(argv)


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


def cmd_code_graph(args: argparse.Namespace) -> int:
    lang = args.lang
    entry_args = []
    for entrypoint in args.entrypoints or []:
        entry_args.extend(["--entrypoint", entrypoint])
    if lang == "auto":
        return emit_combined_code_graph(Path(args.path), args.output, args.entrypoints or [])
    if lang == "py":
        return code_graph_py.main([args.path, "--output", args.output, *entry_args])
    if lang in {"html", "css"}:
        return code_graph_html.main([args.path, "--lang", lang, "--output", args.output, *entry_args])
    if lang in {"js", "ts"}:
        from . import code_graph_js

        return code_graph_js.main([args.path, "--lang", lang, "--output", args.output, *entry_args])
    emit({"passed": False, "status": "NEEDS-HUMAN", "errors": [f"unsupported language: {args.lang}"]})
    return 1


def graph_suffixes(path: Path) -> set[str]:
    if path.is_file():
        return {path.suffix.lower()}
    ignored = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
    return {item.suffix.lower() for item in path.rglob("*") if item.is_file() and not (set(item.parts) & ignored)}


def merge_graphs(path: Path, graphs: list[dict], entrypoints: list[str]) -> dict:
    modules = []
    symbols = []
    edges = []
    languages = []
    errors = []
    for graph in graphs:
        languages.append(str(graph.get("language", "")))
        modules.extend(item for item in graph.get("modules", []) if isinstance(item, dict))
        symbols.extend(item for item in graph.get("symbols", []) if isinstance(item, dict))
        edges.extend(item for item in graph.get("edges", []) if isinstance(item, dict))
        errors.extend(str(item) for item in graph.get("errors", []) if item)
    if not entrypoints:
        seen = set()
        for graph in graphs:
            for item in graph.get("entrypoints", []):
                if isinstance(item, str):
                    seen.add(item)
        entrypoints = sorted(seen)
    return {
        "schema_version": 1,
        "language": "polyglot",
        "root": str(path.resolve()),
        "modules": sorted(modules, key=lambda item: str(item.get("id", ""))),
        "symbols": sorted(symbols, key=lambda item: str(item.get("id", ""))),
        "edges": sorted(edges, key=lambda item: (str(item.get("type", "")), str(item.get("from", "")), str(item.get("to", "")), int(item.get("location", {}).get("line", 0) or 0))),
        "entrypoints": sorted(entrypoints),
        "adapter_languages": sorted(set(filter(None, languages))),
        "passed": not errors,
        "errors": errors,
    }


def emit_combined_code_graph(path: Path, output: str, entrypoints: list[str]) -> int:
    suffixes = graph_suffixes(path)
    graphs = []
    if suffixes & {".py"}:
        graphs.append(code_graph_py.graph_for(path, entrypoints or None))
    if suffixes & {".html", ".htm", ".jinja", ".jinja2", ".j2", ".css"}:
        graphs.append(code_graph_html.graph_for(path, "auto", entrypoints or None))
    if suffixes & {".js", ".jsx", ".ts", ".tsx"}:
        from . import code_graph_js

        tmp = Path(output).with_suffix(".js-adapter.tmp.json")
        lang = "ts" if suffixes & {".ts", ".tsx"} else "js"
        rc = code_graph_js.main([str(path), "--lang", lang, "--output", str(tmp), *sum((["--entrypoint", item] for item in entrypoints), [])])
        if rc != 0:
            data = json.loads(tmp.read_text(encoding="utf-8")) if tmp.is_file() else {"passed": False, "errors": ["JS/TS adapter failed"]}
            emit({"passed": False, "status": "NEEDS-HUMAN", "errors": data.get("errors", []), "adapter": "js-ts"})
            return 1
        graphs.append(json.loads(tmp.read_text(encoding="utf-8")))
        tmp.unlink(missing_ok=True)
    if not graphs:
        emit({"passed": False, "status": "NEEDS-HUMAN", "errors": ["no supported source files found"]})
        return 1
    result = merge_graphs(path, graphs, entrypoints)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    emit(result)
    return 0 if result.get("passed") is True else 1


def cmd_salvage_check(args: argparse.Namespace) -> int:
    if args.passthrough:
        return salvage_check.main(args.passthrough)
    return salvage_check.main(["verdict", args.run_folder])


def cmd_characterize(args: argparse.Namespace) -> int:
    if args.browser:
        from . import capture_web

        return capture_web.main([args.target, "--output", args.output])
    argv = ["characterize", args.target, "--output", args.output]
    if args.root:
        argv.extend(["--root", args.root])
    if args.test_cmd:
        argv.extend(["--test-cmd", args.test_cmd])
    return salvage_check.main(argv)


def cmd_apply_design(args: argparse.Namespace) -> int:
    argv = [args.pack, args.target, "--photo", args.photo, "--surface-class", args.surface_class]
    if args.output:
        argv.extend(["--output", args.output])
    return apply_design.main(argv)


def cmd_design_parity(args: argparse.Namespace) -> int:
    argv = [args.target, "--reference", args.reference]
    if args.output:
        argv.extend(["--output", args.output])
    return design_parity.main(argv)


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

    archive_cmd = sub.add_parser("archive-run", help="export a curated tamper-evident run archive")
    archive_cmd.add_argument("run_folder")
    archive_cmd.add_argument("--archive-root")
    archive_cmd.add_argument("--target-repo")
    archive_cmd.add_argument("--maw-commit")
    archive_cmd.add_argument("--output")
    archive_cmd.set_defaults(func=cmd_archive_run)

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

    code_graph = sub.add_parser("code-graph", help="emit normalized code graph JSON")
    code_graph.add_argument("path")
    code_graph.add_argument("--lang", choices=["auto", "py", "js", "ts", "html", "css"], default="auto")
    code_graph.add_argument("--entrypoint", action="append", dest="entrypoints")
    code_graph.add_argument("--output", required=True)
    code_graph.set_defaults(func=cmd_code_graph)

    salvage = sub.add_parser("salvage-check", help="run salvage hard gates or pass through a salvage subcommand")
    salvage.add_argument("run_folder")
    salvage.add_argument("passthrough", nargs=argparse.REMAINDER)
    salvage.set_defaults(func=cmd_salvage_check)

    characterize = sub.add_parser("characterize", help="capture a salvage characterization baseline")
    characterize.add_argument("target")
    characterize.add_argument("--root")
    characterize.add_argument("--test-cmd")
    characterize.add_argument("--browser", action="store_true", help="use optional Playwright client-DOM capture")
    characterize.add_argument("--output", required=True)
    characterize.set_defaults(func=cmd_characterize)

    apply_design_cmd = sub.add_parser("apply-design", help="apply a reusable design-language pack to a web target")
    apply_design_cmd.add_argument("pack")
    apply_design_cmd.add_argument("target")
    apply_design_cmd.add_argument("--photo", default="[data-liquid-glass-photo]")
    apply_design_cmd.add_argument("--surface-class", default="glass")
    apply_design_cmd.add_argument("--output")
    apply_design_cmd.set_defaults(func=cmd_apply_design)

    design_parity_cmd = sub.add_parser("design-parity", help="compare an adopted design pack against its frozen reference")
    design_parity_cmd.add_argument("target")
    design_parity_cmd.add_argument("--reference", default=str(ROOT / "packs" / "liquid-glass" / "reference" / "reference-render.json"))
    design_parity_cmd.add_argument("--output")
    design_parity_cmd.set_defaults(func=cmd_design_parity)

    ml_autopilot.add_parser(sub, ROOT)
    wilds_benchmark.add_parser(sub, ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
