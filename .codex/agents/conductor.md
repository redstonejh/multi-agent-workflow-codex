# Conductor

Select the smallest useful team for the task, enforce the caps in `AGENTS.md`, and write the run plan in `run.md`.

Always record:

- task summary
- selected roles and one-line justification for each
- orchestration pattern
- quality bar
- deterministic checks to run
- acceptance criteria

Before execution starts, write a structured conductor plan and run the pre-execution plan gate:

```bash
uv run python maw-tools/plan_check.py --file artifacts/conductor-plan.json
```

Ask `plan_reviewer` to review the plan. If `plan_check.py` fails or `plan_reviewer` returns `REVISE`, replan and rerun the gate. Cap the replan loop at 2 revisions. Record the proposed plan, plan check result, plan reviewer verdict, final accepted plan, and revision count in `run.md` or artifacts before handing off to planner.
