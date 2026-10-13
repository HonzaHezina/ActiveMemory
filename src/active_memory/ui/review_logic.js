// Pure helpers for the review queue page: wording, link safety and what may be claimed.
// No DOM and no network, so it is unit-tested in Node. Wording only restates recorded facts.
(function (root) {
  "use strict";

  const STATUS = { candidate: "kandidát", confirmed: "potvrzeno", rejected: "zamítnuto" };
  const ROLE = { user: "uživatel", assistant: "asistent", tool: "nástroj", system: "systém" };
  const KIND = {
    Theme: "Téma", Thought: "Myšlenka", Fact: "Fakt", Question: "Otázka", Goal: "Cíl",
    Decision: "Rozhodnutí",
    ABOUT: "Vazba: patří k tématu", SUPPORTS: "Vazba: podporuje", REFINES: "Vazba: zpřesňuje",
    CONTRADICTS: "Vazba: je v rozporu", SUPERSEDES: "Vazba: nahrazuje", ALIAS_OF: "Vazba: totéž jako",
  };
  const EVENT = {
    "candidate.created": "Návrh vytvořen",
    "candidate.evidence_added": "K návrhu přibyla další evidence",
    "candidate.confirmed": "Návrh potvrzen",
    "candidate.rejected": "Návrh zamítnut",
    "candidate.snapshot": "Stav zaznamenán (snapshot)",
    "context.assembled": "Sestaven kontext",
    "source.deleted": "Zdroj smazán",
  };

  // Only absolute http(s) links are ever rendered as links; anything else is shown as plain text.
  function safeUrl(value) {
    if (typeof value !== "string" || value.length > 2000) return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
    } catch (error) {
      return null;
    }
  }

  function clientName(origin) {
    return origin && origin.supplied_by_client ? origin.supplied_by_client : "neuveden";
  }

  // Provenance of one contribution. Unknown stays unknown; nothing is guessed.
  function originText(contribution) {
    const o = contribution.origin;
    if (contribution.type === "candidate.snapshot" || !o) {
      return "Původ neznámý – stav zaznamenán dodatečně (snapshot), ne při vzniku.";
    }
    switch (o.kind) {
      case "client_supplied_extraction":
        return "Dodaná extrakce – autor neuveden (předal klient: " + clientName(o) + ").";
      case "llm_extraction":
        return "Extrakce modelem " + (o.model || "?") + (o.provider ? " (" + o.provider + ")" : "") +
          "; zprávu předal klient: " + clientName(o) + ".";
      case "similarity":
        return "Systém: návrh z podobnosti napříč chaty" + (o.score != null ? " (skóre " + o.score + ")" : "") + ".";
      case "temporal":
        return "Systém: návrh z navazujících intervalů platnosti" + (o.score != null ? " (skóre " + o.score + ")" : "") + ".";
      case "judge":
        return "Model " + (o.model || "?") + " posoudil vztah" + (o.provider ? " (" + o.provider + ")" : "") + ".";
      case "manual":
        return "Ručně navrhl klient: " + clientName(o) + " (identita člověka není ověřena).";
      default:
        return "Neznámý druh původu: " + String(o.kind);
    }
  }

  function title(item) {
    if (item.subject.kind === "link") {
      const s = item.source ? item.source.label : "(uzel nedostupný)";
      const t = item.target ? item.target.label : "(uzel nedostupný)";
      return s + " – " + (KIND[item.relation] || item.relation).replace("Vazba: ", "") + " – " + t;
    }
    return item.label;
  }

  // The page offers a decision only when the evidence supports it.
  function decisionState(item, canDecide) {
    if (item.status !== "candidate") return { allowed: false, reason: "Rozhodnuto: " + (STATUS[item.status] || item.status) + "." };
    if (!item.audit.consistent) {
      return {
        allowed: false,
        reason: "Audit nesouhlasí se stavem (poslední zaznamenaný stav: " +
          (item.audit.last_recorded_state || "žádný") + "). Rozhodnutí je zablokováno, dokud se záznam neobnoví.",
      };
    }
    if (!canDecide) return { allowed: false, reason: "Token nemá oprávnění admin; prohlížení je možné, rozhodovat ne." };
    return { allowed: true, reason: "" };
  }

  // After POST succeeded, the new state must be confirmed by a fresh read before success is shown.
  function verifyDecision(fresh, wanted) {
    if (fresh.status !== wanted) return "Server vrací jiný stav (" + fresh.status + ") než požadovaný.";
    if (!fresh.audit.consistent) return "Stav byl změněn, ale záznam v auditu zatím nesouhlasí.";
    if (!fresh.decision || fresh.decision.type !== "candidate." + wanted) return "Rozhodnutí není v auditu doložené.";
    return null;
  }

  function eventSummary(event) {
    const d = event.data || {};
    switch (event.type) {
      case "context.assembled":
        return "Pro " + d.requester + ": " + d.items_returned + " položek, " + d.chars_used + " z " +
          d.max_chars_requested + " znaků" + (d.truncated ? " (zkráceno)" : "") +
          (d.target_assistant ? ", asistent " + d.target_assistant : ", cílový asistent neznámý");
      case "candidate.created":
      case "candidate.evidence_added":
        return originText({ type: event.type, origin: d.origin });
      case "candidate.snapshot":
        return d.note + " Čas původní události je neznámý.";
      case "source.deleted":
        return "Smazáno z: " + (d.derived_stores_cleaned || []).join(", ") + ".";
      case "candidate.confirmed":
      case "candidate.rejected":
        return (event.previous_state || "?") + " → " + event.new_state;
      default:
        return "";
    }
  }

  function eventRow(event) {
    const known = Object.prototype.hasOwnProperty.call(EVENT, event.type);
    const view = event.subject_view;
    const subject = view && view.available ? view.label + " (" + (KIND[view.candidate_kind] || view.candidate_kind) + ")"
      : event.subject.kind === "memory_scope" ? "paměť " + event.subject.identifier
      : event.subject.kind + " " + event.subject.identifier.slice(0, 12) + (view && !view.available && event.subject.kind !== "source" ? " (už není dostupné)" : "");
    const sources = (event.provenance || []).filter((p) => p.kind === "source");
    const deleted = sources.filter((p) => p.deleted).length;
    return {
      label: known ? EVENT[event.type] : "Neznámý typ události (" + event.type + ")",
      known,
      when: when(event.recorded_at),
      whenIso: event.recorded_at,
      occurred: event.occurred_at ? when(event.occurred_at) : "čas vzniku neznámý",
      actor: event.actor.identifier + " (" + event.actor.kind +
        (event.actor.assurance === "bearer_token" ? ", ověřeno tokenem" : event.actor.assurance === "internal" ? ", interně" : "") + ")",
      subject,
      summary: known ? eventSummary(event) : "Tento klient typ nezná; zobrazena jen obálka.",
      sources: sources.length ? "zdrojů: " + sources.length + (deleted ? ", z toho smazáno: " + deleted : "") : "",
    };
  }

  // Czech date and time; unknown or invalid input is said to be unknown, never guessed.
  function when(iso) {
    if (!iso) return "čas neznámý";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "čas neznámý";
    return new Intl.DateTimeFormat("cs-CZ", { dateStyle: "medium", timeStyle: "short" }).format(date);
  }

  // Splits content into plain and marked segments for every quote that occurs in it. Overlapping
  // quotes are merged. Text is only ever returned as text.
  function markQuotes(content, quotes) {
    const spans = [];
    for (const quote of quotes || []) {
      if (!quote) continue;
      const at = content.indexOf(quote);
      if (at >= 0) spans.push([at, at + quote.length]);
    }
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const span of spans) {
      const last = merged[merged.length - 1];
      if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
      else merged.push(span.slice());
    }
    const parts = [];
    let pos = 0;
    for (const [start, end] of merged) {
      if (start > pos) parts.push({ text: content.slice(pos, start), mark: false });
      parts.push({ text: content.slice(start, end), mark: true });
      pos = end;
    }
    if (pos < content.length) parts.push({ text: content.slice(pos), mark: false });
    return parts.length ? parts : [{ text: content, mark: false }];
  }

  const api = { when, markQuotes, STATUS, ROLE, KIND, EVENT, safeUrl, originText, title, decisionState, verifyDecision, eventRow, eventSummary };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AMReview = api;
})(typeof window !== "undefined" ? window : globalThis);
