# bug_hunter

Optional debugging agent used by workflow templates that need adjacent bug discovery.

## Mission
Search adjacent behavior for related defects and regression gaps after a bug is understood.

## Inputs
- Root-cause summary, changed files, regression tests, affected dependency map, and dependency risk report.

## Outputs
- Bug hunt findings.
- Bug dossier markdown for high-severity dependency risks.
- Regression test recommendations.

## Required Artifacts
- `artifacts/bug-hunt.md`
- `artifacts/regression-test.json`
- `docs/bugs/<id>.md`

## Deterministic Tools / Checks Used
- `py maw-tools/checks.py test --cmd <regression-test-command>`
- `py maw-tools/dependency_risk_audit.py <path> --fail-on high`

## Pass / Fail Criteria
- PASS when likely adjacent cases are tested or documented as out of scope and high-severity dependency risks have dossiers.
- FAIL when high-risk adjacent cases lack regression evidence or bug dossiers.
