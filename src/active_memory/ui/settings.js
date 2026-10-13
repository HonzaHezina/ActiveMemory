// Settings view: LLM provider configuration for the background work (extraction of new messages,
// advice, relation judging, embeddings). Admin only. API keys are write-only: the server never
// returns them and this page never prefills them. Success is shown only after reading back.
// Embeddings use the model's provider and key unless the person says otherwise.
(function () {
  "use strict";
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const TEXT = ["model_base_url", "model_name", "advice_model", "embedding_model"];
  const CHECK = ["allow_model_calls", "judge_enabled", "auto_propose", "recommend_enabled"];
  const state = { view: null };

  const radios = () => [...document.querySelectorAll('input[name="extraction_mode"]')];
  const mode = () => (radios().find((r) => r.checked) || {}).value;
  const hostOf = (url) => { try { return new URL(url).hostname; } catch (error) { return "(neplatná adresa)"; } };
  const presets = () => (state.view ? state.view.presets : []);

  function result(text, isError) {
    const box = $("settings-result");
    box.hidden = !text;
    box.textContent = text || "";
    box.className = "note" + (isError ? " error" : "");
  }

  function fillPresetList() {
    const select = $("s-preset");
    select.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "(vlastní)" }));
    for (const p of presets()) select.append(Object.assign(document.createElement("option"), { value: p.id, textContent: p.label }));
  }

  // The preset that matches the current address, so the note stays truthful when the address is edited.
  function syncPreset() {
    const url = $("s-model_base_url").value.trim().replace(/\/$/, "");
    const hit = presets().find((p) => p.base_url.replace(/\/$/, "") === url);
    $("s-preset").value = hit ? hit.id : "";
    $("s-preset-note").textContent = hit ? hit.note : "Vlastní adresa: zadejte rozhraní kompatibilní s OpenAI (/chat/completions, /embeddings).";
    if (hit) {
      $("s-model_name").placeholder = hit.model ? "např. " + hit.model : "název modelu";
      $("s-advice_model").placeholder = hit.advice_model ? "(prázdné = stejný; doporučeno " + hit.advice_model + ")" : "(prázdné = stejný jako pro extrakci)";
      $("s-embedding_model").placeholder = hit.embedding_model ? "(prázdné = " + hit.embedding_model + ")" : "(prázdné = obvyklý model poskytovatele)";
    }
  }

  function applyPreset(id) {
    const p = presets().find((x) => x.id === id);
    if (!p) { syncPreset(); return; }
    $("s-model_base_url").value = p.base_url;
    if (p.model) $("s-model_name").value = p.model;
    if (p.advice_model) $("s-advice_model").value = p.advice_model;
    $("s-embedding_model").value = "";
    consent();
  }

  function fill(view) {
    state.view = view;
    fillPresetList();
    const r = view.runtime;
    for (const radio of radios()) radio.checked = radio.value === r.extraction_mode;
    for (const key of TEXT) $("s-" + key).value = r[key] || "";
    for (const key of CHECK) $("s-" + key).checked = !!r[key];
    $("s-similarity_mode").value = r.similarity_mode;
    $("s-max_recommend_calls").value = r.max_recommend_calls;
    $("s-embedding_base_url").value = r.embedding_base_url || "";
    $("s-model_api_key").value = ""; $("s-embedding_api_key").value = "";
    $("s-model-key-state").textContent = view.secrets.model_api_key ? "Klíč je nastaven (nezobrazuje se)." : "Klíč není nastaven.";
    $("s-emb-key-state").textContent = view.secrets.embedding_api_key ? "Vlastní klíč embeddingů je nastaven (nezobrazuje se)." : "Vlastní klíč embeddingů není nastaven.";
    $("s-emb-same").checked = view.effective.embedding_same_provider && view.effective.embedding_same_key;
    consent();
    const a = view.active;
    $("settings-info").textContent = "Právě aktivní: extrakce " + (a.extraction === "llm" ? "modelem" : "dodaná (bez modelu)") +
      " · embeddingy " + (a.embeddings ? "zapnuty" : "vypnuty") + " · posuzování vazeb " + (a.judge ? "zapnuto" : "vypnuto") +
      " · rady modelu " + (a.recommendations ? "zapnuty" : "vypnuty") +
      (view.overridden.length ? " · nastaveno v rozhraní (přepisuje prostředí serveru)" : " · nastavení ze serveru");
    const u = view.usage;
    const line = (name, x) => x ? name + ": volání " + x.calls + (x.prompt_tokens !== undefined ? ", tokeny vstup/výstup " + x.prompt_tokens + "/" + x.completion_tokens : x.tokens !== undefined ? ", tokeny " + x.tokens : "") : name + ": nezapnuto";
    $("settings-state").replaceChildren(
      ...[line("Extrakce", u.extractor), line("Embeddingy", u.embedder), line("Posuzování vazeb", u.judge), line("Rady modelu", u.recommender),
        "Čítače platí od posledního startu serveru."].map((t) => Object.assign(document.createElement("div"), { textContent: t })));
  }

  function consent() {
    const same = $("s-emb-same").checked;
    $("s-emb-own").hidden = same;
    // Model shown when the field is empty: the preset of the address in the form, else what the server uses.
    const url = $("s-model_base_url").value.trim().replace(/\/$/, "");
    const hit = presets().find((p) => p.base_url.replace(/\/$/, "") === url);
    const saved = state.view && state.view.runtime.model_base_url.replace(/\/$/, "") === url ? state.view.effective.embedding_model : "";
    const guess = $("s-embedding_model").value || (same ? (hit ? hit.embedding_model : saved) : saved) || "";
    $("s-emb-effective").textContent = (same ? "Embeddingy půjdou na " + hostOf($("s-model_base_url").value) + " s klíčem modelu" : "Embeddingy půjdou na vlastní adresu a klíč") +
      "; model: " + (guess || "(není znám, zadejte)") + ".";
    const hosts = new Set();
    if (mode() === "llm" || $("s-judge_enabled").checked || $("s-recommend_enabled").checked) hosts.add(hostOf($("s-model_base_url").value));
    if ($("s-similarity_mode").value === "embedding") hosts.add(hostOf(same || !$("s-embedding_base_url").value.trim() ? $("s-model_base_url").value : $("s-embedding_base_url").value));
    $("s-consent-text").textContent = hosts.size
      ? "Souhlasím s odesíláním textů zpráv poskytovateli: " + [...hosts].join(", ") + ". Bez tohoto souhlasu se nic neodešle."
      : "Souhlasím s odesíláním textů zpráv poskytovateli modelu (zatím nic z nastavení nic neodesílá).";
    syncPreset();
  }

  function changes() {
    const r = state.view.runtime;
    const out = {};
    if (mode() && mode() !== r.extraction_mode) out.extraction_mode = mode();
    for (const key of TEXT) if ($("s-" + key).value.trim() !== (r[key] || "")) out[key] = $("s-" + key).value.trim();
    for (const key of CHECK) if ($("s-" + key).checked !== !!r[key]) out[key] = $("s-" + key).checked;
    if ($("s-similarity_mode").value !== r.similarity_mode) out.similarity_mode = $("s-similarity_mode").value;
    const cap = parseInt($("s-max_recommend_calls").value, 10);
    if (!Number.isNaN(cap) && cap !== r.max_recommend_calls) out.max_recommend_calls = cap;
    if ($("s-model_api_key").value) out.model_api_key = $("s-model_api_key").value;
    if ($("s-emb-same").checked) {
      // Same provider and key: hand both back to "same as the model".
      if (r.embedding_base_url) out.embedding_base_url = "";
      if (state.view.secrets.embedding_api_key) out.embedding_api_key = "";
    } else {
      const url = $("s-embedding_base_url").value.trim();
      if (url !== (r.embedding_base_url || "")) out.embedding_base_url = url;
      if ($("s-embedding_api_key").value) out.embedding_api_key = $("s-embedding_api_key").value;
    }
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
    const wantsModel = (body.extraction_mode || state.view.runtime.extraction_mode) === "llm" || $("s-recommend_enabled").checked;
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
        if (key.endsWith("api_key")) { if (!!fresh.secrets[key] !== (value !== "")) bad.push(key); }
        else if ((fresh.runtime[key] === undefined ? "" : fresh.runtime[key]) !== value) bad.push(key);
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

  async function clearKey(field, label) {
    if (!state.view) return;
    try {
      await S.call("PUT", "/v1/settings/llm", { [field]: "" });
      const fresh = await S.call("GET", "/v1/settings");
      fill(fresh);
      result(fresh.secrets[field] ? "Klíč se nepodařilo smazat." : label + " smazán.", !!fresh.secrets[field]);
    } catch (error) {
      result("Klíč nebyl smazán: " + error.message, true);
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
  $("s-clear-model-key").addEventListener("click", () => clearKey("model_api_key", "Klíč modelu"));
  $("s-clear-emb-key").addEventListener("click", () => clearKey("embedding_api_key", "Vlastní klíč embeddingů"));
  $("s-preset").addEventListener("change", (e) => applyPreset(e.target.value));
  for (const id of ["s-model_base_url", "s-embedding_base_url", "s-embedding_model", "s-similarity_mode", "s-judge_enabled", "s-recommend_enabled", "s-emb-same"]) {
    $(id).addEventListener("input", consent);
    $(id).addEventListener("change", consent);
  }
  for (const radio of radios()) radio.addEventListener("change", consent);
})();
