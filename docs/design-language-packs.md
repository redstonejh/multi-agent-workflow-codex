# Design-Language Packs

MAW design-language packs are reusable UI assets that can be applied to web
targets and checked deterministically. Pack files are data; deterministic tools
in `maw-tools/` stay Python standard-library-only.

## Liquid Glass

`packs/liquid-glass/` contains:

- `kit/`: `tokens.css`, `base.css`, `glass.css`, `components.css`,
  `background.js`, `liquid-glass-webgl.js`, and `glass-kit.css`.
- `manifest.json`: semver, public API, token list, kit content hash, and
  reference metadata.
- `reference/`: standalone demo HTML plus `reference-render.json`, the frozen
  computed-CSS oracle for the `.glass` family across every `data-background`
  palette.

Apply it to a web target:

```bash
maw apply-design liquid-glass <target> --output artifacts/apply-design.json
```

Then prove the adopted kit matches the canonical look:

```bash
maw design-parity <target> --output artifacts/design-parity.json
```

`design-parity` compares the CSS glass baseline. The optional WebGL refraction
helper is shipped as project data and can be initialized with:

```js
initLiquidGlass({ photoSelector: "[data-liquid-glass-photo]", surfaceSelector: ".glass" });
```

Frontend MAW runs can select this optional step when the target is a web/HTML
project. Non-web targets should return `NEEDS-HUMAN` instead of guessing.
