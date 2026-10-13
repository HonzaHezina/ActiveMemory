// Settings view: LLM provider configuration for the background work (extraction of new messages,
// similarity, relation judge). Admin only. API keys are write-only: the server never returns them,
// and this page never prefills them. Success is shown only after the settings are read back.
(function () {
  "use strict";
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const TEXT = ["model_base_url", "model_name", "embedding_base_url", "embedding_model"];
  const CHECK = ["allow_model_calls", "judge_enabled", "auto_propose"];
  const state = { view: null };

  const radios = () => [...document.querySelectorAll('input[name="extraction_mode"]')];
  const mode = () => (radios().find((r) => r.checked) || {}).value;
  const hostOf = (url) => { try { return new URL(url).hostname; } catch (error) { return "(neplatná adresa)"; } };

  function result(text, isError) {
    const box = $("settings-result");
    box.hidden = !text;
    box.textContent = text || "";
    box.className = "note" + (isError ? " error" : "");
  }

  function fill(view) {
    state.view = view;
    const r = view.runtime;
    for (const radio of radios()) radio.checked = radio.value === r.extraction_mode;
    for (const key of TEXT) $("s-" + key).value = r[key];
    for (const key of CHECK) $("s-" + key).checked = !!r[key];
    $("s-similarity_mode").value = r.similarity_mode;
    $("s-model_api_key").value = ""; $("s-embedding_api_key").value = "";
    $("s-model-key-state").textContent = view.secrets.model_api_key ? "Klíč je nastaven (nezobrazuje se)." : "Klíč není nastaven.";
    $("s-emb-key-state").textContent = view.secrets.embedding_api_key ? "Klíč je nastaven (nezobrazuje se)." : "Klíč není nastaven.";
    consent();
    const a = view.active;
    $("settings-info").textContent = "Právě aktivní: extrakce " + (a.extraction === "llm" ? "modelem" : "dodaná (bez modelu)") +
      " · embeddingy " + (a.embeddings ? "zapnuty" : "vypnuty") + " · posuzování vazeb " + (a.judge ? "zapnuto" : "vypnuto") +
      (view.overridden.length ? " · nastaveno v rozhraní (přepisuje prostředí serveru)" : " · nastavení ze serveru");
    const u = view.usage;
    const line = (name, x) => x ? name + ": volání " + x.calls + (x.prompt_tokens !== undefined ? ", tokeny vstup/výstup " + x.prompt_tokens + "/" + x.completion_tokens : x.tokens !== undefined ? ", tokeny " + x.tokens : "") : name + ": nezapnuto";
    $("settings-state").replaceChildren(
      ...[line("Extrakce", u.extractor), line("Embeddingy", u.embedder), line("Posuzování vazeb", u.judge),
        "Čítače platí od posledního startu serveru."].map((t) => Object.assign(document.createElement("div"), { textContent: t })));
  }

  function syncPresets() {
    for (const [preset, field] of [["s-preset", "s-model_base_url"], ["s-emb-preset", "s-embedding_base_url"]]) {
      const known = [...$(preset).options].some((o) => o.value && o.value === $(field).value.trim());
      $(preset).value = known ? $(field).value.trim() : "";
    }
  }

  function consent() {
    syncPresets();
    const hosts = new Set();
    if (mode() === "llm" || $("s-judge_enabled").checked) hosts.add(hostOf($("s-model_base_url").value));
    if ($("s-similarity_mode").value === "embedding") hosts.add(hostOf($("s-embedding_base_url").value));
    $("s-consent-text").textContent = hosts.size
      ? "Souhlasím s odesíláním textů zpráv poskytovateli: " + [...hosts].join(", ") + ". Bez tohoto souhlasu se nic neodešle."
      : "Souhlasím s odesíláním textů zpráv poskytovateli modelu (zatím nic z nastavení nic neodesílá).";
  }

  function changes() {
    const r = state.view.runtime;
    const out = {};
    if (mode() && mode() !== r.extraction_mode) out.extraction_mode = mode();
    for (const key of TEXT) if ($("s-" + key).value.trim() !== r[key]) out[key] = $("s-" + key).value.trim();
    for (const key of CHECK) if ($("s-" + key).checked !== !!r[key]) out[key] = $("s-" + key).checked;
    if ($("s-similarity_mode").value !== r.similarity_mode) out.similarity_mode = $("s-similarity_mode").value;
    if ($("s-model_api_key").value) out.model_api_key = $("s-model_api_key").value;
    if ($("s-embedding_api_key").value) out.embedding_api_key = $("s-embedding_api_key").value;
    return out;
  }

  async function reload() {
    try { fill(await S.call("GET", "/v1/settings")); }
    catch (error) {
      state.view = null;
      $("settings-info").textContent = error.status === 403 ? "Nastavení smí zobrazit a měnit jen token s oprávněním admin." : error.message;
      $("settings-form").hidden = true;
      return;
    }
    $("settings-form").hidden = false;
  }

  async function save(event) {
    event.preventDefault();
    if (!state.view) return;
    const body = changes();
    if (!Object.keys(body).length) { result("Nic se nezměnilo."); return; }
    const wantsModel = (body.extraction_mode || state.view.runtime.extraction_mode) === "llm";
    if (wantsModel && !$("s-allow_model_calls").checked) {
      result("Model se nezapne bez vašeho souhlasu s odesíláním textů (bod 3).", true);
      return;
    }
    $("s-save").disabled = true;
    try {
      await S.call("PUT", "/v1/settings/llm", body);
      const fresh = await S.call("GET", "/v1/settings");
      fill(fresh);
      const bad = [];
      for (const [key, value] of Object.entries(body)) {
        if (key.endsWith("api_key")) { if (!fresh.secrets[key]) bad.push(key); }
        else if (fresh.runtime[key] !== value) bad.push(key);
      }
      result(bad.length ? "Uložení se nepodařilo ověřit u: " + bad.join(", ") : "Uloženo a ověřeno čtením zpět. Platí pro nově vložené zprávy.", bad.length > 0);
    } catch (error) {
      result("Nastavení nebylo změněno: " + error.message, true);
    } finally {
      $("s-save").disabled = false;
    }
  }

  async function test(target) {
    const button = $(target === "model" ? "s-test-model" : "s-test-embedding");
    button.disabled = true;
    result("Zkouším spojení (krátký vymyšlený text, ne vaše zprávy)…");
    try {
      const r = await S.call("POST", "/v1/settings/llm/test", { target });
      result(r.ok ? "Poskytovatel " + r.host + " odpověděl (" + r.latency_ms + " ms)."
        : "Poskytovatel " + r.host + " neodpověděl správně" + (r.status ? " (HTTP " + r.status + ")" : "") + (r.error ? " (" + r.error + ")" : "") + ".", !r.ok);
    } catch (error) {
      result("Test nelze provést: " + error.message + " (nejdřív uložte nastavení se souhlasem a klíčem).", true);
    } finally {
      button.disabled = false;
    }
  }

  S.register("settings", {
    async load() { await reload(); },
    show() { if (!S.connected) $("settings-info").textContent = "Připojte se tokenem – bez něj se nic nezobrazí."; },
    clear() {
      state.view = null; result("");
      for (const key of ["s-model_api_key", "s-embedding_api_key"]) $(key).value = "";
      $("settings-info").textContent = "Připojte se tokenem – bez něj se nic nezobrazí.";
      $("settings-state").replaceChildren();
    },
  });
  $("settings-form").addEventListener("submit", save);
  $("s-test-model").addEventListener("click", () => test("model"));
  $("s-test-embedding").addEventListener("click", () => test("embedding"));
  $("s-emb-preset").addEventListener("change", (e) => { if (e.target.value) { $("s-embedding_base_url").value = e.target.value; consent(); } });
  $("s-preset").addEventListener("change", (e) => { if (e.target.value) { $("s-model_base_url").value = e.target.value; consent(); } });
  for (const id of ["s-model_base_url", "s-embedding_base_url", "s-similarity_mode", "s-judge_enabled"]) $(id).addEventListener("input", consent);
  for (const radio of radios()) radio.addEventListener("change", consent);
})();
