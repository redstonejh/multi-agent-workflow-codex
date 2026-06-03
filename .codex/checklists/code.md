# Code Risk Checklist

Task type: `code`

- Public tests and deterministic test commands pass. Evidence: `artifacts/test-result.json`
- Run-specific JSON artifacts parse as JSON objects and are not accepted by existence alone. Evidence: `artifacts/artifact-parse-report.json`
- Checklist links and deterministic artifact references are valid. Evidence: `artifacts/checklist-validation.json`
- Relevant dependencies and coupling boundaries are mapped. Evidence: `artifacts/dependency-map.json`
- Hidden dependency risks are documented or explicitly mitigated. Evidence: `artifacts/dependency-risk-report.json`
- Hidden tests, golden outputs, invariants, and regression risks are reviewed adversarially. Evidence: `advisory critic-only`
- Backward compatibility, error handling, and edge-case behavior are considered for changed code. Evidence: `advisory critic-only`
