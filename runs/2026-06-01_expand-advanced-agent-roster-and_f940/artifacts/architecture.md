# Advanced Agent Architecture

Advanced mode is opt-in at the workflow-template layer. The parity roster remains unchanged for parity workflows:

`conductor, planner, worker, critic, acceptance_gate`

Advanced templates may add specialized roles when the task requires extra verification or coordination. The MVP maps:

- ML validation/training: leakage_auditor, data_quality_auditor, baseline_enforcer, overfitting_checker, calibration_checker, reproducibility_checker.
- Bug investigation: debugger, bug_hunter, dependency_mapper.
- Multi-agent research: aggregator.

Deterministic checks live in stdlib Python tools:

- `examples/ml_problems/ml_checks.py`: leakage, data quality, baseline comparison, calibration/ECE, reproducibility, fit diagnosis.
- `maw-tools/checks.py`: dependency map validation and aggregation completeness.

Templates declare advanced agents and required artifacts; `start_workflow.py` creates only the agents required by the chosen template.
