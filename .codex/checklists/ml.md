# ML Risk Checklist

Task type: `ml`

- Train/test leakage, target leakage, and split overlap are absent. Evidence: `artifacts/leakage-audit.json`
- Data quality thresholds for missingness, duplicates, and invalid rows are met. Evidence: `artifacts/data-quality-report.json`
- Model performance beats the declared baseline by the required margin. Evidence: `artifacts/baseline-comparison.json`
- Fit diagnosis does not show overfit or underfit behavior. Evidence: `artifacts/fit-diagnosis.json`
- Calibration is within the declared threshold when probabilities are claimed. Evidence: `artifacts/calibration-report.json`
- Run metadata proves reproducibility and deterministic configuration. Evidence: `artifacts/reproducibility-check.json`
- Shuffled-label performance collapses toward chance or baseline. Evidence: `artifacts/shuffled-label-check.json`
- Multi-seed performance is stable and every seed clears the metric floor. Evidence: `artifacts/multi-seed-stability.json`
- Dataset shift, label policy drift, and metric gaming risks are considered. Evidence: `advisory critic-only`
