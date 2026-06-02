# Visual Verifier

## Mission
Document before/after visual evidence when available while keeping deterministic source/style checks as the hard gate.

## Inputs
- UI source files.
- Change verifier output.
- Style drift audit output.
- Optional screenshots or external visual evidence supplied by the user or environment.

## Outputs
- Visual verification notes that distinguish deterministic evidence from advisory visual observations.

## Required Artifacts
- `artifacts/visual-verification.md`

## Deterministic Tools / Checks Used
- Review raw `changed`, `style`, and `tokens` outputs.
- Optional screenshot comparison may be documented only when an external tool is available.

## Pass / Fail Criteria
Hard PASS/FAIL comes from deterministic source/style checks and token drift checks. Pixel/visual comparison is advisory. Model judgment is advisory. Full automated screenshot diff inside MAW is `# MAW-TODO`.
