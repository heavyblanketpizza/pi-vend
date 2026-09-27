// Chat client: one renderer for saved history and live SSE events.
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const chat = $("#chat");
  if (!chat) return;

  const icon = (name, cls) => window.PIVEND.icon(name, cls);
  const thread = $("#thread");
  const scroller = $("#scroller");
  const welcome = $("#welcome");
  const form = $("#composer");
  const input = $("#input");
  const sendButton = $("#send");
  const jump = $("#jump");
  const titleEl = $("#chat-title");
  const csrf = chat.dataset.csrf;
  let sendUrl = chat.dataset.sendUrl;
  let busy = false;

  // ------------------------------------------------------------- tool labels
  const few = (items) => {
    const list = (items || []).filter(Boolean);
    return list.length > 2 ? `${list.slice(0, 2).join(", ")} 외 ${list.length - 2}개` : list.join(", ");
  };
  const TOOLS = {
    keyword_stats: { label: "검색량 조회", detail: (a) => few(a.keywords) },
    related_keywords: { label: "연관 키워드 탐색", detail: (a) => a.seed },
    keyword_trend: { label: "검색 트렌드 분석", detail: (a) => few(a.keywords) },
    analyze_competitors: { label: "경쟁 상품 분석", detail: (a) => a.query },
    check_title: { label: "상품명 점검", detail: (a) => a.title },
    list_drafts: { label: "초안 목록 확인" },
    get_draft: { label: "초안 불러오기", detail: (a) => (a.draft_id ? `#${a.draft_id}` : "") },
    save_draft: { label: "초안 저장", detail: (a) => a.title || a.product_name },
    render_detail_page: {
      label: "상세페이지 렌더링",
      detail: (a) => (a.detail_page?.sections?.length ? `섹션 ${a.detail_page.sections.length}개` : ""),
    },
  };
  const describe = (name, args) => {
    const tool = TOOLS[name] || { label: name };
    let detail = "";
    try { detail = tool.detail ? tool.detail(args || {}) || "" : ""; } catch { detail = ""; }
    return { label: tool.label, detail };
  };
  // Sub-100ms steps (cache hits) show no duration rather than "0.0초".
  const seconds = (ms) => (ms == null || ms < 100 ? "" : ms < 10_000 ? `${(ms / 1000).toFixed(1)}초` : `${Math.round(ms / 1000)}초`);

  // --------------------------------------------------------------- markdown
  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const md = (text) => {
    if (window.marked && window.DOMPurify) {
      return window.DOMPurify.sanitize(window.marked.parse(text, { breaks: true, gfm: true }));
    }
    return escapeHtml(text).replace(/\n/g, "<br>");
  };

  // --------------------------------------------------------------- scrolling
  let stick = true;
  const atBottom = () => scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  const toBottom = (force = false) => {
    if (force || stick) scroller.scrollTo({ top: scroller.scrollHeight, behavior: "instant" });
  };
  scroller.addEventListener("scroll", () => {
    stick = atBottom();
    jump.classList.toggle("show", !stick && !thread.hidden);
  });
  jump.addEventListener("click", () => {
    scroller.scrollTo({ top: scroller.scrollHeight, behavior: "smooth" });
  });

  const el = (tag, cls, html) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html != null) node.innerHTML = html;
    return node;
  };

  // --------------------------------------------------------- activity group
  class Activity {
    constructor(parent) {
      this.steps = new Map();
      this.root = el("div", "activity");
      this.root.dataset.open = "true";
      this.head = el("button", "activity-head");
      this.head.type = "button";
      this.head.innerHTML = `<span class="head-state"></span><span class="head-text"></span><span class="subtle head-dur tnum"></span>${icon("chevron-down", "chev")}`;
      this.head.addEventListener("click", () => {
        this.root.dataset.open = this.root.dataset.open === "true" ? "false" : "true";
      });
      this.list = el("div", "activity-steps");
      this.root.append(this.head, this.list);
      parent.appendChild(this.root);
      this.refresh();
    }

    add(id, name, args, live) {
      const { label, detail } = describe(name, args);
      const step = el("div", `step ${live ? "running" : "done"}`);
      step.innerHTML = `<span class="state"></span><div><span class="label"></span><span class="detail"></span></div><span class="dur"></span><div class="summary"></div>`;
      step.querySelector(".label").textContent = label;
      step.querySelector(".detail").textContent = detail;
      this.list.appendChild(step);
      this.steps.set(id, { el: step, started: performance.now(), state: live ? "running" : "done", ms: null });
      this.paint(id);
      this.refresh();
    }

    finish(id, isError, summary, live) {
      const step = this.steps.get(id);
      if (!step) return;
      step.state = isError ? "failed" : "done";
      step.ms = live ? performance.now() - step.started : null;
      step.el.className = `step ${step.state}`;
      if (isError && summary) step.el.querySelector(".summary").textContent = summary;
      this.paint(id);
      this.refresh();
    }

    paint(id) {
      const step = this.steps.get(id);
      const state = step.el.querySelector(".state");
      state.innerHTML =
        step.state === "running" ? icon("loader-circle", "spin") : step.state === "failed" ? icon("circle-x") : icon("circle-check");
      step.el.querySelector(".dur").textContent = seconds(step.ms);
    }

    get running() { return [...this.steps.values()].filter((s) => s.state === "running").length; }
    get failed() { return [...this.steps.values()].filter((s) => s.state === "failed").length; }

    refresh() {
      const total = this.steps.size;
      const running = this.running;
      const failed = this.failed;
      const state = this.head.querySelector(".head-state");
      const text = this.head.querySelector(".head-text");
      const dur = this.head.querySelector(".head-dur");
      if (running) {
        state.className = "head-state running";
        state.innerHTML = icon("loader-circle", "spin");
        text.textContent = `작업 중 · ${total - running}/${total}`;
      } else if (failed) {
        state.className = "head-state failed";
        state.innerHTML = icon("circle-alert");
        text.textContent = `작업 ${total}개 중 ${failed}개 실패`;
      } else {
        state.className = "head-state done";
        state.innerHTML = icon("circle-check");
        text.textContent = `작업 ${total}개 완료`;
      }
      const ms = [...this.steps.values()].reduce((sum, s) => sum + (s.ms || 0), 0);
      dur.textContent = !running && ms ? seconds(ms) : "";
    }

    collapse() {
      if (!this.failed) this.root.dataset.open = "false";
    }
  }

  // -------------------------------------------------------------- turns
  const markTemplate = $("#tpl-mark");
  const turns = [];

  class Turn {
    constructor() {
      this.root = el("div", "msg-assistant");
      this.root.appendChild(markTemplate.content.firstElementChild.cloneNode(true));
      this.content = el("div", "content");
      this.root.appendChild(this.content);
      thread.appendChild(this.root);
      this.texts = [];
      this.prose = null;
      this.pending = "";
      this.frame = 0;
      this.activity = null;
      this.activities = [];
      this.thinkingEl = null;
      turns.push(this);
    }

    thinking(on, label = "생각하는 중") {
      if (on && !this.thinkingEl) {
        this.thinkingEl = el("div", "thinking", `<span class="shimmer">${label}…</span>`);
        this.content.appendChild(this.thinkingEl);
        toBottom();
      } else if (!on && this.thinkingEl) {
        this.thinkingEl.remove();
        this.thinkingEl = null;
      }
    }

    text(delta, streaming) {
      this.thinking(false);
      if (!this.prose) {
        this.prose = el("div", "prose");
        this.content.appendChild(this.prose);
        this.texts.push("");
        this.activity = null;
      }
      this.texts[this.texts.length - 1] += delta;
      this.prose.classList.toggle("caret", streaming);
      if (!streaming) {
        this.prose.innerHTML = md(this.texts[this.texts.length - 1]);
        return;
      }
      // Re-render markdown at most once per frame while streaming.
      if (!this.frame) {
        this.frame = requestAnimationFrame(() => {
          this.frame = 0;
          if (this.prose) this.prose.innerHTML = md(this.texts[this.texts.length - 1]);
          toBottom();
        });
      }
    }

    endText() {
      if (this.frame) {
        cancelAnimationFrame(this.frame);
        this.frame = 0;
        if (this.prose) this.prose.innerHTML = md(this.texts[this.texts.length - 1]);
      }
      this.prose?.classList.remove("caret");
      this.prose = null;
    }

    toolStart(id, name, args, live) {
      this.thinking(false);
      this.endText();
      if (!this.activity) {
        this.activity = new Activity(this.content);
        this.activities.push(this.activity);
      }
      this.activity.add(id, name, args, live);
      toBottom();
    }

    toolEnd(id, isError, summary, images, draftUrl, live) {
      const activity = this.activities.find((a) => a.steps.has(id));
      activity?.finish(id, isError, summary, live);
      if (images?.length) {
        this.renderCard(images, draftUrl);
        this.activity = null;
      }
      if (live && activity && !activity.running) this.thinking(true, "결과를 정리하는 중");
      toBottom();
    }

    renderCard(images, draftUrl) {
      const card = el("a", "render-card");
      card.href = draftUrl || images[0];
      card.innerHTML = `
        <div class="shot"><img alt="" loading="lazy"></div>
        <div class="body">
          <span class="kicker">${icon("image", "i-sm")}상세페이지</span>
          <span class="t">렌더링 완료</span>
          <span class="s tnum"></span>
          <span class="go">초안에서 보기 ${icon("arrow-right", "i-sm")}</span>
        </div>`;
      card.querySelector("img").src = images[0];
      card.querySelector(".s").textContent = `860px · 이미지 ${images.length}장`;
      this.content.appendChild(card);
    }

    error(text) {
      this.thinking(false);
      this.endText();
      const box = el("div", "msg-error", icon("circle-alert"));
      const span = document.createElement("span");
      span.textContent = text;
      box.appendChild(span);
      this.content.appendChild(box);
      this.activity = null;
      toBottom();
    }

    finish() {
      this.thinking(false);
      this.endText();
      this.activities.forEach((a) => {
        // Steps that never reported back (connection dropped) are shown as failed.
        a.steps.forEach((step, id) => { if (step.state === "running") a.finish(id, true, "응답이 중단됐어요", true); });
        a.collapse();
      });
      const text = this.texts.join("\n\n").trim();
      if (text && !this.content.querySelector(".msg-actions")) {
        const actions = el("div", "msg-actions");
        const copy = el("button", "btn-icon sm", icon("copy", "i-sm"));
        copy.type = "button";
        copy.title = "복사";
        copy.setAttribute("aria-label", "답변 복사");
        copy.dataset.copy = text;
        actions.appendChild(copy);
        this.content.appendChild(actions);
      }
    }
  }

  const addUser = (text) => {
    const bubble = el("div", "msg-user");
    bubble.textContent = text;
    thread.appendChild(bubble);
  };

  // ---------------------------------------------------------------- history
  const history = JSON.parse($("#history")?.textContent || "[]");
  let turn = null;
  let fakeId = 0;
  for (const item of history) {
    if (item.role === "user") {
      turn?.finish();
      turn = null;
      addUser(item.text);
      continue;
    }
    turn ??= new Turn();
    if (item.role === "assistant") {
      turn.text(item.text, false);
      turn.endText();
    } else if (item.role === "tools") {
      for (const step of item.steps) {
        const id = `h${fakeId++}`;
        turn.toolStart(id, step.name, step.args, false);
        turn.toolEnd(id, step.isError, step.summary, step.images, step.draftUrl, false);
      }
    } else if (item.role === "error") {
      turn.error(item.text);
    }
  }
  turn?.finish();
  requestAnimationFrame(() => toBottom(true));

  // --------------------------------------------------------------- composer
  const autosize = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 240)}px`;
  };
  const updateSend = () => {
    sendButton.disabled = busy || input.disabled || !input.value.trim();
    sendButton.innerHTML = busy ? icon("loader-circle", "i-lg spin") : icon("arrow-up", "i-lg");
  };
  input.addEventListener("input", () => { autosize(); updateSend(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submit(input.value);
  });

  document.querySelectorAll(".suggestion").forEach((button) =>
    button.addEventListener("click", () => {
      if (button.dataset.mode === "send") return submit(button.dataset.prompt);
      input.value = button.dataset.prompt;
      autosize();
      updateSend();
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }),
  );

  const addToSidebar = (url, title) => {
    const list = document.querySelector(".convos");
    if (!list) return;
    list.querySelector(".side-empty")?.remove();
    document.querySelectorAll(".convo[aria-current]").forEach((c) => c.removeAttribute("aria-current"));
    let group = list.querySelector(".convo-group");
    if (!group || group.querySelector(".side-label")?.textContent !== "오늘") {
      group = el("div", "convo-group", `<div class="side-label">오늘</div>`);
      list.prepend(group);
    }
    const item = el("div", "convo");
    item.setAttribute("aria-current", "page");
    const link = el("a");
    link.href = url;
    link.textContent = title;
    item.appendChild(link);
    group.querySelector(".side-label").after(item);
  };

  async function ensureConversation(text) {
    if (sendUrl) return true;
    const response = await fetch(chat.dataset.newUrl, { method: "POST", headers: { "X-CSRFToken": csrf } });
    if (!response.ok) return false;
    const created = await response.json();
    sendUrl = created.send_url;
    window.history.replaceState(null, "", created.url);
    addToSidebar(created.url, text.replace(/\s+/g, " ").slice(0, 60));
    return true;
  }

  async function submit(raw) {
    const text = raw.trim();
    if (busy || !text || input.disabled) return;
    busy = true;
    updateSend();

    welcome.hidden = true;
    thread.hidden = false;
    addUser(text);
    input.value = "";
    autosize();
    if (titleEl.textContent === "새 대화") {
      titleEl.textContent = text.replace(/\s+/g, " ").slice(0, 60);
      document.title = `${titleEl.textContent} · 에이전트 · Pi-Vend`;
    }
    const current = new Turn();
    current.thinking(true);
    toBottom(true);

    try {
      if (!(await ensureConversation(text))) throw new Error("대화를 만들지 못했어요");
      const response = await fetch(sendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ message: text }),
      });
      if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let index;
        while ((index = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            let event;
            try { event = JSON.parse(line.slice(6)); } catch { continue; }
            handle(current, event);
          }
        }
      }
    } catch (error) {
      current.error(error instanceof Error ? error.message : String(error));
    } finally {
      current.finish();
      busy = false;
      updateSend();
      input.focus();
    }
  }

  function handle(current, event) {
    switch (event.type) {
      case "assistant_start":
        current.endText();
        break;
      case "text_delta":
        current.text(event.delta, true);
        break;
      case "tool_start":
        current.toolStart(event.id, event.name, event.args, true);
        break;
      case "tool_end":
        current.toolEnd(event.id, event.isError, event.summary, event.images, event.draftUrl, true);
        break;
      case "assistant_end":
        current.endText();
        if (event.errorMessage) current.error(event.errorMessage);
        break;
      case "error":
        current.error(event.message);
        break;
    }
  }

  // Prefilled prompt (e.g. from the research page): focus it and clean the URL.
  if (input.value) {
    const url = new URL(window.location.href);
    url.searchParams.delete("prompt");
    window.history.replaceState(null, "", url);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
  autosize();
  updateSend();
})();
