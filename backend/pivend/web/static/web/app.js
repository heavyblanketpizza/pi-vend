// Shared behaviors: theme, mobile nav, two-step confirms, toasts, sortable tables, copy buttons.
(() => {
  const root = document.documentElement;
  const sprite = (window.PIVEND && window.PIVEND.sprite) || "";

  window.PIVEND = Object.assign(window.PIVEND || {}, {
    icon(name, cls = "") {
      return `<svg class="i ${cls}" aria-hidden="true"><use href="${sprite}#i-${name}"></use></svg>`;
    },
  });

  // Theme: system -> light -> dark
  const THEMES = [
    { id: "system", icon: "monitor", label: "시스템" },
    { id: "light", icon: "sun", label: "라이트" },
    { id: "dark", icon: "moon", label: "다크" },
  ];
  const readTheme = () => {
    try { return localStorage.getItem("pivend-theme") || "system"; } catch { return "system"; }
  };
  const applyTheme = (id) => {
    if (id === "system") delete root.dataset.theme; else root.dataset.theme = id;
    try { id === "system" ? localStorage.removeItem("pivend-theme") : localStorage.setItem("pivend-theme", id); } catch {}
    const theme = THEMES.find((t) => t.id === id);
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.innerHTML = window.PIVEND.icon(theme.icon);
      btn.title = `테마: ${theme.label}`;
    });
  };
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const index = THEMES.findIndex((t) => t.id === readTheme());
      applyTheme(THEMES[(index + 1) % THEMES.length].id);
    }),
  );
  applyTheme(readTheme());

  // Skin: neobrutalist (default) <-> base
  const SKINS = [{ id: "brutal", label: "네오브루탈" }, { id: "base", label: "기본" }];
  const readSkin = () => { try { return localStorage.getItem("pivend-skin") || "brutal"; } catch { return "brutal"; } };
  const applySkin = (id) => {
    root.dataset.skin = id;
    try { localStorage.setItem("pivend-skin", id); } catch {}
    document.querySelectorAll("[data-skin-toggle]").forEach((b) => { b.title = `스킨: ${SKINS.find((s) => s.id === id).label}`; });
  };
  document.querySelectorAll("[data-skin-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const index = SKINS.findIndex((s) => s.id === readSkin());
      applySkin(SKINS[(index + 1) % SKINS.length].id);
    }),
  );
  applySkin(readSkin());

  // Agent drawer: available on every page; [data-copilot="prompt"] opens it with a prefilled prompt.
  const copilot = document.getElementById("copilot");
  if (copilot) {
    const frame = copilot.querySelector("iframe");
    const full = copilot.querySelector("[data-copilot-full]");
    const open = (prompt) => {
      const url = new URL(frame.dataset.src, window.location.origin);
      if (prompt) url.searchParams.set("prompt", prompt);
      if (prompt || !frame.src) frame.src = url.pathname + url.search;
      copilot.hidden = false;
      document.body.classList.add("copilot-open");
      requestAnimationFrame(() => copilot.classList.add("open"));
    };
    const close = () => {
      copilot.classList.remove("open");
      document.body.classList.remove("copilot-open");
      setTimeout(() => { copilot.hidden = true; }, 220);
    };
    document.addEventListener("click", (e) => {
      const trigger = e.target.closest("[data-copilot]");
      if (trigger) { e.preventDefault(); open(trigger.dataset.copilot || ""); }
      if (e.target.closest("[data-copilot-close]")) close();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !copilot.hidden) close(); });
    // "Open full screen" follows the conversation the drawer is showing.
    full.addEventListener("click", () => {
      try {
        const path = frame.contentWindow.location.pathname;
        if (path.startsWith("/chat/")) full.href = path;
      } catch {}
    });
  }

  // Mobile navigation drawer
  document.querySelectorAll("[data-nav-open]").forEach((b) => b.addEventListener("click", () => document.body.classList.add("nav-open")));
  document.querySelectorAll("[data-nav-close]").forEach((b) => b.addEventListener("click", () => document.body.classList.remove("nav-open")));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") document.body.classList.remove("nav-open"); });

  // Two-step destructive buttons: first click arms, second click submits.
  document.querySelectorAll("[data-confirm]").forEach((btn) => {
    let timer;
    const original = btn.innerHTML;
    const reset = () => { delete btn.dataset.confirming; btn.innerHTML = original; };
    btn.addEventListener("click", (e) => {
      if (btn.dataset.confirming) return;
      e.preventDefault();
      btn.dataset.confirming = "true";
      btn.textContent = btn.dataset.confirm;
      clearTimeout(timer);
      timer = setTimeout(reset, 2500);
    });
    btn.addEventListener("blur", () => setTimeout(reset, 150));
  });

  // Toasts
  const dismiss = (toast) => { toast.classList.add("leaving"); setTimeout(() => toast.remove(), 220); };
  document.querySelectorAll(".toast").forEach((toast, i) => setTimeout(() => dismiss(toast), 4200 + i * 300));
  window.PIVEND.toast = (text, kind = "success") => {
    const toast = document.createElement("div");
    toast.className = `toast ${kind}`;
    toast.innerHTML = window.PIVEND.icon(kind === "error" ? "circle-alert" : "circle-check");
    const span = document.createElement("span");
    span.textContent = text;
    toast.appendChild(span);
    document.querySelector(".toasts").appendChild(toast);
    setTimeout(() => dismiss(toast), 3000);
  };

  // Sortable tables: <th data-sort="num|text">, cells may carry data-value.
  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = [...table.querySelectorAll("th")];
    headers.forEach((th, col) => {
      if (!th.dataset.sort) return;
      th.tabIndex = 0;
      const sort = () => {
        const dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
        headers.forEach((h) => h.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", dir);
        const body = table.tBodies[0];
        const value = (row) => {
          const cell = row.cells[col];
          const raw = cell.dataset.value ?? cell.textContent.trim();
          return th.dataset.sort === "num" ? Number(raw) || 0 : raw;
        };
        const rows = [...body.rows].sort((a, b) => {
          const [x, y] = [value(a), value(b)];
          const cmp = typeof x === "number" ? x - y : String(x).localeCompare(String(y), "ko");
          return dir === "ascending" ? cmp : -cmp;
        });
        rows.forEach((r) => body.appendChild(r));
      };
      th.addEventListener("click", sort);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter") sort(); });
    });
  });

  // Copy buttons: data-copy="text"
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      window.PIVEND.toast("복사했어요");
    } catch {
      window.PIVEND.toast("복사하지 못했어요", "error");
    }
  });

  // "/" focuses the main input on the page.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    const target = document.querySelector("[data-hotkey-focus]");
    if (target) { e.preventDefault(); target.focus(); }
  });
})();
