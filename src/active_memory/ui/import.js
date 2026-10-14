// Import view: pick conversations.json from the ChatGPT export, see what it contains, then send it.
// The file is read in this page only (nothing is uploaded before the person presses the button) and
// the messages go through the same API as every other producer; they become candidates, never facts.
(function () {
  "use strict";
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = { plan: null, running: false, cancel: false };

  function say(text, isError) {
    $("import-result").textContent = text || "";
    $("import-result").className = "note" + (isError ? " error" : "");
    $("import-result").hidden = !text;
  }

  async function choose() {
    const file = $("import-file").files[0];
    state.plan = null; $("import-start").hidden = true; say("");
    if (!file) { $("import-preview").textContent = ""; return; }
    $("import-preview").textContent = "Čtu soubor v tomto okně…";
    try {
      const data = JSON.parse(await file.text());
      if (!Array.isArray(data)) throw new Error("Očekávám conversations.json: seznam konverzací.");
      state.plan = window.AMImport.convert(data);
    } catch (error) {
      $("import-preview").textContent = "";
      say("Soubor nelze přečíst: " + error.message, true);
      return;
    }
    const p = state.plan, s = p.skipped;
    $("import-preview").textContent = "Konverzací: " + p.conversations + ", zpráv k nahrání: " + p.bodies.length +
      ". Přeskočeno: prázdné nebo ne čistý text " + s.empty_or_not_text + ", systémové a nástrojové " + s.other_role +
      ", delší než " + window.AMImport.LIMIT + " znaků " + s.too_long + ".";
    $("import-start").hidden = !p.bodies.length;
  }

  async function start() {
    if (!state.plan || state.running) return;
    state.running = true; state.cancel = false;
    $("import-start").disabled = true; $("import-cancel").hidden = false;
    const bodies = state.plan.bodies;
    let done = 0, fresh = 0;
    try {
      for (const body of bodies) {
        if (state.cancel) break;
        const r = await S.call("POST", "/v1/episodes", body);
        done++; if (!r.duplicate) fresh++;
        if (done % 10 === 0 || done === bodies.length) say("Odesláno " + done + " z " + bodies.length + " (nových " + fresh + ").");
      }
      say((state.cancel ? "Zastaveno. " : "Hotovo. ") + "Odesláno " + done + " z " + bodies.length + ", nových " + fresh +
        ". Opakování je bezpečné, shodné zprávy se přeskočí. Zprávy najdete v Konverzacích.");
    } catch (error) {
      say("Import se zastavil po " + done + " zprávách: " + error.message +
        (error.status === 403 ? " Import potřebuje token s právem zápisu (write)." : ""), true);
    } finally {
      state.running = false; $("import-start").disabled = false; $("import-cancel").hidden = true;
      S.markDirty && S.markDirty();
    }
  }

  S.register("import", {
    async load() {},
    show() {
      $("import-info").textContent = S.connected ? "" : "Připojte se tokenem – bez něj se nic neodešle.";
      $("import-start").disabled = !S.connected;
    },
    clear() { state.plan = null; state.cancel = true; $("import-file").value = ""; $("import-preview").textContent = ""; $("import-start").hidden = true; say(""); },
  });
  $("import-file").addEventListener("change", choose);
  $("import-start").addEventListener("click", start);
  $("import-cancel").addEventListener("click", () => { state.cancel = true; });
})();
