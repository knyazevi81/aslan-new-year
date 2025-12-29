// Minimal progressive enhancement for sliders (range inputs).
// No frameworks. If JS is disabled, the server-rendered value is still shown.
(function () {
  function initRange(range) {
    var outId = range.getAttribute("data-output");
    if (!outId) return;
    var out = document.getElementById(outId);
    if (!out) return;

    function sync() {
      out.textContent = String(range.value);
    }

    range.addEventListener("input", sync);
    range.addEventListener("change", sync);
    sync();
  }

  function boot() {
    var ranges = document.querySelectorAll('input[type="range"][data-output]');
    for (var i = 0; i < ranges.length; i++) initRange(ranges[i]);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();