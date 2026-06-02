# MAW-BUG-0003: Invoice total changes when tax config key is renamed

Status: open
Severity: high

## Affected files
- billing/totals.py
- invoices/export.py
- config/defaults.py

## Affected symbols
- calculate_total
- export_invoice
- tax_rate

## Root cause
`calculate_total()` and `export_invoice()` both depend on the magic string `"tax_rate"` without a shared constant or schema validation.

## Reproduction steps, if applicable
1. Rename `"tax_rate"` in config/defaults.py.
2. Run invoice export.
3. Observe exported totals omit tax.

## Expected behavior
Config key changes should fail validation or be centralized through a shared constant.

## Actual behavior
Invoice export can omit tax when the implicit config key changes.

## Fix strategy
Introduce `TAX_RATE_KEY`, add config schema validation, and add regression tests.

## Regression tests needed
- Test invoice export with the shared tax-rate key.
- Test config validation fails when the tax-rate key is missing.

## Links to run artifacts
- runs/2026-06-02_implement-dependency-risk-audit_3806/artifacts/dependency-risk-audit-architecture.md

## Date discovered
2026-06-02

## Date fixed, if fixed
not fixed
