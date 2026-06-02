# Conductor Plan

Extend the existing front-end/UI pack, not the framework core. The highest-risk gap is that a UI request can currently pass static checks without proving the requested source/style change happened or without guarding design-token drift.

The selected scope adds deterministic hard gates:
- `changed`: compare a target before/after snapshot and optionally expected value.
- `style`: extract a selector/property value from CSS.
- `tokens`: reject CSS values outside `design-tokens.json`.

Browser screenshots, model visual judgment, and rendered viewport comparisons remain advisory or `# MAW-TODO`.
