const test = require("node:test");
const assert = require("node:assert/strict");
const I = require("../../src/active_memory/ui/import_logic.js");

const node = (id, parent, role, parts, t, type) => ({ id, parent, message: { id, author: { role }, create_time: t, content: { content_type: type || "text", parts } } });
const sample = () => [{
  conversation_id: "c1", current_node: "h",
  mapping: {
    root: { id: "root", parent: null, message: null },
    a: node("a", "root", "system", ["x"], 1760000000),
    b: node("b", "a", "user", ["Ahoj"], 1760000001),
    c: node("c", "b", "assistant", ["stará větev"], 1760000002),
    d: node("d", "b", "assistant", ["Dobrý den"], 1760000003),
    e: node("e", "d", "user", [""], 1760000004),
    f: node("f", "e", "assistant", [{ asset: 1 }], 1760000005, "multimodal_text"),
    g: node("g", "f", "user", ["Díky"], 1760000006),
    h: node("h", "g", "assistant", ["x".repeat(50001)], 1760000007),
  },
}];

test("current branch, in order, original times, counted skips", () => {
  const r = I.convert(sample());
  assert.deepEqual(r.bodies.map((b) => b.content), ["Ahoj", "Dobrý den", "Díky"]);
  assert.equal(r.bodies[0].occurred_at, "2025-10-09T08:53:21.000Z");
  assert.equal(r.bodies[0].message_id, "b");
  assert.deepEqual(r.skipped, { empty_or_not_text: 2, other_role: 1, too_long: 1 });
  assert.equal(r.conversations, 1);
  assert.equal(r.list.length, 1);
  assert.deepEqual([r.list[0].id, r.list[0].bodies.length, r.list[0].first < r.list[0].last], ["c1", 3, true]);
});

test("a cycle or missing ids do not hang or crash", () => {
  const loop = { x: { id: "x", parent: "x", message: null } };
  assert.equal(I.branch({ mapping: loop, current_node: "x" }).length, 1);
  assert.deepEqual(I.convert([{ mapping: {}, current_node: null }]).bodies, []);
  assert.deepEqual(I.convert([{ mapping: loop, current_node: "x" }]).bodies, []);
});
