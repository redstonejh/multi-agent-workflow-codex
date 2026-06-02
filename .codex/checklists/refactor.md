# Refactor Risk Checklist

Task type: `refactor`

- Public API signatures remain compatible. Evidence: `artifacts/behavior-diff.json`
- Public `repr()` and `str()` formatting remains byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Serialized JSON/CSV/export bytes remain byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Golden report text and fixture outputs remain byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Legacy aliases, import paths, and registry/import-time state remain compatible. Evidence: `artifacts/behavior-diff.json`
- The baseline was captured before the first source edit. Evidence: `artifacts/behavior-baseline.json`
- Edge cases and undocumented caller assumptions are inventoried before approval. Evidence: `advisory critic-only`
