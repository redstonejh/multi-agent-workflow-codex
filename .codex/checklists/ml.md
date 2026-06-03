# ML Risk Checklist

Task type: `ml`

- Train/test leakage, target leakage, split ID overlap, content-duplicate leakage, group/entity leakage, temporal leakage, and high feature-target correlation are absent. Evidence: `artifacts/leakage-audit.json`
- Core ML validation evidence is aggregated in the required schema and all source evidence passes. Evidence: `artifacts/ml-validator.json`
- Data quality thresholds for missingness, duplicates, and invalid rows are met. Evidence: `artifacts/data-quality-report.json`
- Classification claims report confusion matrix, per-class and macro precision/recall/F1, ROC-AUC/PR-AUC when scores exist, and gate on an imbalance-aware metric. Evidence: `artifacts/classification-metrics.json`
- Model performance beats the declared baseline by requiring the seeded bootstrap CI lower bound to clear the required margin. Evidence: `artifacts/baseline-comparison.json`
- Fit diagnosis does not show overfit or underfit behavior. Evidence: `artifacts/fit-diagnosis.json`
- Calibration is within the declared threshold when probabilities are claimed. Evidence: `artifacts/calibration-report.json`
- Run metadata proves reproducibility and deterministic configuration. Evidence: `artifacts/reproducibility-check.json`
- Shuffled-label performance collapses toward chance or baseline and reports a permutation p-value at alpha <= 0.05. Evidence: `artifacts/shuffled-label-check.json`
- Multi-seed performance reports mean, std, seeded bootstrap CI, coefficient of variation, and every seed clears the metric floor; max_variance is legacy optional. Evidence: `artifacts/multi-seed-stability.json`
- Planted ML regressions are caught by candidate validation tests. Evidence: `artifacts/regression-resistance.json`
- Distribution drift is within PSI and KS thresholds. Evidence: `artifacts/drift-report.json`
