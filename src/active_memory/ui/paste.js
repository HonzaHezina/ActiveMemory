// Paste view: a conversation copied from any chat. The text is split into messages by speaker
// markers in this page, shown for correction (who speaks can be flipped), and only then sent.
// Messages arrive as candidates through the same API as every other producer. All text is shown
// as text only.
(function () {
  "use strict";
  const S = window.AMShell;
  const $ = (id) => document.getElementById(id);
  const state = { messages: [], running: false };

  function say(text, isError) {
    $("paste-result").textContent = text || "";
    $("paste-result").className = "note" + (isError ? " error" : "");
    $("paste-result").hidden = !text;
  }

  const today = () => new Date().toISOString().slice(0, 10);
  const ROLE = { user: "Vy", assistant: "Asistent" };

  function paint() {
    const ol = $("paste-list");
    ol.replaceChildren();
    state.messages.forEach((m) => {
      const who = document.createElement("button");
      who.type = "button"; who.className = "link"; who.textContent = ROLE[m.role] + " (změnit)";
      who.addEventListener("click", () => { m.role = m.role === "user" ? "assistant" : "user"; paint(); });
      const head = document.createElement("div");
      head.append(who);
      const body = document.createElement("div");
      body.className = "quote";
      body.textContent = m.content.length > 600 ? m.content.slice(0, 600) + "…" : m.content;
      const li = document.createElement("li");
      li.append(head, body);
      ol.append(li);
    });
    $("paste-send").hidden = !state.messages.length;
    $("paste-send").textContent = "Odeslat (" + state.messages.length + " zpráv)";
  }

  function parse() {
    say("");
    const r = window.AMImport.parsePaste($("paste-text").value);
    state.messages = r.messages;
    $("paste-preview").textContent = !r.messages.length ? "Není co odeslat: vložte text konverzace."
      : r.marked ? "Rozděleno na " + r.messages.length + " zpráv podle značek mluvčích." + (r.preamble ? " Text před první značkou (" + r.preamble + " znaků) se nepoužije." : "") + " Zkontrolujte, kdo mluví."
      : "Nenašel jsem značky mluvčích, vše je jedna zpráva od vás. Přidejte na začátek odpovědí například „ChatGPT:“ a rozdělte znovu.";
    paint();
  }

  async function send() {
    if (state.running || !state.messages.length) return;
    const day = $("paste-day").value || today();
    const bodies = window.AMImport.pasteBodies(state.messages, $("paste-title").value, day);
    const skipped = state.messages.length - bodies.length;
    state.running = true; $("paste-send").disabled = true;
    let fresh = 0; const rejected = [];
    try {
      for (const body of bodies) {
        try {
          const r = await S.call("POST", "/v1/episodes", body);
          if (!r.duplicate) fresh++;
        } catch (error) {
          if (error.status !== 422 && error.status !== 409) throw error;
          rejected.push(error.message);
        }
      }
      say("Odesláno " + bodies.length + " zpráv, nových " + fresh +
        (rejected.length ? ", odmítnuto serverem " + rejected.length + " (např. podezření na heslo nebo klíč v textu: " + rejected[0] + ")" : "") +
        (skipped ? ", přeskočeno delších než " + window.AMImport.LIMIT + " znaků: " + skipped : "") +
        ". Stejné vložení znovu nic nezdvojí. Najdete to v Konverzacích pod názvem s datem vložení.", rejected.length > 0);
    } catch (error) {
      say("Odesílání se zastavilo: " + error.message + (error.status === 403 ? " Vkládání potřebuje token s právem zápisu (write)." : ""), true);
    } finally {
      state.running = false; $("paste-send").disabled = false; S.markDirty();
    }
  }

  S.register("paste", {
    async load() {},
    show() {
      $("paste-info").textContent = S.connected ? "" : "Připojte se tokenem – bez něj se nic neodešle.";
      if (!$("paste-day").value) $("paste-day").value = today();
    },
    clear() {
      state.messages = []; $("paste-text").value = ""; $("paste-title").value = "";
      $("paste-preview").textContent = ""; $("paste-list").replaceChildren(); $("paste-send").hidden = true; say("");
    },
  });
  $("paste-parse").addEventListener("click", parse);
  $("paste-send").addEventListener("click", send);
})();
