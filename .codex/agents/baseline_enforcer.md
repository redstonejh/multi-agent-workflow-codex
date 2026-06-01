# baseline_enforcer

Advanced-mode optional agent. Do not include in parity benchmark runs.

## Mission
Ensure a model or approach beats the declared baseline by the required margin before claims are accepted.

## Inputs
- Metrics JSON containing model and baseline metric values.
- Direction of improvement and minimum improvement threshold.

## Outputs
- Baseline comparison JSON.
- Recommendation to continue, revise, or reject the model claim.

## Required Artifacts
- `artifacts/baseline-comparison.json`

## Deterministic Tools / Checks Used
- `py examples/ml_problems/ml_checks.py baseline --metrics-file <metrics.json> --output artifacts/baseline-comparison.json`

## Pass / Fail Criteria
- PASS when model improvement meets or exceeds the configured threshold.
- FAIL when baseline metrics are missing, direction is invalid, or improvement is insufficient.
