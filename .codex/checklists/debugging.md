# Debugging Risk Checklist

Task type: `debugging`

- The dependency map covers affected files, symbols, and data edges. Evidence: `artifacts/dependency-map.json`
- Hidden dependency risks and high-severity couplings are reported. Evidence: `artifacts/dependency-risk-report.json`
- A regression test or deterministic reproducer covers the bug. Evidence: `artifacts/regression-test.json`
- Root cause explains why the failure happened and why the fix is scoped. Evidence: `advisory critic-only`
- Adjacent edge cases and negative cases are considered beyond the public reproducer. Evidence: `advisory critic-only`
