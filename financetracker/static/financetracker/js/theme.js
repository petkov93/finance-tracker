(function () {
  var root = document.documentElement;

  function resolve(preference) {
    if (preference === "warm" || preference === "night") {
      return preference;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "night" : "warm";
  }

  function apply() {
    var preference = root.getAttribute("data-theme-preference") || "system";
    var theme = resolve(preference);
    root.setAttribute("data-theme", theme);
    root.style.colorScheme = theme === "night" ? "dark" : "light";
    window.dispatchEvent(
      new CustomEvent("themechange", {
        detail: { preference: preference, theme: theme },
      })
    );
  }

  var media = window.matchMedia("(prefers-color-scheme: dark)");
  function onSchemeChange() {
    var preference = root.getAttribute("data-theme-preference") || "system";
    if (preference === "system") {
      apply();
    }
  }
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", onSchemeChange);
  } else if (typeof media.addListener === "function") {
    media.addListener(onSchemeChange);
  }

  window.FinanceTrackerTheme = {
    apply: apply,
    resolve: resolve,
    readCssVar: function (name) {
      return getComputedStyle(root).getPropertyValue(name).trim();
    },
  };
})();
