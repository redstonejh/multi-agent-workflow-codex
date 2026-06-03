# Salvage Risk Checklist

Task type: `salvage`

- The preserved surface and entrypoints are frozen before iteration 0 and the hash remains unchanged. Evidence: `artifacts/salvage-result.json`
- Preserved behavior has byte-for-byte parity on the frozen surface. Evidence: `artifacts/preserve-parity.json`
- Hidden dependencies are graph-derived, source-documented with `MAW-DEP[id]`, and covered by tests. Evidence: `artifacts/hidden-deps.json`
- Removed legacy symbols are unreachable from the frozen surface and unreferenced by kept reachable code. Evidence: `artifacts/dead-code.json`
- Duplicate logic has exactly one declared survivor and former call sites reroute to it. Evidence: `artifacts/duplication.json`
- Planted hidden-dependency, dead-reference, duplicate, and behavior-break failures are caught by the gates. Evidence: `artifacts/salvage-resistance.json`
