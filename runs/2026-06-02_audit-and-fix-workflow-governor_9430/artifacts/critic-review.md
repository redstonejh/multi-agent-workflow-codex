# Critic Review

Verdict: APPROVE

Correctness:
- Generic core plans still pass under default caps.
- ML and frontend plans using default caps now fail with `insufficient_role_cap_for_required_roles`.
- Template caps provide enough headroom for specialist workflows.
- Plans cannot pass by dropping planner, worker, critic, conductor, or acceptance gate.

Maintainability:
- Required-role rules, task aliases, and role aliases remain centralized in `plan_check.py`.
- Template caps are validated by `validate_workflow_template.py`.
- Package-data mirrors were updated.

Scope:
- No framework rewrite.
- No working features removed.
- Refactor remains core-only because this repo does not define `refactor_scout` or `refactorer`.
