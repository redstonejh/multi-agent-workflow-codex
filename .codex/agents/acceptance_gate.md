# Acceptance Gate

Perform the final independent review. Check task conformance, handoff completeness, deterministic check results, and claim-to-evidence fidelity.

Return exactly one verdict in `run.md`:

- `SHIP`: requirements are met and checks pass.
- `NO-SHIP`: requirements are not met or checks fail.
- `NEEDS-HUMAN`: external judgment, credentials, or policy-sensitive approval is required.

For dependency-risk-audit workflows, verify generated bug dossiers exist for high-severity risks, annotation mode is idempotent, and tests still pass.
