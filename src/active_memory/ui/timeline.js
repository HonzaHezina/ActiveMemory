// Timeline view: recent events from the public events endpoint, newest first. Only what the log
// records is shown; unknown event types are shown as an envelope.
(function () {
  "use strict";
  const R = window.AMReview;
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = { events: [], cursor: null, more: false };

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

  async function load(older) {
    const p = new URLSearchParams({ order: "desc", limit: "30", expand: "subject" });
    if (older && state.cursor) p.set("cursor", state.cursor);
    const page = await S.call("GET", "/v1/events?" + p);
    state.events = older ? state.events.concat(page.events) : page.events;
    state.cursor = page.next_cursor; state.more = page.has_more;
  }

  function render() {
    const list = $("timeline");
    list.replaceChildren();
    $("timeline-info").textContent = S.connected
      ? "Událost se zapíše až po skutečném dokončení operace. Nejnovější nahoře."
      : "Připojte se tokenem – bez něj se nic nezobrazí.";
    for (const event of state.events) {
      const row = R.eventRow(event);
      const css = event.type.replace("candidate.", "t-").replace("context.assembled", "t-context").replace("source.deleted", "t-deleted");
      const view = event.subject_view;
      const open = view && view.available && (event.subject.kind === "node" || event.subject.kind === "link")
        ? el("button", { type: "button", class: "link", onclick: () => S.show("review", { focus: { kind: event.subject.kind, id: event.subject.identifier } }) }, "Otevřít návrh")
        : null;
      list.append(el("li", { class: row.known ? css : "t-unknown" },
        el("div", { class: "when" }, row.when),
        el("div", {}, el("strong", {}, row.label), " · ", row.subject),
        el("div", {}, row.summary),
        open,
        el("details", { class: "tech" }, el("summary", {}, "Technické údaje"),
          el("div", {}, "Vznik: " + row.occurred + " · zapsal: " + row.actor + (row.sources ? " · " + row.sources : "")),
          el("div", {}, "Pořadí " + event.sequence + " · " + event.event_id))));
    }
    $("older").hidden = !state.more;
  }

  S.register("timeline", {
    async load() { await load(false); },
    show() { render(); },
    clear() { state.events = []; state.cursor = null; state.more = false; render(); },
  });
  $("older").addEventListener("click", () => load(true).then(render).catch((e) => S.say(e.message, true)));
})();
