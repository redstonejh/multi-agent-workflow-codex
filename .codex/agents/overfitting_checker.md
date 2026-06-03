# overfitting_checker

Optional ML validation agent used by workflow templates that need fit diagnosis.

## Mission
Diagnose overfitting and underfitting from train, validation, and test metrics using the chosen metric, including macro_f1 for imbalanced classification.

## Inputs
- Fit metrics JSON with train_<metric>, validation_<metric>, and test_<metric> for classification, or regression errors.
- Thresholds from the workflow template or planner.

## Outputs
- Fit diagnosis JSON.
- Short explanation of overfit, underfit, invalid, or healthy status.

## Required Artifacts
- `artifacts/fit-diagnosis.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py fit-diagnosis --problem-type <type> --metrics-file <metrics.json> --output artifacts/fit-diagnosis.json`

## Pass / Fail Criteria
- PASS when the fit diagnosis status is `healthy`.
- FAIL when status is `overfit`, `underfit`, or `invalid`.
