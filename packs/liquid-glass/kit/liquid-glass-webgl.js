(function () {
  function initLiquidGlass(options) {
    const opts = options || {};
    const photoSelector = opts.photoSelector || "[data-liquid-glass-photo]";
    const surfaceSelector = opts.surfaceSelector || ".glass,.glass-strong,.glass-control,.glass-popover";
    const canvas = document.createElement("canvas");
    canvas.className = "liquid-glass-webgl-canvas";
    canvas.setAttribute("aria-hidden", "true");
    canvas.style.cssText = "position:fixed;inset:0;z-index:0;pointer-events:none;display:none";
    document.body.appendChild(canvas);
    const api = {
      canvas,
      photoSelector,
      surfaceSelector,
      enable() {
        document.body.classList.add("webgl-glass-on");
        canvas.style.display = "block";
      },
      disable() {
        document.body.classList.remove("webgl-glass-on");
        canvas.style.display = "none";
      },
      collectSurfaces() {
        return Array.from(document.querySelectorAll(surfaceSelector)).map((node) => node.getBoundingClientRect());
      }
    };
    window.LiquidGlassWebGL = api;
    return api;
  }
  window.initLiquidGlass = initLiquidGlass;
})();
