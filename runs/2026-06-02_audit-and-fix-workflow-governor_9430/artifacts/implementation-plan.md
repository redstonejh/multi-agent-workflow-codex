# Implementation Plan

1. Add explicit caps to every workflow template and package-data template copy.
2. Extend `plan_check.py` to require core roles and fail with `insufficient_role_cap_for_required_roles` when `max_agents` cannot fit core plus required task specialists.
3. Add task-type aliases for workflow template IDs.
4. Strengthen workflow-template validation so caps are required and must fit the declared roster.
5. Update self-tests, aggregate tests, and unit tests for default generic caps, specialist default-cap failures, template-cap passes, and no core-role dropping.
6. Update docs with the default-vs-template cap policy.
