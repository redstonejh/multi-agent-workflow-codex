# Restrained Acrylic Utility

Use this style for compact desktop utilities, installers, setup pickers, package managers, and internal tools where the user is trying to complete one task quickly.

The reference product shape is closer to Windows 11 Settings, JetBrains Toolbox, GitHub Desktop, VS Code Extensions, PowerToys, Docker Desktop, and Obsidian than to a dashboard or landing page.

## Deconstruction

### Purpose

This is a task-completion interface. The content is the product. Branding, explanation, onboarding panels, tutorial steps, and decorative regions should be removed unless they directly help the task.

### Layout

- Use a compact utility-dialog window.
- Use two sections: content and sticky footer.
- Put the search field first; it is the visual anchor.
- Use a scrollable row list, not floating cards.
- Put actions in the footer where the workflow ends.
- Keep Exit or destructive tertiary actions on the left; keep Clear, secondary actions, and the primary Install/Apply action on the right.

### Native Acrylic Model

- The operating system or native window material owns blur.
- In Electron on Windows 11, use `backgroundMaterial: "acrylic"` with transparent `backgroundColor`.
- On macOS, use vibrancy.
- Unsupported platforms must use a solid dark fallback.
- Do not add CSS `backdrop-filter` to buttons, search fields, rows, or footer bars. Stacking gaussian blur layers makes controls muddy and visually inconsistent.

### Surfaces

Use translucent tints over one acrylic window surface. Do not add borders around every element.

CoreSetup-derived tokens:

```css
:root {
  --acrylic-panel: rgba(26, 34, 51, .66);
  --acrylic-button: rgba(32, 42, 61, .34);
  --acrylic-search-surface: rgba(39, 49, 70, .512);
  --acrylic-secondary-surface: rgba(52, 64, 88, .26);
  --acrylic-option-hover: rgba(82, 96, 125, .20);
  --acrylic-button-hover: rgba(36, 48, 71, .32);
  --acrylic-selected: rgba(96, 165, 250, .10);
  --acrylic-accent: #3b82f6;
  --acrylic-accent-action: rgba(59, 130, 246, .72);
  --acrylic-text: #f8fafc;
  --acrylic-muted-text: #94a3b8;
  --acrylic-border: rgba(148, 163, 184, .22);
  --acrylic-highlight: rgba(255, 255, 255, .07);
  --acrylic-status-installed: #a7f3d0;
  --acrylic-status-update: #93c5fd;
}
```

`--acrylic-search-surface` is intentionally not the same token as the footer. It was calculated to match the perceived normal secondary button tone over the footer/window stack. When translucent surfaces sit on different parent layers, matching literal RGBA values can produce visibly different darkness.

### Rows

- Rows are full-width selectable list items.
- Use 48-56px row height.
- Use real icons, a visible checkbox, app name, and optional status text.
- Use subtle hover tint only.
- Selected rows should remain mostly transparent; the checked checkbox carries most of the selected signal.
- Avoid thick left rails, large blue blocks, cards, glow, and heavy borders.

### Buttons

- One primary action only.
- Primary action uses the accent action tint.
- Secondary buttons use the neutral button tint.
- Tertiary actions are text-like, transparent, and readable.
- Disabled states should be readable but clearly inactive.
- Do not make every action blue.

### Typography

- Use Segoe UI Variable on Windows.
- Keep row labels around 14-15px medium.
- Keep footer button text around 14px medium.
- Avoid oversized headings; omit headers entirely when the task is self-explanatory.

### Motion

- Keep transitions short and functional.
- Use subtle focus/hover state changes.
- Do not add decorative float, glow, parallax, or landing-page motion.

### Anti-Patterns

Do not use:

- dashboards
- hero headers
- marketing copy
- tutorial step sidebars
- giant rounded cards
- neon cyan/teal accents
- decorative glass borders
- CSS blur on each component
- white-on-white glass
- acronym placeholder icons
- package IDs in client-facing rows

## Implementation Checklist

- Native window acrylic/vibrancy or solid fallback is configured.
- `html` and `body` are transparent when native acrylic is active.
- Exactly one main window tint sits above the native material.
- Component surfaces are tints only; no `backdrop-filter`.
- Search, footer, button, hover, and selected states are tuned by perceived composite color, not by copied RGBA values.
- App list uses rows, checkboxes, real icons, human-readable names, and compact status labels.
- Primary action is visually dominant; secondary and tertiary actions are quieter.
