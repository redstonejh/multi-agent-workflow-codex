# Conductor Plan

## Selected Team
Core MAW roles are sufficient for repository implementation. The front-end pack itself adds workflow-specific agents for future runs: `ui_builder`, `a11y_auditor`, `responsive_checker`, `perf_budgeter`, `markup_validator`, and `ux_critic`.

## Scope
Build a stdlib-only front-end/UI pack on top of the existing MAW framework:
- deterministic web checks
- agent prompts
- front-end skill
- workflow template
- red-to-green demo
- self-tests and aggregate self-test
- README update

## Constraints
All Python commands must use `uv run python`. No browser and no npm. Browser visual regression, rendering checks, hard-gated aesthetics, and viewport screenshot testing must remain `# MAW-TODO`.
