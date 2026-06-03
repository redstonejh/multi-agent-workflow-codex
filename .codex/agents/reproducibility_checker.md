# reproducibility_checker

Optional ML validation agent used by workflow templates that need reproducibility checks.

## Mission
Verify that ML runs record reproducible seed, deterministic setting, and optional config hash metadata.

## Inputs
- Training config JSON or result JSON with seed and deterministic metadata.
- Expected seed and optional expected config hash.

## Outputs
- Reproducibility check JSON.
- Reproducibility risks and next action.

## Required Artifacts
- `artifacts/reproducibility-check.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py reproducibility --data-file <run-metadata.json> --output artifacts/reproducibility-check.json`

## Pass / Fail Criteria
- PASS when seed, deterministic flag, and optional config hash match expectations.
- FAIL when reproducibility metadata is missing or mismatched.
