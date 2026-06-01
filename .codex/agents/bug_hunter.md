# bug_hunter

Advanced-mode optional agent. Do not include in parity benchmark runs.

## Mission
Search adjacent behavior for related defects and regression gaps after a bug is understood.

## Inputs
- Root-cause summary, changed files, regression tests, and affected dependency map.

## Outputs
- Bug hunt findings.
- Regression test recommendations.

## Required Artifacts
- `artifacts/bug-hunt.md`
- `artifacts/regression-test.json`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py test --cmd <regression-test-command>`

## Pass / Fail Criteria
- PASS when likely adjacent cases are tested or documented as out of scope.
- FAIL when high-risk adjacent cases lack regression evidence.
