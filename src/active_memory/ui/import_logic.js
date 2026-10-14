// Pure conversion of the official ChatGPT export (conversations.json) into messages for the
// episodes API. Mirrors scripts/import_chatgpt_export.py: the branch ending in current_node,
// oldest first, original timestamps, ids from the export; only user/assistant plain text.
// No DOM and no network, so it is unit-tested in Node.
(function (root) {
  "use strict";

  const LIMIT = 50000;

  function branch(conversation) {
    const mapping = conversation.mapping || {};
    const chain = [], seen = new Set();
    let node = conversation.current_node;
    while (node && Object.prototype.hasOwnProperty.call(mapping, node) && !seen.has(node)) {
      seen.add(node);
      chain.push(mapping[node]);
      node = mapping[node].parent;
    }
    return chain.reverse();
  }

  function textOf(message) {
    const content = message.content || {};
    if (content.content_type !== "text") return null;
    const parts = content.parts || [];
    if (!parts.every((p) => typeof p === "string")) return null;
    return parts.join("\n");
  }

  function convert(conversations) {
    const bodies = [], list = [], skipped = { empty_or_not_text: 0, other_role: 0, too_long: 0 };
    let used = 0;
    for (const conversation of conversations) {
      const cid = conversation.conversation_id || conversation.id;
      if (!cid) continue;
      const before = bodies.length;
      for (const node of branch(conversation)) {
        const message = node.message;
        if (!message) continue;
        const role = (message.author || {}).role;
        if (role !== "user" && role !== "assistant") { skipped.other_role++; continue; }
        const text = textOf(message);
        const stamp = message.create_time;
        if (!text || !text.trim() || stamp === null || stamp === undefined) { skipped.empty_or_not_text++; continue; }
        if (text.length > LIMIT) { skipped.too_long++; continue; }
        bodies.push({
          source_system: "chatgpt-export", conversation_id: String(cid),
          message_id: String(message.id || node.id), role, content: text,
          occurred_at: new Date(Number(stamp) * 1000).toISOString(),
        });
      }
      if (bodies.length > before) {
        used++;
        const mine = bodies.slice(before);
        list.push({ id: String(cid), title: String(conversation.title || ""), bodies: mine, first: mine[0].occurred_at, last: mine[mine.length - 1].occurred_at });
      }
    }
    return { bodies, list, skipped, conversations: used };
  }

  const api = { LIMIT, branch, convert };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AMImport = api;
})(typeof window !== "undefined" ? window : globalThis);
