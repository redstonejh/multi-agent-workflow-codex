# Worker Output

Implemented cap policy and validation:
- Added explicit caps to all workflow templates and package-data copies.
- Added `insufficient_role_cap_for_required_roles` to `plan_check.py`.
- Required all core roles in conductor plans.
- Added task-type aliases for template IDs.
- Required and validated template caps in `validate_workflow_template.py`.
- Updated self-tests, aggregate checks, unit tests, README, AGENTS.md, conductor docs, and MAW skill docs.
