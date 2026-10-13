// Conversations view: the messages as delivered, and under each one what was derived from it with
// links to the review queue and the topic map. Read-only; all text is inserted as text.
(function () {
  "use strict";
  const R = window.AMReview;
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = { list: [], total: 0, next: null, more: false, current: null, detail: null, highlight: null };

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "class") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (value !== null && value !== undefined && value !== false) node.setAttribute(key, value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  const same = (a, b) => a && b && a.source_system === b.source_system && a.conversation_id === b.conversation_id;

  async function loadList(append) {
    const query = new URLSearchParams({ limit: "25" });
    if (append && state.next) query.set("cursor", state.next);
    const page = await S.call("GET", "/v1/conversations?" + query);
    state.list = append ? state.list.concat(page.conversations) : page.conversations;
    state.total = page.total; state.next = page.next_cursor; state.more = page.has_more;
  }

  async function openConversation(source_system, conversation_id, highlight) {
    state.current = { source_system, conversation_id };
    state.highlight = highlight || null;
    state.detail = await S.call("GET", "/v1/conversations/" + encodeURIComponent(source_system) + "/" + encodeURIComponent(conversation_id));
    render();
    if (highlight) {
      const target = document.querySelector('[data-episode="' + CSS.escape(highlight) + '"]');
      if (target && target.scrollIntoView) target.scrollIntoView({ block: "center" });
    }
  }

  function counts(derived) {
    const parts = [];
    if (derived.candidate) parts.push(derived.candidate + " čeká na rozhodnutí");
    if (derived.confirmed) parts.push(derived.confirmed + " potvrzeno");
    if (derived.rejected) parts.push(derived.rejected + " zamítnuto");
    return parts.length ? parts.join(" · ") : "nic z ní nevzniklo";
  }

  function derivedChip(item) {
    return el("li", { class: "chip " + item.status },
      el("span", { class: "kindline" }, R.KIND[item.candidate_kind] || item.candidate_kind, " "),
      el("span", { class: "badge " + item.status }, R.STATUS[item.status] || item.status),
      el("div", { class: "title" }, item.title),
      el("div", { class: "more-links" },
        el("button", { type: "button", class: "link", onclick: () => S.show("review", { focus: { kind: item.subject.kind, id: item.subject.identifier } }) }, "Ve frontě ke schválení"),
        item.subject.kind === "node" ? [" · ", el("button", { type: "button", class: "link", onclick: () => S.show("map", { tab: "themes", focusNode: item.subject.identifier }) }, "Na mapě témat")] : null));
  }

  function bubble(message) {
    const quotes = message.derived.flatMap((d) => d.quotes);
    return el("li", { class: "msg " + message.role + (message.episode_id === state.highlight ? " highlight" : ""), "data-episode": message.episode_id },
      el("div", { class: "meta" }, (R.ROLE[message.role] || message.role) + " · " + R.when(message.occurred_at)),
      el("p", { class: "source-text" }, R.markQuotes(message.content, quotes).map((s) => (s.mark ? el("mark", {}, s.text) : s.text))),
      message.derived.length
        ? el("div", { class: "derived" }, el("div", { class: "meta" }, "Z této zprávy vzniklo:"), el("ul", { class: "chips" }, message.derived.map(derivedChip)))
        : el("div", { class: "meta" }, message.role === "user" ? "Z této zprávy nevzniklo nic." : "Odpověď asistenta se nezpracovává do paměti."));
  }

  function render() {
    const list = $("conv-list");
    list.replaceChildren();
    if (!S.connected) {
      $("conv-info").textContent = "Připojte se tokenem – bez něj se nic nezobrazí.";
      $("conv-detail").replaceChildren(); $("conv-more").hidden = true;
      return;
    }
    $("conv-info").textContent = "Konverzací: " + state.total + ". Nejnovější nahoře.";
    if (!state.list.length) list.append(el("li", { class: "empty" }, "Zatím žádné konverzace."));
    for (const c of state.list) {
      list.append(el("li", { class: "card conv-card" + (same(c, state.current) ? " selected" : ""), tabindex: "0", role: "button",
        onclick: () => openConversation(c.source_system, c.conversation_id).catch((e) => S.say(e.message, true)),
        onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.currentTarget.click(); } } },
        el("h3", { class: "title" }, c.conversation_id),
        el("div", { class: "meta" }, c.source_system + " · zpráv: " + c.messages + " · " + R.when(c.first_at) + (c.messages > 1 ? " – " + R.when(c.last_at) : "")),
        el("div", { class: "meta" }, counts(c.derived))));
    }
    $("conv-more").hidden = !state.more;
    const detail = $("conv-detail");
    if (!state.detail) { detail.replaceChildren(el("p", { class: "empty" }, "Vyberte konverzaci vlevo.")); return; }
    detail.replaceChildren(
      el("h3", {}, "Konverzace „" + state.detail.conversation_id + "“"),
      el("div", { class: "meta" }, state.detail.source_system + " · zpráv: " + state.detail.messages.length),
      el("ol", { class: "messages" }, state.detail.messages.map(bubble)));
  }

  S.register("conversations", {
    async load() { await loadList(false); },
    async show(params) {
      if (params && params.conversation_id) await openConversation(params.source_system, params.conversation_id, params.highlight);
      else render();
    },
    clear() {
      state.list = []; state.total = 0; state.next = null; state.more = false;
      state.current = null; state.detail = null; state.highlight = null; render();
    },
  });
  $("conv-more").addEventListener("click", () => loadList(true).then(render).catch((e) => S.say(e.message, true)));
})();
