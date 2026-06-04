# Salvage Risk Checklist

Task type: `salvage`

- The preserved surface and entrypoints are frozen before iteration 0 and the hash remains unchanged. Evidence: `artifacts/salvage-result.json`
- Static-first test triage partitions tests before surface freeze; only ACTIVE keep-bound tests become the preserved test contract, CUT-bound tests are not executed, and LEGACY symbols are do-not-resurrect. Evidence: `artifacts/test-triage.json`, `artifacts/test-provenance.md`
- Preserved behavior has field-level parity on the frozen surface: geometry tolerates only sub-pixel noise, colors use perceptual epsilon, settled interaction evidence is compared, and multi-object viewport/scroll drift still fails. Evidence: `artifacts/preserve-parity.json`
- Hidden dependencies are graph-derived, source-documented with `MAW-DEP[id]`, and covered by tests. Evidence: `artifacts/hidden-deps.json`
- Removed legacy symbols are unreachable from the frozen surface and unreferenced by kept reachable code. Evidence: `artifacts/dead-code.json`
- Duplicate logic has exactly one declared survivor and former call sites reroute to it. Evidence: `artifacts/duplication.json`
- Planted hidden-dependency, dead-reference, duplicate, behavior-break, hollow-port, viewport-drift, real-move, legacy-resurrection, and sole-coverage-drop failures are caught by the gates. Evidence: `artifacts/salvage-resistance.json`
