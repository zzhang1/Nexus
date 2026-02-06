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

  document.querySelectorAll("textarea[data-ctrl-enter='true']").forEach((area) => {
    area.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        const form = area.closest("form");
        if (form) {
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        }
      }
    });
  });

  const loadingOverlay = document.getElementById("loading-overlay");
  const loadingTitle = document.getElementById("loading-title");
  const loadingSubtitle = document.getElementById("loading-subtitle");

  function showLoading(form) {
    if (!loadingOverlay) return;
    const title = form?.getAttribute("data-loading-title");
    const subtitle = form?.getAttribute("data-loading-subtitle");
    if (loadingTitle && title) loadingTitle.textContent = title;
    if (loadingSubtitle && subtitle) loadingSubtitle.textContent = subtitle;
    loadingOverlay.classList.add("active");
    loadingOverlay.setAttribute("aria-hidden", "false");
    document.body.setAttribute("aria-busy", "true");
  }

  function hideLoading() {
    if (!loadingOverlay) return;
    loadingOverlay.classList.remove("active");
    loadingOverlay.setAttribute("aria-hidden", "true");
    document.body.removeAttribute("aria-busy");
  }

  function disableForm(form) {
    if (!form) return;
    form.querySelectorAll("button, input, select, textarea").forEach((el) => {
      if (el.tagName === "BUTTON" || el.type === "submit") {
        el.disabled = true;
      }
    });
  }

  document.querySelectorAll("form").forEach((form) => {
    form.addEventListener("submit", () => {
      const noLoading = form.getAttribute("data-no-loading");
      if (noLoading === "true") return;
      const method = (form.getAttribute("method") || "get").toLowerCase();
      if (method === "get" && form.getAttribute("data-loading-for-get") !== "true") {
        return;
      }
      showLoading(form);
      disableForm(form);
    });
  });

  window.addEventListener("pageshow", hideLoading);
})();
