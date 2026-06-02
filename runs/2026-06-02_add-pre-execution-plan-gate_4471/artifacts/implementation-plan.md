# Implementation Plan

1. Add `maw-tools/plan_check.py` with a centralized rule table, JSON input/output, exit 0/1, and explicit violations for unknown roles, duplicate roles, missing acceptance gate, missing task validators, cap overruns, and unjustified optional roles.
2. Add a Codex-native `plan_reviewer` agent definition and wire the conductor and MAW skill docs so plan review happens before execution.
3. Update acceptance-gate guidance to verify plan-gate evidence in completed runs.
4. Add self-tests and repo tests for the deterministic plan gate, including ML, frontend, and code required-role rules.
5. Add a planted demo run showing a missing ML validator fails first, then passes after replanning.
6. Update README with only verified behavior and example commands.
