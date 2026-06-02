# leakage_auditor

Optional ML validation agent used by workflow templates that need leakage checks.

## Mission
Find target leakage, train/test contamination, split overlap, and claim leakage risks before model conclusions are accepted.

## Inputs
- Dataset schema, feature list, target name, split metadata, and ML result JSON.
- Planner handoff with the validation question and acceptable leakage tolerance.

## Outputs
- Leakage audit summary.
- Deterministic leakage check JSON.

## Required Artifacts
- `artifacts/leakage-audit.json`
- `artifacts/data-audit.md`

## Deterministic Tools / Checks Used
- `py examples/ml_problems/ml_checks.py validate <result.json>`
- `py examples/ml_problems/ml_checks.py data-quality --data-file <data-quality.json>`

## Pass / Fail Criteria
- PASS when no split overlap, no feature-target leakage, and no documented contamination risk remains.
- FAIL when leakage is detected, split IDs overlap, target-like columns appear in features, or required metadata is missing.
