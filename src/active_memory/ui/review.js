// Review queue view. A client of the public REST API only: reads /v1/candidates, decides through
// /v1/nodes|links/{id}/review. All server data is inserted as text. The token lives in the shell.
(function () {
  "use strict";
  const R = window.AMReview;
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = {
    filter: { kind: "all", status: "candidate" },
    items: [], total: 0, nextCursor: null, hasMore: false,
    busy: new Set(), expanded: new Set(), focus: null,
  };

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
  const call = (...args) => S.call(...args);
  const say = (text, kind) => S.say(text, kind === "error");
  const idOf = (item) => item.subject.kind + ":" + item.subject.identifier;

  function queueQuery(cursor) {
    const p = new URLSearchParams({ kind: state.filter.kind, status: state.filter.status, limit: "25" });
    if (cursor) p.set("cursor", cursor);
    return "/v1/candidates?" + p;
  }

  async function load(params, append) {
    const focus = params && params.focus;
    if (focus) {
      state.focus = await call("GET", "/v1/candidates/" + focus.kind + "/" + focus.id);
      return;
    }
    state.focus = null;
    const page = await call("GET", queueQuery(append ? state.nextCursor : null));
    state.items = append ? state.items.concat(page.items) : page.items;
    state.total = page.total; state.hasMore = page.has_more; state.nextCursor = page.next_cursor;
  }

  async function refresh() {
    const focus = state.focus ? { kind: state.focus.subject.kind, id: state.focus.subject.identifier } : null;
    await load(focus ? { focus } : {});
    render();
    S.refreshCount();
  }

  // -- rendering -------------------------------------------------------------------------
  function badge(status) { return el("span", { class: "badge " + status }, R.STATUS[status] || status); }

  function evidenceBlock(e) {
    const url = R.safeUrl(e.url);
    return el("blockquote", { class: "quote" },
      el("q", {}, e.quote),
      el("footer", { class: "meta" },
        (R.ROLE[e.role] || e.role || "role neznámá") + " · " + R.when(e.occurred_at) + " · konverzace „" + e.conversation_id + "“ ",
        el("button", { type: "button", class: "link", onclick: () => S.show("conversations", { source_system: e.source_system, conversation_id: e.conversation_id, highlight: e.episode_id }) }, "otevřít celou konverzaci"),
        " · ",
        el("button", { type: "button", class: "link", onclick: () => openSource(e) }, "zobrazit zprávu"),
        url ? [" · ", el("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, "externí odkaz")] : null));
  }

  function technical(item) {
    const e = item.evidence[0];
    return el("details", { class: "tech" },
      el("summary", {}, "Technické údaje"),
      el("div", {}, "Identifikátor návrhu: " + item.subject.identifier + " (" + item.subject.kind + ")"),
      item.evidence.map((x) => el("div", {}, "Zdroj: zpráva " + x.message_id + ", konverzace " + x.conversation_id + " (" + x.source_system + "), epizoda " + x.episode_id)),
      e ? null : el("div", {}, "Žádná živá evidence."),
      item.audit ? el("div", {}, "Audit: událostí " + item.audit.events + ", poslední zaznamenaný stav " + (item.audit.last_recorded_state || "žádný")) : null);
  }

  function itemCard(item) {
    const id = idOf(item);
    const decision = R.decisionState(item, S.canDecide);
    const busy = state.busy.has(id);
    const open = state.expanded.has(id);
    const shown = open ? item.evidence : item.evidence.slice(0, 1);
    const buttons = el("div", { class: "actions" },
      el("button", { type: "button", class: "ok", disabled: !decision.allowed || busy, onclick: () => decide(item, "confirmed") }, busy ? "Probíhá…" : "Potvrdit"),
      el("button", { type: "button", class: "no", disabled: !decision.allowed || busy, onclick: () => decide(item, "rejected") }, busy ? "Probíhá…" : "Zamítnout"));
    const inMap = item.subject.kind === "node"
      ? el("button", { type: "button", class: "link", onclick: () => S.show("map", { tab: "themes", focusNode: item.subject.identifier }) }, "Ukázat na mapě témat")
      : null;
    return el("li", { class: "card item " + item.status + (busy ? " busy" : ""), "data-id": id },
      el("div", { class: "kindline" }, R.KIND[item.candidate_kind] || item.candidate_kind, " ", badge(item.status)),
      el("h3", { class: "title" }, R.title(item)),
      item.summary ? el("p", { class: "summary-text" }, item.summary) : null,
      item.proposal ? el("p", { class: "meta" }, "Skóre " + item.proposal.score + ": " + item.proposal.reason) : null,
      el("div", { class: "evidence" }, shown.length ? shown.map(evidenceBlock) : el("p", { class: "meta" }, "Žádná živá evidence.")),
      item.evidence.length > 1
        ? el("button", { type: "button", class: "link evidence-extra", onclick: () => { open ? state.expanded.delete(id) : state.expanded.add(id); render(); } },
            open ? "Skrýt ostatní citace" : "Zobrazit všech " + item.evidence.length + " citací")
        : null,
      el("div", { class: "origin" }, item.contributions.length
        ? item.contributions.map((c) => el("div", {}, "Původ: " + R.originText(c)))
        : el("div", {}, "Původ není v auditu doložen.")),
      !item.audit.consistent && item.status === "candidate" ? el("div", { class: "warn" }, "Audit nesouhlasí s aktuálním stavem.") : null,
      item.decision ? el("p", { class: "meta" }, "Rozhodl " + item.decision.actor.identifier + " (ověřeno tokenem) · " + R.when(item.decision.recorded_at)) : null,
      buttons,
      decision.allowed ? null : el("div", { class: "why" }, decision.reason),
      inMap ? el("div", { class: "more-links" }, inMap) : null,
      technical(item));
  }

  function render() {
    const list = $("queue");
    list.replaceChildren();
    const bar = $("focus-bar");
    if (!S.connected) {
      $("queue-info").textContent = "Připojte se tokenem – bez něj se nic nezobrazí.";
      $("more").hidden = true; bar.hidden = true; $("source-pane").replaceChildren();
      return;
    }
    if (state.focus) {
      bar.hidden = false; bar.replaceChildren(
        "Zobrazen jeden návrh (otevřeno z jiného pohledu). ",
        el("button", { type: "button", class: "link", onclick: () => { state.focus = null; refresh().catch((e) => say(e.message, "error")); } }, "Zpět na celou frontu"));
      $("queue-info").textContent = "";
      list.append(itemCard(state.focus));
      $("more").hidden = true;
      return;
    }
    bar.hidden = true;
    $("queue-info").textContent = "Zobrazeno " + state.items.length + " z " + state.total + ".";
    if (!state.items.length) list.append(el("li", { class: "empty" }, "Žádní kandidáti v tomto filtru."));
    for (const item of state.items) list.append(itemCard(item));
    $("more").hidden = !state.hasMore;
  }

  async function openSource(evidence) {
    const pane = $("source-pane");
    try {
      const data = await call("GET", "/v1/episodes/" + evidence.episode_id);
      pane.replaceChildren(
        el("h3", {}, "Původní zpráva"),
        el("div", { class: "meta" }, (R.ROLE[data.role] || data.role) + " · " + R.when(data.occurred_at) + " · konverzace „" + data.conversation_id + "“"),
        el("p", { class: "source-text" }, R.markQuotes(data.content, [evidence.quote]).map((s) => (s.mark ? el("mark", {}, s.text) : s.text))),
        el("button", { type: "button", class: "link", onclick: () => pane.replaceChildren() }, "zavřít"));
    } catch (error) {
      say("Zdroj nelze zobrazit: " + (error.status === 404 ? "byl smazán." : error.message), "error");
    }
  }

  // -- decisions ---------------------------------------------------------------------------
  async function decide(item, wanted) {
    const id = idOf(item);
    if (state.busy.has(id)) return;
    state.busy.add(id); render(); say("");
    const path = (item.subject.kind === "node" ? "/v1/nodes/" : "/v1/links/") + item.subject.identifier + "/review";
    try {
      await call("POST", path, { status: wanted, expected_status: item.status });
      const fresh = await call("GET", "/v1/candidates/" + item.subject.kind + "/" + item.subject.identifier);
      const problem = R.verifyDecision(fresh, wanted);
      say(problem || (wanted === "confirmed" ? "Potvrzeno a ověřeno v auditu." : "Zamítnuto a ověřeno v auditu."), problem ? "error" : "");
    } catch (error) {
      if (error.status === 409) say("Stav se mezitím změnil jinde (" + error.message + "). Data jsou obnovena; rozhodněte znovu, pokud je to potřeba.", "error");
      else if (error.status === 403) say("Rozhodnutí odmítnuto: token nemá oprávnění admin.", "error");
      else if (error.status === 404) say("Kandidát už neexistuje (zdroj mohl být smazán).", "error");
      else if (error.status !== 401) say("Rozhodnutí se nepodařilo potvrdit: " + error.message + " Data jsou obnovena; ověřte stav.", "error");
    } finally {
      state.busy.delete(id);
      if (S.connected) { try { await refresh(); } catch (error) { say("Obnovení selhalo: " + error.message, "error"); } }
    }
  }

  S.register("review", {
    async load(params) { await load(params); },
    async show(params) {
      if (params && params.focus) { await load(params); }
      else if (state.focus && !(params && params.focus)) { state.focus = null; await load({}); }
      render();
    },
    clear() {
      state.items = []; state.total = 0; state.hasMore = false; state.focus = null;
      state.expanded.clear(); state.busy.clear(); render();
    },
  });

  $("reload").addEventListener("click", () => { state.focus = null; refresh().catch((e) => say(e.message, "error")); });
  $("f-kind").addEventListener("change", (e) => { state.filter.kind = e.target.value; state.focus = null; refresh().catch((x) => say(x.message, "error")); });
  $("f-status").addEventListener("change", (e) => { state.filter.status = e.target.value; state.focus = null; refresh().catch((x) => say(x.message, "error")); });
  $("more").addEventListener("click", () => load({}, true).then(render).catch((e) => say(e.message, "error")));
})();
