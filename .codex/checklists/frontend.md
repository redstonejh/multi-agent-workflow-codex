# Frontend Risk Checklist

Task type: `frontend`

- The intended UI target changed and the edit is not a no-op. Evidence: `artifacts/change-verification.json`
- Style values that support the change were extracted and verified. Evidence: `artifacts/style-extraction.json`
- Static accessibility checks pass for required markup. Evidence: `artifacts/a11y-audit.json`
- Text and UI color contrast meets thresholds. Evidence: `artifacts/contrast-check.json`
- Page byte, element, and asset budgets remain within limits. Evidence: `artifacts/perf-budget.json`
- Markup has no duplicate ids or unclosed tags. Evidence: `artifacts/markup-validation.json`
- Internal links, anchors, and local assets resolve. Evidence: `artifacts/link-check.json`
- Design-token and style drift checks pass. Evidence: `artifacts/style-drift-audit.json`
- Responsive layout, visual framing, and interaction feel are reviewed across target viewports. Evidence: `advisory critic-only`
