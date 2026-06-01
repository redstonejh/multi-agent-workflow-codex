# Critic Review

Verdict: PASS.

Checks performed:

- Parity roster remains unchanged in `standard-software-task.json`.
- Advanced agents are optional role files and are activated by advanced templates only.
- Each requested advanced agent has mission, inputs, outputs, required artifacts, deterministic tools, and pass/fail criteria.
- ML deterministic checks now include baseline comparison, calibration/ECE, reproducibility metadata, data quality, and existing leakage/fit diagnosis paths.
- General deterministic checks now include dependency-map and aggregation validation.
- Template validation passed.
- Unit tests passed after correcting the calibration sample threshold.
- Full pytest suite passed.

Residual risks:

- Dependency mapping currently validates declared maps; automatic source extraction remains follow-up.
- Calibration output is ECE-focused and does not yet generate plots or classwise reports.
