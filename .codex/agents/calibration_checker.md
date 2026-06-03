# calibration_checker

Optional ML validation agent used by workflow templates that need calibration checks.

## Mission
Check whether predicted probabilities are calibrated well enough for the workflow's risk level.

## Inputs
- Calibration JSON containing `confidences` and `correct` arrays.
- Maximum allowed expected calibration error.

## Outputs
- Calibration/ECE JSON.
- Notes on whether probability claims are supported.

## Required Artifacts
- `artifacts/calibration-report.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py calibration --data-file <calibration.json> --output artifacts/calibration-report.json`

## Pass / Fail Criteria
- PASS when ECE is at or below the configured threshold.
- FAIL when calibration inputs are missing, malformed, or ECE exceeds the threshold.

- Calibration evidence must include ECE, Brier score, Maximum Calibration Error, and the equal-width ECE bias note.
