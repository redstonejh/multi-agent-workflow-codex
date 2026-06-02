#!/usr/bin/env python3
"""Start a MAW run from a workflow template."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

import validate_workflow_template


HANDOFF_TEMPLATE = """# Hand-off: {frm} -> {to}  (run {run_id}, step {step:02d})

## Task context
{task}

## What I did
Initialized this handoff from workflow template `{template_id}`. Fill in completed work before passing to the next role.

## Output / artifacts
- artifacts/artifact-checklist.md  (required artifacts for this template)

## Open questions / risks
Template placeholder; replace with run-specific risks.

## Recommended next step
{to} should follow the workflow template and update this handoff with concrete results.
"""

RUN_TEMPLATE = """# Run {run_id}

- Task: {task}
- Workflow template: {template_id}
- Created: {created}
- Status: in-progress

## Conductor plan
Started from workflow template `{template_id}`.

Agents:
{agents}

Deterministic checks:
{checks}

Acceptance gates:
{gates}

## Required Artifact Checklist
See `artifacts/artifact-checklist.md`.

## Final result summary
Pending acceptance gate.
"""

MEMORY_TEMPLATE = """# Shared Journal - {run_id}

## {time} - conductor
Started run from workflow template `{template_id}`.
"""

AGENT_TEMPLATE = """# {agent} Notes - {run_id}

Initialized from workflow template `{template_id}`.
"""


def slugify(text: str, max_words: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:max_words]) if words else "run"


def repo_template_dir(repo_root: Path) -> Path:
    return repo_root / "templates" / "workflows"


def resolve_template(repo_root: Path, template_name: str) -> tuple[Path | None, list[str]]:
    workflows = repo_template_dir(repo_root)
    candidates = [
        workflows / f"{template_name}.json",
        workflows / template_name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate, []
    return None, [f"unknown workflow template: {template_name}"]


def load_valid_template(repo_root: Path, template_name: str) -> tuple[dict[str, Any] | None, Path | None, list[str]]:
    path, errors = resolve_template(repo_root, template_name)
    if path is None:
        return None, None, errors

    errors = validate_workflow_template.validate_template(path)
    if errors:
        return None, path, errors
    template, load_errors = validate_workflow_template.load_json(path)
    if template is None:
        return None, path, load_errors
    return template, path, []


def write_artifact_checklist(run_dir: Path, template: dict[str, Any]) -> None:
    lines = [
        "# Required Artifact Checklist",
        "",
        f"Workflow template: `{template['id']}`",
        "",
    ]
    for artifact in template["required_artifacts"]:
        lines.append(f"- [ ] `{artifact}`")
    lines.append("")
    (run_dir / "artifacts" / "artifact-checklist.md").write_text("\n".join(lines), encoding="utf-8")


def write_handoffs(run_dir: Path, template: dict[str, Any], task: str) -> list[str]:
    paths: list[str] = []
    for index, handoff in enumerate(template["handoffs"], start=1):
        frm = handoff["from"]
        to = handoff["to"]
        path = run_dir / "handoffs" / f"{index:02d}_{frm}__to__{to}.md"
        path.write_text(
            HANDOFF_TEMPLATE.format(
                frm=frm,
                to=to,
                run_id=run_dir.name,
                step=index,
                task=task,
                template_id=template["id"],
            ),
            encoding="utf-8",
        )
        paths.append(str(path))
    return paths


def create_run(repo_root: Path, template: dict[str, Any], template_path: Path, task: str, root: Path, slug: str | None) -> dict[str, Any]:
    run_id = f"{dt.datetime.now().strftime('%Y-%m-%d')}_{slug or slugify(task)}_{secrets.token_hex(2)}"
    run_dir = root / run_id
    if run_dir.exists():
        raise RuntimeError(f"run folder already exists: {run_dir}")

    (run_dir / "agents").mkdir(parents=True)
    (run_dir / "handoffs").mkdir()
    (run_dir / "artifacts").mkdir()

    agents = "\n".join(f"- {agent}" for agent in template["agents"])
    checks = "\n".join(f"- {check['name']}: `{check['command']}`" for check in template["deterministic_checks"])
    gates = "\n".join(f"- {gate}" for gate in template["acceptance_gates"])
    created = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    run_dir.joinpath("run.md").write_text(
        RUN_TEMPLATE.format(
            run_id=run_id,
            task=task,
            template_id=template["id"],
            created=created,
            agents=agents,
            checks=checks,
            gates=gates,
        ),
        encoding="utf-8",
    )
    run_dir.joinpath("memory.md").write_text(
        MEMORY_TEMPLATE.format(
            run_id=run_id,
            template_id=template["id"],
            time=dt.datetime.now().strftime("%H:%M"),
        ),
        encoding="utf-8",
    )
    for agent in template["agents"]:
        (run_dir / "agents" / f"{agent}.md").write_text(
            AGENT_TEMPLATE.format(agent=agent, run_id=run_id, template_id=template["id"]),
            encoding="utf-8",
        )

    shutil.copyfile(template_path, run_dir / "artifacts" / "workflow-template.json")
    write_artifact_checklist(run_dir, template)
    handoffs = write_handoffs(run_dir, template, task)

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "template": template["id"],
        "template_copy": str(run_dir / "artifacts" / "workflow-template.json"),
        "artifact_checklist": str(run_dir / "artifacts" / "artifact-checklist.md"),
        "handoffs": handoffs,
        "agents": template["agents"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start a MAW run from a workflow template.")
    parser.add_argument("template", help="workflow template id or JSON filename")
    parser.add_argument("task", help="task description")
    parser.add_argument("--repo-root", default=".", help="repository root containing templates/workflows")
    parser.add_argument("--root", default="runs", help="run root directory")
    parser.add_argument("--slug", help="explicit run slug")
    parser.add_argument("--json", action="store_true", help="print JSON output")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root)
    template, template_path, errors = load_valid_template(repo_root, args.template)
    if errors or template is None or template_path is None:
        result = {"passed": False, "errors": errors}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("; ".join(errors), file=sys.stderr)
        return 1

    try:
        result = create_run(repo_root, template, template_path, args.task, Path(args.root), args.slug)
    except RuntimeError as exc:
        result = {"passed": False, "errors": [str(exc)]}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    result["passed"] = True
    print(json.dumps(result, indent=2) if args.json else result["run_dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
