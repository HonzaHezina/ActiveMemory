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

  // ---- pasted conversation --------------------------------------------------------------
  // Speaker markers at the start of a line: "Vy:", "You said:", "ChatGPT:", "**Claude:**" ...
  const USER = /^\s*(?:\*\*)?(?:you|vy|ty|já|user|human|uživatel|me)(?:\s+(?:said|řekl[a]?|napsal[a]?))?\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$/i;
  const BOT = /^\s*(?:\*\*)?(?:chatgpt|gpt-?\d[\w.-]*|claude|gemini|mistral|le chat|copilot|assistant|asistent|ai|model)(?:\s+(?:said|řekl[a]?|napsal[a]?|odpověděl[a]?))?\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$/i;

  // Split pasted text into messages by speaker markers. Without any marker the whole text is one
  // user message (`marked` is false so the page can warn). Text before the first marker is not
  // guessed into a message; its length is reported instead.
  function parsePaste(text) {
    const messages = [];
    let current = null, preamble = 0;
    for (const line of String(text).replace(/\r\n?/g, "\n").split("\n")) {
      let role = null, rest = line;
      let m = USER.exec(line);
      if (m) { role = "user"; rest = m[1]; }
      else if ((m = BOT.exec(line))) { role = "assistant"; rest = m[1]; }
      if (role) { current = { role, lines: [rest] }; messages.push(current); }
      else if (current) current.lines.push(line);
      else preamble += line.trim().length;
    }
    const out = messages.map((x) => ({ role: x.role, content: x.lines.join("\n").trim() })).filter((x) => x.content);
    if (!messages.length) {
      const whole = String(text).trim();
      return { messages: whole ? [{ role: "user", content: whole }] : [], marked: false, preamble: 0 };
    }
    return { messages: out, marked: true, preamble };
  }

  // 53-bit string hash (cyrb53); stable across runs so a repeated paste is recognised, not a security hash.
  function hash(str) {
    let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
      const ch = str.charCodeAt(i);
      h1 = Math.imul(h1 ^ ch, 2654435761); h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
  }

  // Messages with ids derived from title, date and content, so pasting the same thing again is a
  // recognised duplicate. Pasted text has no original times: `day` (YYYY-MM-DD) is the date the
  // person gives or today, and the conversation id says it was pasted.
  function pasteBodies(messages, title, day) {
    const name = (String(title).replace(/[\/\\\u0000-\u001f]+/g, " ").trim() || "Vložená konverzace").slice(0, 100);
    const cid = name + " (vloženo " + day + ", " + hash(JSON.stringify([title, day, messages])).slice(0, 8) + ")";
    const base = Date.parse(day + "T12:00:00Z");
    return messages.filter((x) => x.content.length <= LIMIT).map((x, i) => ({
      source_system: "pasted", conversation_id: cid, message_id: String(i + 1), role: x.role, content: x.content,
      occurred_at: new Date(base + i * 60000).toISOString(),
    }));
  }

  const api = { LIMIT, branch, convert, parsePaste, pasteBodies, hash };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AMImport = api;
})(typeof window !== "undefined" ? window : globalThis);
