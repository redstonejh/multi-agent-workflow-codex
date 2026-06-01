# overfitting_checker

Advanced-mode optional agent. Do not include in parity benchmark runs.

## Mission
Diagnose overfitting and underfitting from train, validation, and test metrics.

## Inputs
- Fit metrics JSON with classification scores or regression errors.
- Thresholds from the workflow template or planner.

## Outputs
- Fit diagnosis JSON.
- Short explanation of overfit, underfit, invalid, or healthy status.

## Required Artifacts
- `artifacts/fit-diagnosis.json`

## Deterministic Tools / Checks Used
- `py examples/ml_problems/ml_checks.py fit-diagnosis --problem-type <type> --metrics-file <metrics.json> --output artifacts/fit-diagnosis.json`

## Pass / Fail Criteria
- PASS when the fit diagnosis status is `healthy`.
- FAIL when status is `overfit`, `underfit`, or `invalid`.
