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

## Restrained Acrylic Utility

`packs/restrained-acrylic-utility/` captures the CoreSetup desktop utility
style. It is a reference pack for native/Electron utilities, not an automatic
HTML injection pack.

Use it when building:

- desktop installers
- package pickers
- setup utilities
- small internal tools where the user completes one task quickly

The style is intentionally restrained:

- native OS acrylic/vibrancy owns blur
- component surfaces use translucent tints only
- no CSS `backdrop-filter` on buttons, search, rows, or footer
- dense list rows instead of cards
- search first, row list second, sticky footer actions last
- one primary action, quieter secondary actions, text-like tertiary actions
- no hero headers, dashboard panels, decorative glow, neon accents, or tutorial sidebars

The pack includes `STYLE.md` for the full deconstruction and `tokens.css` for
the CoreSetup-derived surface palette. Because it targets native desktop apps,
`maw apply-design restrained-acrylic-utility ...` should return `NEEDS-HUMAN`
until a native-app-specific applier exists.
