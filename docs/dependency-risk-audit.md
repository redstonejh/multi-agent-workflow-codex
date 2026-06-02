# Dependency Risk Audit

`dependency-risk-audit` is a workflow-specific deterministic check for fragile Python dependencies. It is an optional capability used by debugging and dependency analysis workflows.

## Usage

```bash
python maw-tools/dependency_risk_audit.py path/to/package
python maw-tools/dependency_risk_audit.py path/to/package --fail-on high
python maw-tools/dependency_risk_audit.py path/to/package --annotate
python maw-tools/dependency_risk_audit.py path/to/package --annotate --dry-run
python maw.py dependency-audit path/to/package --output dependency-risk-report.json
```

## Detected Signals

- functions reading or mutating module globals
- environment variable dependencies
- current working directory dependencies
- time or randomness without injection
- mutation of shared mutable arguments
- duplicated literals and implicit config keys
- broad imports and import-time side effects
- cross-module calls
- high fan-in or fan-out
- circular imports
- large functions with mixed responsibilities

## JSON Output

Each risk contains:

- `file`
- `line`
- `symbol`
- `risk_type`
- `severity`
- `explanation`
- `affected_symbols_or_files`
- `recommended_fix`
- `confidence`

## Annotation Mode

`--annotate` inserts short comments above medium and high severity risk lines:

```python
# MAW-DEPENDENCY-RISK: Changing this may affect config.py. Reason: implicit coupling magic string. See docs/bugs/MAW-BUG-1234ABCD.md
```

Annotations are idempotent. Run with `--dry-run` first and review comments before committing. Keep generated comments only when they help future maintainers understand non-obvious coupling.

## Bug Dossiers

High-severity risks generate markdown dossiers under `docs/bugs/` unless `--no-dossiers` is passed. Use those files to record root cause, expected behavior, actual behavior, fix strategy, and regression tests.
