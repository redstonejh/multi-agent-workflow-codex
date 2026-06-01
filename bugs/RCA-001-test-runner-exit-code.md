# RCA BUG-001: `checks.py test` exited 0 even when the test command failed

Severity: medium   Status: fixed (with a self-test)   Found-by: review while
chasing a (later-debunked) file-corruption report

## Symptom
`maw-tools/checks.py test` reported the correct verdict in its JSON
(`"passed": false` for a failing command) but the **process exit code was always
0**. Any caller that gates on the exit code — the acceptance gate, a CI step, a
shell `&&` chain — would read a failing test as success.

## Root cause
`cmd_test` ended with `return _emit({...})`, and the `_emit` helper returns 0
(it only prints JSON). So the function's return value — which becomes the process
exit code — was hard-wired to 0 regardless of whether the test passed. The JSON
payload and the exit code disagreed; consumers that trusted the exit code were
silently misled. `cmd_gap` had the same shape (always exited 0).

## Why not caught
- **No self-test for the checker.** The tool everything else trusts had no test
  asserting it goes red on known-bad input.
- **The JSON looked right**, so a human reading the output saw `passed: false`
  and assumed the tool was fine — the exit-code path was never exercised.

## Fix
- `cmd_test` and `cmd_gap` now `return 0 if passed else 1`, so the process exit
  code tracks the verdict.
- Added **`maw-tools/selftest_checks.py`**, which runs `checks.py` against a
  known-passing and a known-failing command (and an in/out-of-tolerance `gap`)
  and asserts both the JSON `passed` field and the exit code are correct. It
  exits non-zero if any assertion fails. Current status: **all assertions pass**;
  it went red on this bug before the fix.

## Prevention
- A deterministic check must have a self-test proving it returns a failing exit
  code on bad input. Add any new check to `selftest_checks.py`. `# MAW-TODO` wire
  the self-test into a pre-commit hook / CI.

## Note — the file "null-byte corruption" was a sandbox artifact, not a bug
While investigating, a sample file (`examples/sample_app/textutil.py`) was
repeatedly reported as containing a block of trailing NUL bytes that broke import.
This was ultimately traced to a **sandbox/filesystem-view artifact, not real
on-disk corruption** — three independent tools (`od`, plain CPython, PowerShell
.NET) confirmed the file was clean the whole time. The exploratory changes made
under that false premise — a `nullbytes` subcommand in `checks.py`, null-byte
scan requirements and a "distrust the tooling" rewrite of the acceptance gate, and
two RCAs (the old RCA-002/RCA-003) — were **reverted** as churn. Only the genuine,
independently-justified `test`/`gap` exit-code fix above was kept.
