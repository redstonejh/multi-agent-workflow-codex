# data_quality_auditor

Optional ML validation agent used by workflow templates that need data quality checks.

## Mission
Check basic data quality signals before ML validation or training proceeds.

## Inputs
- Data quality JSON with row count, missing value counts, and duplicate row count.
- Allowed missing and duplicate rates.

## Outputs
- Data quality JSON report.
- Summary of blocking data issues.

## Required Artifacts
- `artifacts/data-quality-report.json`

## Deterministic Tools / Checks Used
- `python examples/ml_problems/ml_checks.py data-quality --data-file <data-quality.json> --output artifacts/data-quality-report.json`

## Pass / Fail Criteria
- PASS when row count is valid and missing/duplicate rates are within thresholds.
- FAIL when metadata is malformed or rates exceed thresholds.
