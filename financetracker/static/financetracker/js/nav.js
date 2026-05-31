(function () {
  const STORAGE_KEY = "ft-sidebar-collapsed";
  const MOBILE_MQ = window.matchMedia("(max-width: 768px)");

  const body = document.body;
  const toggle = document.querySelector(".sidebar-toggle");
  const sidebar = document.querySelector(".sidebar");
  const backdrop = document.querySelector(".sidebar-backdrop");
  if (!toggle || !sidebar) return;

  function isMobile() {
    return MOBILE_MQ.matches;
  }

  function setCollapsed(collapsed) {
    body.classList.toggle("sidebar-collapsed", collapsed && !isMobile());
    if (!isMobile()) {
      try {
        localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
      } catch (_) { /* ignore */ }
    }
    updateToggleAria();
    notifyLayoutChange();
  }

  function setMobileOpen(open) {
    const on = open && isMobile();
    body.classList.toggle("sidebar-mobile-open", on);
    if (backdrop) backdrop.hidden = !on;
    updateToggleAria();
    notifyLayoutChange();
  }

  function notifyLayoutChange() {
    window.dispatchEvent(new Event("resize"));
  }

  function updateToggleAria() {
    const mobile = isMobile();
    const expanded = mobile
      ? body.classList.contains("sidebar-mobile-open")
      : !body.classList.contains("sidebar-collapsed");
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.setAttribute(
      "aria-label",
      expanded ? "Close navigation" : "Open navigation"
    );
  }

  function loadDesktopState() {
    if (isMobile()) return;
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "1");
    } catch (_) {
      setCollapsed(false);
    }
  }

  toggle.addEventListener("click", function () {
    if (isMobile()) {
      setMobileOpen(!body.classList.contains("sidebar-mobile-open"));
    } else {
      setCollapsed(!body.classList.contains("sidebar-collapsed"));
    }
  });

  if (backdrop) {
    backdrop.addEventListener("click", function () {
      setMobileOpen(false);
    });
  }

  document.addEventListener("click", function (e) {
    if (!isMobile() || !body.classList.contains("sidebar-mobile-open")) return;
    if (sidebar.contains(e.target) || toggle.contains(e.target)) return;
    setMobileOpen(false);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && isMobile()) setMobileOpen(false);
  });

  sidebar.querySelectorAll(".sidebar-link").forEach(function (link) {
    link.addEventListener("click", function () {
      if (isMobile()) setMobileOpen(false);
    });
  });

  function onBreakpointChange() {
    if (isMobile()) {
      body.classList.remove("sidebar-collapsed");
      setMobileOpen(false);
    } else {
      body.classList.remove("sidebar-mobile-open");
      loadDesktopState();
    }
    updateToggleAria();
  }

  MOBILE_MQ.addEventListener("change", onBreakpointChange);
  loadDesktopState();
  updateToggleAria();
})();
