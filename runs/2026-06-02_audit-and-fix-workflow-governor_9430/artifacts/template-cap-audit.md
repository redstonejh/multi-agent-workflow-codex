# Template Cap Audit

Initial inspection found no workflow template with explicit `caps`.

Updated policy:
- `DEFAULT_CAPS` remains `{"max_agents": 5, "max_parallel": 3}` for generic core-agent runs.
- Specialist workflow templates must declare explicit caps.
- `plan_check.py` fails with `insufficient_role_cap_for_required_roles` when core plus required specialist roles cannot fit under `max_agents`.
- `plan_check.py` also fails when a plan drops core roles to fit a cap.

Template caps after change:
- `standard-software-task`: `max_agents` 5
- `refactor-task`: `max_agents` 5
- `bug-investigation`: `max_agents` 8
- `ml-validation-task`: `max_agents` 10
- `ml-training-task`: `max_agents` 10
- `frontend-ui-task`: `max_agents` 13
- `multi-agent-research-task`: `max_agents` 9

Role-rule notes:
- `ml` requires `leakage_auditor` and `baseline_enforcer`.
- `frontend` requires `a11y_auditor` and `change_verifier`.
- `debugging` requires `debugger`, `bug_hunter`, and `dependency_mapper`.
- `refactor` has no separate `refactor_scout` or `refactorer` agent in this repo, so the refactor template remains core-only.
