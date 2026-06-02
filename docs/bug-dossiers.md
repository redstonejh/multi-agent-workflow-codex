# Bug Dossiers

Bug dossiers document known bugs and high-severity dependency risks in a stable format.

## Location

```text
docs/bugs/<id>.md
```

## Required Format

```markdown
# <id>: <title>

Status: open
Severity: high

## Affected files
- path/to/file.py

## Affected symbols
- function_or_constant

## Root cause
Short explanation of the defect or hidden dependency.

## Reproduction steps, if applicable
1. Run or change the smallest thing that demonstrates the issue.

## Expected behavior
What should happen.

## Actual behavior
What happens instead.

## Fix strategy
Concrete remediation plan.

## Regression tests needed
- Test name or scenario.

## Links to run artifacts
- runs/<run_id>/artifacts/<artifact>

## Date discovered
YYYY-MM-DD

## Date fixed, if fixed
not fixed
```

Use dossiers for high-severity dependency risks, recurring bugs, and fixes that need future maintainers to understand root cause rather than only symptoms.
