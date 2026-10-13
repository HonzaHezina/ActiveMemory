// Pure graph model for the graph view: which nodes and relations to draw for a scope, capped so
// the picture stays readable. No DOM and no network, so it is unit-tested in Node.
(function (root) {
  "use strict";

  const MAX_NODES = 60;
  const convKey = (e) => e.source_system + "/" + e.conversation_id;
  const strength = (n) => (n.strength || 0) * 10 + (n.activity || 0);

  function conversations(map) {
    const seen = new Map();
    for (const node of map.nodes.filter((n) => n.status !== "rejected")) {
      for (const e of node.evidence || []) {
        const key = convKey(e);
        if (!seen.has(key)) seen.set(key, { key, source_system: e.source_system, conversation_id: e.conversation_id, nodes: new Set() });
        seen.get(key).nodes.add(node.id);
      }
    }
    return [...seen.values()].map((c) => ({ key: c.key, source_system: c.source_system, conversation_id: c.conversation_id, count: c.nodes.size }))
      .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key));
  }

  function themes(map) {
    return map.nodes.filter((n) => n.kind === "Theme" && n.status !== "rejected")
      .sort((a, b) => strength(b) - strength(a) || a.label.localeCompare(b.label));
  }

  // scope: {kind: "conversation", source_system, conversation_id} | {kind: "theme", id} | {kind: "all"}
  function buildGraph(map, scope, cap) {
    const limit = cap || MAX_NODES;
    const live = map.nodes.filter((n) => n.status !== "rejected");
    const byId = new Map(live.map((n) => [n.id, n]));
    const edges = map.edges.filter((e) => e.status !== "rejected" && byId.has(e.source_id) && byId.has(e.target_id));
    let seed = [];
    if (scope.kind === "conversation") {
      const key = scope.source_system + "/" + scope.conversation_id;
      seed = live.filter((n) => (n.evidence || []).some((e) => convKey(e) === key));
    } else if (scope.kind === "theme") {
      const theme = byId.get(scope.id);
      if (theme) {
        const members = new Set(edges.filter((e) => e.relation === "ABOUT" && e.target_id === theme.id).map((e) => e.source_id));
        seed = [theme, ...live.filter((n) => members.has(n.id))];
      }
    } else {
      seed = live.slice();
    }
    let truncated = false;
    const total = seed.length;
    if (seed.length > limit) {
      seed = seed.slice().sort((a, b) => strength(b) - strength(a) || a.id.localeCompare(b.id)).slice(0, limit);
      truncated = true;
    }
    const included = new Map(seed.map((n) => [n.id, n]));
    if (scope.kind === "conversation") {
      // The themes the items are about give the picture its structure.
      for (const e of edges) {
        if (e.relation === "ABOUT" && included.has(e.source_id) && !included.has(e.target_id) && included.size < limit + 15) {
          included.set(e.target_id, byId.get(e.target_id));
        }
      }
    }
    const nodes = [...included.values()].map((n) => ({
      id: n.id, label: n.label, type: "node", kind: n.kind, status: n.status, strength: n.strength || 0,
    }));
    const relations = edges.filter((e) => included.has(e.source_id) && included.has(e.target_id)).map((e) => ({
      id: e.id, source: e.source_id, target: e.target_id, relation: e.relation, status: e.status, type: "relation",
    }));
    const convs = new Map();
    const origins = [];
    for (const n of included.values()) {
      const keys = new Set((n.evidence || []).map(convKey));
      for (const key of keys) {
        const sample = n.evidence.find((e) => convKey(e) === key);
        if (!convs.has(key)) convs.set(key, { id: "conv:" + key, label: sample.conversation_id, type: "conversation", kind: "Conversation", status: "confirmed", source_system: sample.source_system, conversation_id: sample.conversation_id });
        origins.push({ id: "from:" + key + ">" + n.id, source: "conv:" + key, target: n.id, relation: "FROM", status: "confirmed", type: "origin" });
      }
    }
    return { nodes: nodes.concat([...convs.values()]), edges: relations.concat(origins), truncated, total, shown: nodes.length };
  }

  const api = { MAX_NODES, buildGraph, conversations, themes };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AMGraph = api;
})(typeof window !== "undefined" ? window : globalThis);
