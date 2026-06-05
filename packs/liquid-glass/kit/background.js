(function () {
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const hexToRgb = (hex) => {
    const value = String(hex || "").replace("#", "").trim();
    if (!/^[0-9a-fA-F]{6}$/.test(value)) return null;
    return [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16) / 255);
  };
  const linear = (channel) => channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4);
  const luminance = (hex) => {
    const rgb = hexToRgb(hex);
    if (!rgb) return 0.78;
    const [r, g, b] = rgb.map(linear);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const compensationFor = (bg, bgEnd) => {
    const lum = clamp((luminance(bg) + luminance(bgEnd || bg)) / 2, 0, 1);
    const darkness = 1 - lum;
    return {
      luminance: lum,
      darkness,
      whiteMixCompensation: 0.70 + darkness * 0.22,
      saturationCompensation: Math.min(1.10, 1.08 - Math.max(0, darkness - 0.10) * 0.34),
      surfaceGlassAlpha: 0.68 - darkness * 0.18,
      exposureCompensation: 0.24 - darkness * 0.22
    };
  };
  const applyBackground = (name, root) => {
    const target = root || document.documentElement;
    const palette = name || "frosted-light";
    target.dataset.background = palette;
    const styles = getComputedStyle(target);
    const values = compensationFor(styles.getPropertyValue("--bg").trim(), styles.getPropertyValue("--bg-end").trim());
    target.style.setProperty("--workspace-bg-luminance", values.luminance.toFixed(4));
    target.style.setProperty("--workspace-bg-darkness", values.darkness.toFixed(4));
    target.style.setProperty("--surface-white-mix-compensation", values.whiteMixCompensation.toFixed(4));
    target.style.setProperty("--surface-saturation-compensation", values.saturationCompensation.toFixed(4));
    target.style.setProperty("--surface-glass-alpha", values.surfaceGlassAlpha.toFixed(4));
    target.style.setProperty("--surface-exposure-compensation", values.exposureCompensation.toFixed(4));
    document.body?.classList.toggle("has-photo-background", palette.startsWith("photo-") || palette === "solar-system");
    return values;
  };
  window.LiquidGlassBackground = { applyBackground, compensationFor };
})();
