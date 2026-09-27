// API 연결: show the fields each AI provider needs.
(() => {
  const form = document.querySelector("[data-llm-form]");
  if (!form) return;
  const model = form.querySelector("#llm-model");
  const keyHelp = form.querySelector("[data-key-help]");
  const modelHelp = form.querySelector("[data-model-help]");
  const note = form.querySelector("[data-provider-note]");
  const keyOptional = form.querySelector("[data-key-optional]");
  const urlFields = form.querySelectorAll("[data-url-field]");
  const urlInput = form.querySelector("#llm-url");

  const setText = (node, text, link) => {
    node.textContent = text;
    if (link) {
      const a = document.createElement("a");
      a.href = link;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = " 키 발급 페이지 ↗";
      node.appendChild(a);
    }
  };

  const update = () => {
    const opt = form.querySelector("input[name=provider]:checked");
    if (!opt) return;
    const d = opt.dataset;
    const local = d.needsUrl === "1";
    urlFields.forEach((f) => { f.hidden = !local; });
    urlInput.required = local;
    keyOptional.hidden = d.needsKey === "1";
    setText(keyHelp, local ? "서버에 인증이 걸려 있을 때만 입력하세요." : "API 키는 해당 서비스 콘솔에서 만들 수 있어요.", d.keyUrl);
    note.textContent = d.note || "";
    note.hidden = !d.note;
    model.setAttribute("list", `models-${opt.value}`);
    model.placeholder = d.defaultModel || "비워두면 서버에 로드된 모델을 사용해요";
    modelHelp.textContent = d.defaultModel ? `비워두면 ${d.defaultModel}을(를) 사용해요.` : "llama-server는 로드한 모델 하나만 있어서 비워둬도 돼요.";
  };
  form.addEventListener("change", (e) => {
    if (e.target.name === "provider") {
      model.value = "";
      update();
    }
  });
  update();
})();
