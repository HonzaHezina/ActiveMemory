"""Import conversations from a local JSON file into a running instance (never commit that file).

File format:
  {"source_system": "chatgpt-paste",
   "conversations": [
     {"conversation_id": "...", "start": "2026-10-13T12:00:00Z",
      "messages": [{"role": "user|assistant", "content": "...",
                    "items": [{"kind": "Question", "label": "...", "summary": "...",
                               "quote": "exact text from content", "themes": ["..."]}]}]}]}

Messages get ids "1", "2", ... in order and times start + 1 minute per message: when the original
timestamps are unknown, ``start`` is a placeholder and the conversation_id should say so.
``items`` are extractions *supplied by whoever wrote the file*, not by a model; they stay
candidates. Every quote is checked to be exact text of its message before anything is sent.
Safe to re-run: identical messages are recognised as duplicates.
Usage: MEMORY_CLIENT_API_KEY=... python scripts/import_chats.py chats.json
"""

import json
import os
import sys
from datetime import datetime, timedelta

import httpx

BASE = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8080")


def main(path):
    key = os.environ.get("MEMORY_CLIENT_API_KEY")
    if not key:
        sys.exit("Set MEMORY_CLIENT_API_KEY to a token with write permission.")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    bodies = []
    for conversation in data["conversations"]:
        start = datetime.fromisoformat(conversation["start"].replace("Z", "+00:00"))
        for index, entry in enumerate(conversation["messages"]):
            for item in entry.get("items", []):
                if item["quote"] not in entry["content"]:
                    sys.exit(f"Quote not found in message {index + 1}: {item['quote'][:60]!r}")
            body = {
                "source_system": data["source_system"],
                "conversation_id": conversation["conversation_id"],
                "message_id": str(index + 1),
                "role": entry["role"],
                "content": entry["content"],
                "occurred_at": (start + timedelta(minutes=index))
                .isoformat()
                .replace("+00:00", "Z"),
            }
            if entry.get("items"):
                body["extraction"] = {
                    "items": [{"confidence": 0.7, "themes": [], **i} for i in entry["items"]]
                }
            bodies.append(body)
    new = 0
    with httpx.Client(
        base_url=BASE, headers={"Authorization": f"Bearer {key}"}, timeout=30
    ) as http:
        for body in bodies:
            response = http.post("/v1/episodes", json=body)
            response.raise_for_status()
            new += 0 if response.json()["duplicate"] else 1
        # Let the worker process the queue before reporting.
        import time

        for _ in range(60):
            jobs = http.get("/v1/jobs").json()
            if not any(j["status"] in ("pending", "running") for j in jobs.get("jobs", jobs)):
                break
            time.sleep(0.5)
    print(f"Zpráv: {len(bodies)}, nových: {new}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
