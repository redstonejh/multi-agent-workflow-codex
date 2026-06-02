# Bug Investigation Workflow Example

Start a bug investigation run:

```bash
maw start bug-investigation "investigate intermittent API timeout regression"
```

Expected debugging agents:

- debugger
- dependency_mapper
- bug_hunter

Representative deterministic artifacts:

- `artifacts/reproduction.md`
- `artifacts/root-cause.md`
- `artifacts/dependency-map.json`
- `artifacts/bug-hunt.md`
- `artifacts/regression-test.json`
