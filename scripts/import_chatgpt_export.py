"""Import the official ChatGPT data export (conversations.json) into a running instance.

Export: ChatGPT > Settings > Data controls > Export data; the e-mailed zip holds conversations.json.
Each conversation is a tree (``mapping``); the branch that ends in ``current_node`` is imported,
oldest message first, with the original timestamps. Only user and assistant messages with plain
text are taken; empty, tool, system and non-text parts are skipped and counted. A message longer
than the API limit is skipped, never cut. Message ids come from the export, so re-running is safe.

The file holds personal data: keep it outside the repository.
Usage: MEMORY_CLIENT_API_KEY=... python scripts/import_chatgpt_export.py conversations.json [--dry-run]
The format is read from the documented structure of the export and tested on a synthetic file only.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

BASE = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8080")
LIMIT = 50000


def branch(conversation):
    """Messages of the current branch, oldest first."""
    mapping = conversation.get("mapping") or {}
    node, chain, seen = conversation.get("current_node"), [], set()
    while node and node in mapping and node not in seen:
        seen.add(node)
        chain.append(mapping[node])
        node = mapping[node].get("parent")
    return list(reversed(chain))


def text_of(message):
    content = message.get("content") or {}
    if content.get("content_type") != "text":
        return None
    parts = content.get("parts") or []
    if not all(isinstance(p, str) for p in parts):
        return None
    return "\n".join(parts)


def convert(conversations):
    """Return (message bodies, counts of skipped messages by reason)."""
    bodies, skipped = [], {"empty_or_not_text": 0, "other_role": 0, "too_long": 0}
    for conversation in conversations:
        cid = conversation.get("conversation_id") or conversation.get("id")
        if not cid:
            continue
        for node in branch(conversation):
            message = node.get("message")
            if not message:
                continue
            role = (message.get("author") or {}).get("role")
            if role not in ("user", "assistant"):
                skipped["other_role"] += 1
                continue
            text = text_of(message)
            stamp = message.get("create_time")
            if not text or not text.strip() or stamp is None:
                skipped["empty_or_not_text"] += 1
                continue
            if len(text) > LIMIT:
                skipped["too_long"] += 1
                continue
            bodies.append(
                {
                    "source_system": "chatgpt-export",
                    "conversation_id": str(cid),
                    "message_id": str(message.get("id") or node.get("id")),
                    "role": role,
                    "content": text,
                    "occurred_at": datetime.fromtimestamp(float(stamp), timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
    return bodies, skipped


def main(path, dry_run):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        sys.exit("Expected conversations.json: a list of conversations.")
    bodies, skipped = convert(data)
    print(f"Konverzací: {len(data)}, zpráv k nahrání: {len(bodies)}, přeskočeno: {skipped}.")
    if dry_run:
        return
    key = os.environ.get("MEMORY_CLIENT_API_KEY")
    if not key:
        sys.exit("Set MEMORY_CLIENT_API_KEY to a token with write permission.")
    new = 0
    with httpx.Client(
        base_url=BASE, headers={"Authorization": f"Bearer {key}"}, timeout=30
    ) as http:
        for body in bodies:
            response = http.post("/v1/episodes", json=body)
            response.raise_for_status()
            new += 0 if response.json()["duplicate"] else 1
        for _ in range(60):
            jobs = http.get("/v1/jobs").json()
            if not any(j["status"] in ("pending", "running") for j in jobs.get("jobs", jobs)):
                break
            time.sleep(0.5)
    print(f"Nových zpráv: {new}.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    if len(args) != 1:
        sys.exit(__doc__)
    main(args[0], "--dry-run" in sys.argv)
