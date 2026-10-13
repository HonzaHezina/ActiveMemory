// Review queue + event timeline. A client of the public REST API only: reads /v1/candidates and
// /v1/events, decides through /v1/nodes|links/{id}/review. All server data is inserted as text.
// The bearer token lives in this page's memory; "Odpojit" or closing the tab discards it.
(function () {
  "use strict";
  const R = window.AMReview;
  const state = {
    token: null, canDecide: false, clientId: null,
    filter: { kind: "node", status: "candidate" },
    items: [], total: 0, nextCursor: null, hasMore: false,
    busy: new Set(), expanded: new Set(),
    timeline: [], olderCursor: null, olderMore: false,
  };
  const $ = (id) => document.getElementById(id);

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

  function say(text, kind) {
    const box = $("message");
    box.textContent = text || "";
    box.className = "message" + (kind === "error" ? " error" : "");
  }

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  async function call(method, path, body) {
    if (!state.token) throw new ApiError(0, "Nejste připojeni.");
    const response = await fetch(path, {
      method, cache: "no-store",
      headers: Object.assign({ Authorization: "Bearer " + state.token }, body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (response.status === 401) { disconnect(); throw new ApiError(401, "Token není platný nebo byl odvolán. Připojte se znovu."); }
    if (response.status === 403) throw new ApiError(403, "Token nemá potřebné oprávnění.");
    if (response.status === 409) {
      const detail = await response.json().catch(() => ({}));
      throw new ApiError(409, detail.detail || "Stav se mezitím změnil.");
    }
    if (response.status === 503) {
      const detail = await response.json().catch(() => ({}));
      throw new ApiError(503, detail.detail || "Služba je dočasně nedostupná.");
    }
    if (!response.ok) throw new ApiError(response.status, "Požadavek selhal (" + response.status + ").");
    return response.json();
  }

  function disconnect() {
    state.token = null; state.canDecide = false; state.items = []; state.timeline = [];
    state.hasMore = false; state.olderMore = false; state.expanded.clear(); state.busy.clear();
    $("who").textContent = ""; $("disconnect").hidden = true;
    render();
  }

  function queueQuery(cursor) {
    const p = new URLSearchParams({ kind: state.filter.kind, status: state.filter.status, limit: "25" });
    if (cursor) p.set("cursor", cursor);
    return "/v1/candidates?" + p;
  }

  async function loadQueue(append) {
    const page = await call("GET", queueQuery(append ? state.nextCursor : null));
    state.items = append ? state.items.concat(page.items) : page.items;
    state.total = page.total; state.hasMore = page.has_more; state.nextCursor = page.next_cursor;
  }

  async function loadTimeline(older) {
    const p = new URLSearchParams({ order: "desc", limit: "30", expand: "subject" });
    if (older && state.olderCursor) p.set("cursor", state.olderCursor);
    const page = await call("GET", "/v1/events?" + p);
    state.timeline = older ? state.timeline.concat(page.events) : page.events;
    state.olderCursor = page.next_cursor; state.olderMore = page.has_more;
  }

  async function refresh() {
    await Promise.all([loadQueue(false), loadTimeline(false)]);
    render();
  }

  // -- rendering -------------------------------------------------------------------------
  function badge(status) { return el("span", { class: "badge " + status }, R.STATUS[status] || status); }

  function evidenceBlock(e) {
    const url = R.safeUrl(e.url);
    return el("blockquote", { class: "quote" },
      el("q", {}, e.quote),
      el("div", { class: "meta" },
        (R.ROLE[e.role] || e.role || "role neznámá") + " · " + (e.occurred_at || "čas neznámý"),
        " · zpráva " + e.message_id + " · konverzace " + e.conversation_id + " (" + e.source_system + ") ",
        el("button", { type: "button", class: "link", onclick: () => openSource(e) }, "detail zdroje"),
        url ? [" · ", el("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, "externí odkaz")] : null));
  }

  function itemCard(item) {
    const id = item.subject.kind + ":" + item.subject.identifier;
    const decision = R.decisionState(item, state.canDecide);
    const busy = state.busy.has(id);
    const open = state.expanded.has(id);
    const shown = open ? item.evidence : item.evidence.slice(0, 1);
    const buttons = el("div", { class: "actions" },
      el("button", { type: "button", class: "ok", disabled: !decision.allowed || busy, onclick: () => decide(item, "confirmed") }, busy ? "Probíhá…" : "Potvrdit"),
      el("button", { type: "button", class: "no", disabled: !decision.allowed || busy, onclick: () => decide(item, "rejected") }, busy ? "Probíhá…" : "Zamítnout"));
    return el("li", { class: "card item " + item.status + (busy ? " busy" : ""), "data-id": id },
      el("div", { class: "kindline" }, R.KIND[item.candidate_kind] || item.candidate_kind),
      el("div", { class: "title" }, R.title(item), " ", badge(item.status)),
      item.summary ? el("p", {}, item.summary) : null,
      item.proposal ? el("div", { class: "meta" }, "Skóre " + item.proposal.score + ": " + item.proposal.reason) : null,
      el("div", { class: "origin" }, item.contributions.length
        ? item.contributions.map((c) => el("div", {}, "• " + R.originText(c)))
        : el("div", {}, "Původ není v auditu doložen.")),
      !item.audit.consistent && item.status === "candidate" ? el("div", { class: "warn" }, "Audit nesouhlasí s aktuálním stavem.") : null,
      el("div", {}, shown.length ? shown.map(evidenceBlock) : el("div", { class: "meta" }, "Žádná živá evidence.")),
      item.evidence.length > 1
        ? el("button", { type: "button", class: "link evidence-extra", onclick: () => { open ? state.expanded.delete(id) : state.expanded.add(id); render(); } },
            open ? "Skrýt ostatní evidence" : "Zobrazit všech " + item.evidence.length + " evidencí")
        : null,
      item.decision ? el("div", { class: "meta" }, "Rozhodl " + item.decision.actor.identifier + " (ověřeno tokenem) · " + item.decision.recorded_at) : null,
      buttons,
      decision.allowed ? null : el("div", { class: "why" }, decision.reason));
  }

  function renderQueue() {
    const list = $("queue");
    list.replaceChildren();
    if (!state.token) { $("queue-info").textContent = "Připojte se tokenem."; $("more").hidden = true; return; }
    $("queue-info").textContent = "Zobrazeno " + state.items.length + " z " + state.total + ".";
    if (!state.items.length) list.append(el("li", { class: "empty" }, "Žádní kandidáti v tomto filtru."));
    for (const item of state.items) list.append(itemCard(item));
    $("more").hidden = !state.hasMore;
  }

  function renderTimeline() {
    const list = $("timeline");
    list.replaceChildren();
    $("timeline-info").textContent = state.token ? "Událost se zobrazí až po skutečném dokončení operace. Nejnovější nahoře." : "";
    for (const event of state.timeline) {
      const row = R.eventRow(event);
      const css = event.type.replace("candidate.", "t-").replace("context.assembled", "t-context").replace("source.deleted", "t-deleted");
      list.append(el("li", { class: row.known ? css : "t-unknown" },
        el("strong", {}, row.label), " · ", row.subject,
        el("div", {}, row.summary),
        el("div", { class: "when" }, "zapsáno " + row.when + " · vznik " + row.occurred + " · " + row.actor + (row.sources ? " · " + row.sources : ""))));
    }
    $("older").hidden = !state.olderMore;
  }

  function render() { renderQueue(); renderTimeline(); if (!state.token) $("source-pane").replaceChildren(); }

  async function openSource(evidence) {
    const pane = $("source-pane");
    try {
      const data = await call("GET", "/v1/episodes/" + evidence.episode_id);
      pane.replaceChildren(
        el("h3", {}, "Původní zpráva"),
        el("div", { class: "meta" }, data.role + " · " + data.occurred_at + " · " + data.source_system + " / " + data.conversation_id + " / " + data.message_id),
        el("p", { class: "source-text" }, window.AMLogic.quoteSegments(data.content, evidence.quote).map((s) => (s.mark ? el("mark", {}, s.text) : s.text))),
        el("button", { type: "button", class: "link", onclick: () => pane.replaceChildren() }, "zavřít"));
    } catch (error) {
      say("Zdroj nelze zobrazit: " + (error.status === 404 ? "byl smazán." : error.message), "error");
    }
  }

  // -- decisions ---------------------------------------------------------------------------
  async function decide(item, wanted) {
    const id = item.subject.kind + ":" + item.subject.identifier;
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
      if (state.token) { try { await refresh(); } catch (error) { say("Obnovení selhalo: " + error.message, "error"); } }
    }
  }

  // -- wiring ------------------------------------------------------------------------------
  $("connect").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.token = $("token").value.trim(); $("token").value = "";
    try {
      const who = await call("GET", "/v1/whoami");
      state.clientId = who.client_id; state.canDecide = who.permissions.includes("admin");
      $("who").textContent = "Připojeno jako " + who.client_id + " · oprávnění: " + who.permissions.join(", ") +
        (state.canDecide ? "" : " · jen prohlížení");
      $("disconnect").hidden = false;
      await refresh();
      say("Připojeno.");
    } catch (error) {
      if (state.token) disconnect();
      say(error.message, "error");
    }
  });
  $("disconnect").addEventListener("click", () => { disconnect(); say("Odpojeno, token byl zapomenut."); });
  $("reload").addEventListener("click", () => refresh().catch((e) => say(e.message, "error")));
  $("f-kind").addEventListener("change", (e) => { state.filter.kind = e.target.value; refresh().catch((x) => say(x.message, "error")); });
  $("f-status").addEventListener("change", (e) => { state.filter.status = e.target.value; refresh().catch((x) => say(x.message, "error")); });
  $("more").addEventListener("click", () => loadQueue(true).then(render).catch((e) => say(e.message, "error")));
  $("older").addEventListener("click", () => loadTimeline(true).then(render).catch((e) => say(e.message, "error")));
  render();
})();
