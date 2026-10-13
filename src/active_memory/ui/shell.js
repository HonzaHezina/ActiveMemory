// Page shell: one document for every view, so the bearer token (kept in memory only) survives
// switching between views. Owns connection, the menu and the shared API call. Views register
// themselves: { load(), show(params), clear() }. All server data is rendered as text by the views.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const views = {};
  const session = { token: null, canDecide: false, clientId: null, active: "conversations", tab: null };

  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }

  function say(text, isError) {
    const box = $("message");
    box.textContent = text || "";
    box.className = "message" + (isError ? " error" : "");
  }

  async function call(method, path, body) {
    if (!session.token) throw new ApiError(0, "Nejste připojeni.");
    const response = await fetch(path, {
      method, cache: "no-store",
      headers: Object.assign({ Authorization: "Bearer " + session.token }, body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (response.status === 401) { disconnect(); throw new ApiError(401, "Token není platný nebo byl odvolán. Připojte se znovu."); }
    if (response.status === 403) throw new ApiError(403, "Token nemá potřebné oprávnění.");
    if (response.status === 404) throw new ApiError(404, "Nenalezeno (možná bylo smazáno).");
    if (response.status === 409 || response.status === 503) {
      const detail = await response.json().catch(() => ({}));
      throw new ApiError(response.status, detail.detail || (response.status === 409 ? "Stav se mezitím změnil." : "Služba je dočasně nedostupná."));
    }
    if (!response.ok) throw new ApiError(response.status, "Požadavek selhal (" + response.status + ").");
    return response.json();
  }

  function register(name, view) { views[name] = Object.assign({ dirty: true }, view); }

  function markDirty() { for (const view of Object.values(views)) view.dirty = true; }

  function paintNav() {
    for (const button of document.querySelectorAll("#nav button")) {
      const on = button.dataset.view === session.active && (!button.dataset.tab || button.dataset.tab === session.tab);
      button.classList.toggle("active", on);
      if (on) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    }
    for (const section of document.querySelectorAll("main > section[data-view]")) {
      section.hidden = section.dataset.view !== session.active;
    }
  }

  async function show(name, params) {
    session.active = name;
    session.tab = (params && params.tab) || (name === "map" ? session.tab || "themes" : null);
    paintNav();
    const view = views[name];
    if (!view) return;
    try {
      if (session.token && view.dirty) { view.dirty = false; await view.load(params || {}); }
      view.show(params || {});
    } catch (error) {
      view.dirty = true;
      say(error.message, true);
    }
  }

  async function refreshCount() {
    if (!session.token) { $("review-count").textContent = ""; return; }
    try {
      const page = await call("GET", "/v1/candidates?kind=all&status=candidate&limit=1");
      $("review-count").textContent = page.total ? "(" + page.total + ")" : "";
    } catch (error) { /* the count is a hint; the views report real errors */ }
  }

  function disconnect() {
    session.token = null; session.canDecide = false; session.clientId = null;
    $("who").textContent = ""; $("disconnect").hidden = true; $("connect").hidden = false;
    $("review-count").textContent = ""; $("proposal-count").textContent = "";
    markDirty();
    for (const view of Object.values(views)) view.clear();
  }

  $("connect").addEventListener("submit", async (event) => {
    event.preventDefault();
    session.token = $("token").value.trim(); $("token").value = "";
    try {
      const who = await call("GET", "/v1/whoami");
      session.clientId = who.client_id; session.canDecide = who.permissions.includes("admin");
      $("who").textContent = "Připojeno jako " + who.client_id + " · oprávnění: " + who.permissions.join(", ") +
        (session.canDecide ? "" : " · jen prohlížení");
      $("disconnect").hidden = false; $("connect").hidden = true;
      markDirty();
      say("Připojeno.");
      await show(session.active, { tab: session.tab });
      refreshCount();
    } catch (error) {
      if (session.token) disconnect();
      say(error.message, true);
    }
  });
  $("disconnect").addEventListener("click", () => { disconnect(); say("Odpojeno, token byl zapomenut."); });
  for (const button of document.querySelectorAll("#nav button")) {
    button.addEventListener("click", () => show(button.dataset.view, button.dataset.tab ? { tab: button.dataset.tab } : {}));
  }

  window.AMShell = {
    ApiError, register, show, call, say, refreshCount,
    get canDecide() { return session.canDecide; },
    get connected() { return !!session.token; },
  };
  document.addEventListener("DOMContentLoaded", () => show("conversations"));
})();
