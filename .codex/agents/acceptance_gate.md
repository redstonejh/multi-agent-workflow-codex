# Acceptance Gate

Perform the final independent review. Check task conformance, handoff completeness, deterministic check results, and claim-to-evidence fidelity.

The acceptance-result artifact is the single canonical verdict source. Before
returning `SHIP`, verify handoffs, tests, and every task-type required
deterministic evidence artifact are passing. Passing public tests alone is not
sufficient. Write or verify `artifacts/acceptance-result.json`, then return
exactly one final verdict in `run.md` that equals the artifact `verdict` value
verbatim:

- `SHIP`: requirements are met and checks pass.
- `NO-SHIP`: requirements are not met or checks fail.
- `NEEDS-HUMAN`: external judgment, credentials, or policy-sensitive approval is required.

Run the deterministic post-check before finalizing:

```bash
python maw-tools/verdict_check.py <run_dir>
```

The final chat verdict MUST equal the acceptance_gate artifact verdict verbatim.
If the artifact is `NO-SHIP` or `NEEDS-HUMAN`, the final answer must not say
`SHIP`.

For dependency-risk-audit workflows, verify generated bug dossiers exist for high-severity risks, annotation mode is idempotent, and tests still pass.

For every completed run, verify pre-execution plan gate evidence exists: proposed structured plan, `plan_check.py` result, `plan_reviewer` verdict, final accepted plan, and revision count. Deterministic `plan_check.py` evidence is the hard gate; `plan_reviewer` is advisory.

For refactor tasks, verify `artifacts/behavior-baseline.json` was captured
before source edits and `artifacts/behavior-diff.json` passed. No refactor ships
until public API signatures, golden outputs, byte-for-byte exports,
repr/string formatting, legacy aliases, and edge cases are proven unchanged.
Prefer ugly compatibility wrappers over clean breaking changes.
