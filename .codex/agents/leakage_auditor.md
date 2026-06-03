# leakage_auditor

Optional ML validation agent used by workflow templates that need leakage checks.

## Mission
Find target leakage, train/test contamination, split overlap, content-duplicate leakage, group/entity leakage, temporal leakage, high feature-target correlation, and claim leakage risks before model conclusions are accepted.

## Inputs
- Dataset schema, feature list, target name, split metadata, and ML result JSON.
- Planner handoff with the validation question and acceptable leakage tolerance.

## Outputs
- Leakage audit summary.
- Deterministic leakage check JSON.

## Required Artifacts
- `artifacts/leakage-audit.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py validate <result.json> --output artifacts/leakage-audit.json`

## Pass / Fail Criteria
- PASS when no split overlap, no content duplicate across splits, no group/entity overlap, train timestamps precede test timestamps, no target-like columns, no excessive feature-target correlation, and no documented contamination risk remains.
- FAIL when leakage is detected, split IDs overlap, content rows duplicate across splits, group IDs cross splits, temporal order is violated, target-like columns appear in features, high feature-target correlation is detected, or required metadata is missing.
