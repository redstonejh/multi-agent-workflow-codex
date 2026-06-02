# ML Validation Workflow Example

Start an ML validation run:

```bash
maw start ml-validation-task "audit classifier for leakage, baseline, calibration, and fit risk"
```

Expected ML validation agents:

- leakage_auditor
- data_quality_auditor
- baseline_enforcer
- overfitting_checker
- calibration_checker
- reproducibility_checker

Representative deterministic artifacts:

- `artifacts/leakage-audit.json`
- `artifacts/data-quality-report.json`
- `artifacts/baseline-comparison.json`
- `artifacts/fit-diagnosis.json`
- `artifacts/calibration-report.json`
- `artifacts/reproducibility-check.json`
