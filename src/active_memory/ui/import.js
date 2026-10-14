// Import view: pick conversations.json from the ChatGPT export, choose which conversations to take,
// then send them. The file is read in this page only (nothing is uploaded before the person presses
// the button) and the messages go through the same API as every other producer; they become
// candidates, never facts. Titles come from the file and are shown as text only.
(function () {
  "use strict";
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = { plan: null, chosen: new Set(), running: false, cancel: false };

  function say(text, isError) {
    $("import-result").textContent = text || "";
    $("import-result").className = "note" + (isError ? " error" : "");
    $("import-result").hidden = !text;
  }

  const day = (iso) => iso.slice(0, 10);

  function visible() {
    const q = $("import-filter").value.trim().toLowerCase();
    return state.plan.list.filter((c) => !q || (c.title || c.id).toLowerCase().includes(q));
  }

  function chosenBodies() {
    return state.plan.list.filter((c) => state.chosen.has(c.id)).flatMap((c) => c.bodies);
  }

  function paintChosen() {
    const n = state.chosen.size, m = chosenBodies().length;
    $("import-chosen").textContent = "Vybráno konverzací: " + n + ", zpráv: " + m + ".";
    $("import-start").hidden = !n;
    $("import-start").textContent = "Odeslat vybrané (" + n + ")";
  }

  function paintList() {
    const ul = $("import-list");
    ul.replaceChildren();
    for (const c of visible()) {
      const box = document.createElement("input");
      box.type = "checkbox"; box.checked = state.chosen.has(c.id);
      box.addEventListener("change", () => { if (box.checked) state.chosen.add(c.id); else state.chosen.delete(c.id); paintChosen(); });
      const label = document.createElement("label");
      const title = document.createElement("strong");
      title.textContent = c.title || "(bez názvu)";
      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = " · " + c.bodies.length + " zpráv · " + day(c.first) + (day(c.last) !== day(c.first) ? " až " + day(c.last) : "");
      label.append(box, " ", title, meta);
      const li = document.createElement("li");
      li.append(label);
      ul.append(li);
    }
  }

  async function choose() {
    const file = $("import-file").files[0];
    state.plan = null; state.chosen = new Set(); $("import-start").hidden = true; $("import-picker").hidden = true; say("");
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
    p.list.sort((a, b) => (a.last < b.last ? 1 : -1));
    $("import-preview").textContent = "V souboru je " + p.conversations + " konverzací se " + p.bodies.length +
      " zprávami. Přeskočeno: prázdné nebo ne čistý text " + s.empty_or_not_text + ", systémové a nástrojové " + s.other_role +
      ", delší než " + window.AMImport.LIMIT + " znaků " + s.too_long + ". Nic zatím není vybráno.";
    $("import-picker").hidden = !p.list.length;
    $("import-filter").value = "";
    paintList(); paintChosen();
  }

  async function start() {
    if (!state.plan || state.running) return;
    const bodies = chosenBodies();
    if (!bodies.length) return;
    state.running = true; state.cancel = false;
    $("import-start").disabled = true; $("import-cancel").hidden = false;
    let done = 0, fresh = 0;
    const rejected = [];
    try {
      for (const body of bodies) {
        if (state.cancel) break;
        try {
          const r = await S.call("POST", "/v1/episodes", body);
          if (!r.duplicate) fresh++;
        } catch (error) {
          if (error.status !== 422 && error.status !== 409) throw error;
          rejected.push(error.message);
        }
        done++;
        if (done % 10 === 0 || done === bodies.length) say("Odesláno " + done + " z " + bodies.length + " (nových " + fresh + ").");
      }
      say((state.cancel ? "Zastaveno. " : "Hotovo. ") + "Odesláno " + done + " z " + bodies.length + ", nových " + fresh +
        (rejected.length ? ", odmítnuto serverem " + rejected.length + " (např. podezření na heslo nebo klíč v textu: " + rejected[0] + ")" : "") +
        ". Opakování je bezpečné, shodné zprávy se přeskočí. Zprávy najdete v Konverzacích.");
    } catch (error) {
      say("Import se zastavil po " + done + " zprávách: " + error.message +
        (error.status === 403 ? " Import potřebuje token s právem zápisu (write)." : ""), true);
    } finally {
      state.running = false; $("import-start").disabled = false; $("import-cancel").hidden = true;
      S.markDirty();
    }
  }

  S.register("import", {
    async load() {},
    show() {
      $("import-info").textContent = S.connected ? "" : "Připojte se tokenem – bez něj se nic neodešle.";
      $("import-start").disabled = !S.connected;
    },
    clear() {
      state.plan = null; state.chosen = new Set(); state.cancel = true; $("import-file").value = "";
      $("import-preview").textContent = ""; $("import-start").hidden = true; $("import-picker").hidden = true; say("");
    },
  });
  $("import-file").addEventListener("change", choose);
  $("import-filter").addEventListener("input", () => { if (state.plan) paintList(); });
  $("import-all").addEventListener("click", () => { for (const c of visible()) state.chosen.add(c.id); paintList(); paintChosen(); });
  $("import-none").addEventListener("click", () => { state.chosen.clear(); paintList(); paintChosen(); });
  $("import-start").addEventListener("click", start);
  $("import-cancel").addEventListener("click", () => { state.cancel = true; });
})();
