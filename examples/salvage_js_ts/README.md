# Salvage JS/TS Fixture

Small dirty JS/TS fixture for the optional `maw code-graph --lang js|ts` adapter.

- `system.ts` is the preserved system surface.
- `state.ts` contains a hidden mutable global coupling.
- `dead.ts` is legacy code intended for removal.
- `duplicate.ts` contains duplicated logic that should collapse to one survivor.
