#!/usr/bin/env python3
"""Plan MAW dependency graphs into parallel worker, aggregate, and merge stages."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TASK_TYPES = {"worker", "aggregate", "merge"}


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    type: str
    depends_on: tuple[str, ...]
    worker: str | None = None


class GraphError(ValueError):
    pass


def load_graph(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GraphError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GraphError("graph must be a JSON object")
    return data


def parse_tasks(data: dict[str, Any]) -> list[Task]:
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise GraphError("graph must contain a non-empty 'tasks' list")

    tasks: list[Task] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            raise GraphError(f"tasks[{index}] must be an object")

        task_id = raw.get("id")
        title = raw.get("title", task_id)
        task_type = raw.get("type", "worker")
        depends_on = raw.get("depends_on", [])
        worker = raw.get("worker")

        if not isinstance(task_id, str) or not task_id:
            raise GraphError(f"tasks[{index}].id must be a non-empty string")
        if task_id in seen:
            raise GraphError(f"duplicate task id: {task_id}")
        if not isinstance(title, str) or not title:
            raise GraphError(f"task {task_id}: title must be a non-empty string")
        if task_type not in TASK_TYPES:
            raise GraphError(f"task {task_id}: type must be one of {sorted(TASK_TYPES)}")
        if not isinstance(depends_on, list) or not all(isinstance(dep, str) for dep in depends_on):
            raise GraphError(f"task {task_id}: depends_on must be a list of task ids")
        if worker is not None and (not isinstance(worker, str) or not worker):
            raise GraphError(f"task {task_id}: worker must be a non-empty string")

        seen.add(task_id)
        tasks.append(Task(task_id, title, task_type, tuple(depends_on), worker))

    known = {task.id for task in tasks}
    by_id = {task.id: task for task in tasks}
    for task in tasks:
        for dep in task.depends_on:
            if dep not in known:
                raise GraphError(f"task {task.id}: unknown dependency {dep}")
        if task.type in {"aggregate", "merge"} and not task.depends_on:
            raise GraphError(f"task {task.id}: {task.type} tasks must depend on prior work")
        if task.type == "merge":
            dep_types = {by_id[dep].type for dep in task.depends_on}
            if "aggregate" not in dep_types:
                raise GraphError(f"task {task.id}: merge tasks must depend on at least one aggregate task")

    return tasks


def plan_stages(tasks: list[Task]) -> list[list[Task]]:
    by_id = {task.id: task for task in tasks}
    remaining = {task.id for task in tasks}
    completed: set[str] = set()
    stages: list[list[Task]] = []

    while remaining:
        ready = [
            task
            for task in tasks
            if task.id in remaining and all(dep in completed for dep in task.depends_on)
        ]
        if not ready:
            cycle_ids = ", ".join(sorted(remaining))
            raise GraphError(f"cycle detected or unsatisfied dependencies among: {cycle_ids}")

        stages.append(ready)
        for task in ready:
            remaining.remove(task.id)
            completed.add(task.id)

    for stage_index, stage in enumerate(stages, start=1):
        if stage_index == 1:
            for task in stage:
                if task.type in {"aggregate", "merge"}:
                    raise GraphError(f"task {task.id}: {task.type} task cannot be in the first stage")
        for task in stage:
            if task.type == "aggregate":
                dep_types = {by_id[dep].type for dep in task.depends_on}
                if "merge" in dep_types:
                    raise GraphError(f"task {task.id}: aggregate task cannot depend on merge output")

    return stages


def stage_to_json(index: int, tasks: list[Task]) -> dict[str, Any]:
    worker_tasks = [task for task in tasks if task.type == "worker"]
    return {
        "stage": index,
        "parallel": len(worker_tasks) > 1,
        "types": sorted({task.type for task in tasks}),
        "worker_lanes": [
            {
                "task_id": task.id,
                "worker": task.worker or f"worker_{task.id}",
            }
            for task in worker_tasks
        ],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "type": task.type,
                "depends_on": list(task.depends_on),
                **({"worker": task.worker} if task.worker else {}),
            }
            for task in tasks
        ],
    }


def plan_graph(data: dict[str, Any]) -> dict[str, Any]:
    tasks = parse_tasks(data)
    stages = plan_stages(tasks)
    return {
        "passed": True,
        "task_count": len(tasks),
        "stages": [stage_to_json(index, stage) for index, stage in enumerate(stages, start=1)],
    }


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        result = plan_graph(load_graph(Path(args.file)))
    except GraphError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, indent=2))
        return 1

    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan MAW task graphs into executable stages.")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="validate and stage a graph JSON file")
    plan.add_argument("--file", required=True, help="path to graph JSON")
    plan.set_defaults(func=cmd_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
