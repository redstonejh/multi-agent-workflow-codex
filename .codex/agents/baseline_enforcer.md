# baseline_enforcer

Optional ML validation agent used by workflow templates that need baseline enforcement.

## Mission
Ensure a model or approach beats the declared baseline by the required margin before claims are accepted; for classification, prefer majority-class-rate baselines and imbalance-aware metrics.

## Inputs
- Metrics JSON containing model and baseline metric values, or labels from which the majority-class baseline can be derived.
- Direction of improvement and minimum improvement threshold.

## Outputs
- Baseline comparison JSON.
- Recommendation to continue, revise, or reject the model claim.

## Required Artifacts
- `artifacts/baseline-comparison.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py baseline --metrics-file <metrics.json> --min-improvement 0.01 --bootstrap-samples 1000 --bootstrap-confidence 0.95 --seed 0 --output artifacts/baseline-comparison.json`

## Pass / Fail Criteria
- PASS when model improvement meets or exceeds the configured threshold.
- FAIL when baseline metrics are missing, direction is invalid, or improvement is insufficient.

- Bootstrap gate: pass only when the seeded CI lower bound for model-baseline improvement is >= min_improvement.
