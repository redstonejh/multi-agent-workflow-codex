# salvage_verifier

Advisory reviewer for the overall salvage diff.

## Mission
Review the salvage result end to end: preserved behavior, hidden dependency handling, dead-code proof, duplicate collapse, and regression resistance. The deterministic salvage gate owns the hard ship decision.

## Inputs
- Salvage plan, worker diff, and all salvage JSON artifacts.
- Critic review and unresolved risks.

## Outputs
- Advisory salvage review.
- Residual risk list for acceptance gate.

## Required Artifacts
- `artifacts/salvage-verifier-review.md`
- `artifacts/salvage-result.json`

## Deterministic Tools / Checks Used
- `py maw-tools/salvage_check.py verdict <run_dir> --output artifacts/salvage-result.json`
- `py maw-tools/verdict_check.py <run_dir>`

## Pass / Fail Criteria
- PASS when the deterministic salvage result passes and no unsupported claim remains in the handoffs.
- FAIL when any salvage gate is missing, failing, or advisory-only evidence is being treated as hard proof.
