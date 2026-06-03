# Refactor Risk Checklist

Task type: `refactor`

- Public API signatures remain compatible. Evidence: `artifacts/behavior-diff.json`
- Public `repr()` and `str()` formatting remains byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Serialized JSON/CSV/export bytes remain byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Golden report text and fixture outputs remain byte-for-byte compatible. Evidence: `artifacts/behavior-diff.json`
- Probe process exit codes, stderr, raised exception type/message, and written-file bytes remain compatible. Evidence: `artifacts/behavior-diff.json`
- Legacy aliases, import paths, and registry/import-time state remain compatible. Evidence: `artifacts/behavior-diff.json`
- The baseline was captured before the first source edit and is deterministic across two pre-edit captures. Evidence: `artifacts/behavior-baseline.json`
- Every changed source line is exercised by at least one baseline probe or test; uncovered changed lines fail as "behavior surface not covered". Evidence: `artifacts/refactor-coverage.json`
- Public functions/classes, signatures, default values, and `__all__` remain unchanged unless the plan explicitly justifies an API change. Evidence: `artifacts/api-surface-diff.json`
- The plan declares `refactor_type` (`rename`, `extract-function`, `inline`, `move-module`, or `dedupe`) and the matching AST structural invariant passes. Evidence: `artifacts/refactor-structure.json`
- Changed functions do not increase cyclomatic complexity, max nesting depth, or function length beyond plan tolerance unless explicitly justified. Evidence: `artifacts/complexity-report.json`
- Behavior probes do not exceed the plan's median wall-time/trace-line performance budget; noisy hosts may mark the gate advisory, but clear regressions fail. Evidence: `artifacts/perf-budget.json`
- Planted post-refactor behavior mutations are caught by the behavior diff; a baseline that catches nothing fails. Evidence: `artifacts/refactor-resistance.json`
- Edge cases and undocumented caller assumptions are inventoried before approval. Evidence: `artifacts/refactor-plan.md`
