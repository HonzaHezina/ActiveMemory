const test = require("node:test");
const assert = require("node:assert/strict");
const R = require("../../src/active_memory/ui/review_logic.js");

const item = (extra) => Object.assign({
  subject: { kind: "node", identifier: "n1" }, candidate_kind: "Thought", status: "candidate", label: "Návrh",
  audit: { consistent: true, last_recorded_state: "candidate" }, contributions: [], evidence: [],
}, extra || {});

test("links are only rendered for absolute http(s) URLs", () => {
  assert.equal(R.safeUrl("https://example.org/a?b=1"), "https://example.org/a?b=1");
  assert.equal(R.safeUrl("http://example.org"), "http://example.org/");
  for (const bad of ["javascript:alert(1)", "data:text/html,x", "//evil.example", "/relative", "", null, undefined, 5, "ftp://x.org", " javascript:alert(1)"]) {
    assert.equal(R.safeUrl(bad), null, String(bad));
  }
});

test("client supplied extraction never claims an author, a model or a human", () => {
  const text = R.originText({ type: "candidate.created", origin: { kind: "client_supplied_extraction", supplied_by_client: "writer" } });
  assert.match(text, /Dodaná extrakce – autor neuveden/);
  assert.match(text, /writer/);
  assert.doesNotMatch(text, /model|člověk/i);
});

test("model and provider are shown only when recorded", () => {
  const known = R.originText({ type: "candidate.created", origin: { kind: "llm_extraction", model: "m-1", provider: "api.example", supplied_by_client: "c" } });
  assert.match(known, /m-1/); assert.match(known, /api\.example/);
  const none = R.originText({ type: "candidate.created", origin: { kind: "judge", model: null, provider: null } });
  assert.doesNotMatch(none, /null/);
});

test("snapshots and missing origin are presented as unknown, not as creation", () => {
  assert.match(R.originText({ type: "candidate.snapshot", origin: null }), /Původ neznámý/);
  assert.match(R.originText({ type: "candidate.created", origin: null }), /Původ neznámý/);
});

test("decisions need candidate state, consistent audit and admin permission", () => {
  assert.equal(R.decisionState(item(), true).allowed, true);
  const noAdmin = R.decisionState(item(), false);
  assert.equal(noAdmin.allowed, false); assert.match(noAdmin.reason, /admin/);
  const drift = R.decisionState(item({ audit: { consistent: false, last_recorded_state: "confirmed" } }), true);
  assert.equal(drift.allowed, false); assert.match(drift.reason, /Audit nesouhlasí/);
  assert.equal(R.decisionState(item({ status: "confirmed" }), true).allowed, false);
});

test("success is only claimed after a fresh read matches state, audit and decision", () => {
  const ok = item({ status: "confirmed", decision: { type: "candidate.confirmed" } });
  assert.equal(R.verifyDecision(ok, "confirmed"), null);
  assert.match(R.verifyDecision(item({ status: "candidate" }), "confirmed"), /jiný stav/);
  assert.match(R.verifyDecision(Object.assign({}, ok, { audit: { consistent: false } }), "confirmed"), /audit/i);
  assert.match(R.verifyDecision(Object.assign({}, ok, { decision: null }), "confirmed"), /není v auditu/);
  assert.match(R.verifyDecision(Object.assign({}, ok, { decision: { type: "candidate.rejected" } }), "confirmed"), /není v auditu/);
});

const event = (extra) => Object.assign({
  type: "candidate.confirmed", recorded_at: "2026-10-01T10:00:00.000000Z", occurred_at: "2026-10-01T10:00:00.000000Z",
  actor: { kind: "human", identifier: "owner", assurance: "bearer_token" },
  subject: { kind: "node", identifier: "abcdef1234567890" }, previous_state: "candidate", new_state: "confirmed",
  provenance: [{ kind: "source", id: "s1", deleted: false }], data: {},
  subject_view: { available: true, candidate_kind: "Goal", label: "Cíl", status: "confirmed" },
}, extra || {});

test("timeline wording keeps the recorded meaning", () => {
  const row = R.eventRow(event());
  assert.equal(row.label, "Návrh potvrzen");
  assert.equal(row.summary, "candidate → confirmed");
  assert.match(row.actor, /ověřeno tokenem/);
  assert.match(row.subject, /Cíl/);
  const ctx = R.eventRow(event({ type: "context.assembled", subject: { kind: "memory_scope", identifier: "personal:owner" }, subject_view: undefined,
    data: { requester: "reader", items_returned: 2, chars_used: 300, max_chars_requested: 8000, truncated: false, target_assistant: null } }));
  assert.match(ctx.summary, /2 položek, 300 z 8000 znaků/);
  assert.match(ctx.summary, /cílový asistent neznámý/);
});

test("snapshot admits the unknown occurrence time; deleted sources are counted", () => {
  const snap = R.eventRow(event({ type: "candidate.snapshot", occurred_at: null, previous_state: null,
    data: { basis: "baseline_snapshot", note: "Stav zaznamenán při zavedení." } }));
  assert.equal(snap.occurred, "čas vzniku neznámý");
  assert.match(snap.summary, /neznámý/);
  const gone = R.eventRow(event({ provenance: [{ kind: "source", id: "s1", deleted: true }] }));
  assert.match(gone.sources, /smazáno: 1/);
});

test("unknown event types are shown as unknown, never reinterpreted", () => {
  const row = R.eventRow(event({ type: "agent.handoff", data: { anything: 1 } }));
  assert.equal(row.known, false);
  assert.match(row.label, /Neznámý typ události \(agent\.handoff\)/);
  assert.doesNotMatch(row.summary, /anything/);
});

test("unavailable subjects are labelled, not guessed", () => {
  const row = R.eventRow(event({ subject_view: { available: false } }));
  assert.match(row.subject, /už není dostupné/);
});

test("link titles name both ends and tolerate a missing end", () => {
  const link = item({ subject: { kind: "link", identifier: "l" }, candidate_kind: "SUPERSEDES", relation: "SUPERSEDES",
    source: { label: "Neo4j" }, target: null });
  assert.equal(R.title(link), "Neo4j – nahrazuje – (uzel nedostupný)");
});

test("markQuotes marks every quote found, merges overlaps and keeps text as text", () => {
  const parts = R.markQuotes("Chci paměť a kontrolu nad ní. <b>x</b>", ["paměť", "kontrolu nad ní", "neexistuje", "ní. <b>"]);
  assert.deepEqual(parts.filter((p) => p.mark).map((p) => p.text), ["paměť", "kontrolu nad ní. <b>"]);
  assert.equal(parts.map((p) => p.text).join(""), "Chci paměť a kontrolu nad ní. <b>x</b>");
  assert.deepEqual(R.markQuotes("beze změny", ["jiné"]), [{ text: "beze změny", mark: false }]);
});

test("when formats real times and admits unknown ones", () => {
  assert.equal(R.when(null), "čas neznámý");
  assert.equal(R.when("není datum"), "čas neznámý");
  assert.match(R.when("2026-10-01T10:00:00Z"), /2026/);
});

test("advice is worded as advice, with only recorded facts", () => {
  assert.equal(R.adviceHead({ model: "m1", provider: "llm.example.org", recommendation: "confirm", confidence: 0.86 }),
    "m1 (llm.example.org) doporučuje: potvrdit, jistota 86 %.");
  assert.match(R.adviceHead({ recommendation: "unsure" }), /^model neuveden doporučuje: nejistý\.$/);
  assert.equal(R.agreementText({ recommendation_agrees: true }), "Vaše rozhodnutí se shoduje s radou modelu.");
  assert.equal(R.agreementText({ recommendation_agrees: false }), "Rozhodli jste jinak, než model radil.");
  assert.equal(R.agreementText({ recommendation_agrees: null }), "");
  const row = R.eventRow({ type: "candidate.recommended", recorded_at: "2026-10-01T10:00:00Z", occurred_at: "2026-10-01T10:00:00Z",
    actor: { kind: "model", identifier: "m1", assurance: "internal" }, subject: { kind: "node", identifier: "n1" }, provenance: [],
    data: { recommendation: "reject", confidence: 0.4, model: "m1", provider: "x.org" } });
  assert.match(row.summary, /Rozhodnutí zůstává na člověku/);
  assert.match(row.label, /rada, ne rozhodnutí/);
});

test("queue kinds: default leaves out theme links, theme links have their own choice", () => {
  assert.deepEqual(R.queueKind("main"), { kind: "all", exclude_relation: "ABOUT" });
  assert.deepEqual(R.queueKind("about"), { kind: "link", relation: "ABOUT" });
  assert.deepEqual(R.queueKind("all"), { kind: "all" });
  assert.deepEqual(R.queueKind("nonsense"), R.queueKind("main"));
});
