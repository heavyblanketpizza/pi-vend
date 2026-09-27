// Chart hover layer: crosshair + multi-series tooltip on line charts, per-mark tooltips
// on bars/segments ([data-tip="title|value"]). Keyboard focus shows the same as hover.
(() => {
  let tip = document.querySelector(".viz-tip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "viz-tip";
    tip.setAttribute("role", "tooltip");
    tip.hidden = true;
    document.body.appendChild(tip);
  }
  const won = (v) => `${Math.round(v).toLocaleString("ko-KR")}원`;

  const place = (clientX, clientY) => {
    const pad = 14;
    const { width, height } = tip.getBoundingClientRect();
    let x = clientX + pad;
    let y = clientY - height - pad;
    if (x + width > window.innerWidth - 8) x = clientX - width - pad;
    if (y < 8) y = clientY + pad;
    tip.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  };

  const fill = (title, rows) => {
    tip.replaceChildren();
    const head = document.createElement("div");
    head.className = "tip-title";
    head.textContent = title;
    tip.appendChild(head);
    for (const row of rows) {
      const line = document.createElement("div");
      line.className = "tip-row";
      if (row.role) {
        const key = document.createElement("i");
        key.className = `key-line ${row.role === "compare" ? "compare" : "s1"}`;
        line.appendChild(key);
      }
      const value = document.createElement("b");
      value.textContent = row.value;
      line.appendChild(value);
      if (row.name) {
        const name = document.createElement("span");
        name.textContent = row.name;
        line.appendChild(name);
      }
      tip.appendChild(line);
    }
    tip.hidden = false;
  };
  const hide = () => { tip.hidden = true; };

  // Line charts: nearest X wins; the pointer never has to land on a line.
  document.querySelectorAll('[data-chart="line"]').forEach((figure) => {
    const svg = figure.querySelector("svg");
    const data = JSON.parse(figure.querySelector('script[type="application/json"]').textContent);
    const cross = svg.querySelector(".crosshair");
    let index = data.x.length - 1;

    const show = (i, clientX, clientY) => {
      index = Math.max(0, Math.min(data.x.length - 1, i));
      cross.setAttribute("x1", data.x[index]);
      cross.setAttribute("x2", data.x[index]);
      cross.removeAttribute("hidden");
      fill(data.labels[index], data.series.map((s) => ({ role: s.role, name: s.name, value: won(s.values[index]) })));
      if (clientX == null) {
        const box = svg.getBoundingClientRect();
        const ratio = box.width / svg.viewBox.baseVal.width;
        clientX = box.left + data.x[index] * ratio;
        clientY = box.top + box.height * 0.3;
      }
      place(clientX, clientY);
    };
    const nearest = (clientX) => {
      const point = new DOMPoint(clientX, 0).matrixTransform(svg.getScreenCTM().inverse());
      let best = 0;
      data.x.forEach((x, i) => { if (Math.abs(x - point.x) < Math.abs(data.x[best] - point.x)) best = i; });
      return best;
    };
    svg.addEventListener("pointermove", (e) => show(nearest(e.clientX), e.clientX, e.clientY));
    svg.addEventListener("pointerleave", () => { cross.setAttribute("hidden", ""); hide(); });
    svg.addEventListener("focus", () => show(index));
    svg.addEventListener("blur", () => { cross.setAttribute("hidden", ""); hide(); });
    svg.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        show(index + (e.key === "ArrowRight" ? 1 : -1));
      }
    });
  });

  // Bars, columns, segments.
  document.querySelectorAll("[data-tip]").forEach((mark) => {
    const [title, value] = mark.dataset.tip.split("|");
    const open = (e) => {
      fill(title, [{ value }]);
      if (e && e.clientX != null && e.type.startsWith("pointer")) place(e.clientX, e.clientY);
      else {
        const box = mark.getBoundingClientRect();
        place(box.left + box.width / 2, box.top);
      }
      mark.classList.add("active");
    };
    const close = () => { hide(); mark.classList.remove("active"); };
    mark.addEventListener("pointermove", open);
    mark.addEventListener("pointerleave", close);
    mark.addEventListener("focus", open);
    mark.addEventListener("blur", close);
  });
})();
