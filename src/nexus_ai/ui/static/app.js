(function () {
  const app = document.getElementById("app-shell");
  const toggleButtons = document.querySelectorAll("[data-action='toggle-sidebar']");
  const overlay = document.querySelector(".sidebar-overlay");
  const STORAGE_KEY = "nexus.sidebar";

  function setCollapsed(value) {
    if (!app) return;
    if (value) {
      app.classList.add("sidebar-collapsed");
      localStorage.setItem(STORAGE_KEY, "collapsed");
    } else {
      app.classList.remove("sidebar-collapsed");
      localStorage.setItem(STORAGE_KEY, "expanded");
    }
  }

  function toggleSidebar() {
    if (!app) return;
    if (window.matchMedia("(max-width: 980px)").matches) {
      app.classList.toggle("sidebar-open");
      return;
    }
    const collapsed = app.classList.contains("sidebar-collapsed");
    setCollapsed(!collapsed);
  }

  function closeMobileSidebar() {
    if (!app) return;
    app.classList.remove("sidebar-open");
  }

  if (app) {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "collapsed") {
      app.classList.add("sidebar-collapsed");
    }
  }

  toggleButtons.forEach((btn) => btn.addEventListener("click", toggleSidebar));
  if (overlay) {
    overlay.addEventListener("click", closeMobileSidebar);
  }

  document.querySelectorAll("[data-auto-submit]").forEach((el) => {
    el.addEventListener("change", () => {
      const form = el.closest("form");
      if (form) form.submit();
    });
  });

  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", closeMobileSidebar);
  });
})();
