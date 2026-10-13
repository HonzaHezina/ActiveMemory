import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from active_memory.api import create_app
from active_memory.settings import Settings

OWNER_KEY = "owner-test-key-with-at-least-24-chars"
READER_KEY = "reader-test-key-with-at-least-24-chars"
WRITER_KEY = "writer-test-key-with-at-least-24-chars"


@pytest.fixture
def app(tmp_path):
    clients = tmp_path / "clients.json"
    clients.write_text(
        json.dumps(
            [
                {
                    "id": "owner",
                    "key_sha256": hashlib.sha256(OWNER_KEY.encode()).hexdigest(),
                    "permissions": ["read", "write", "admin"],
                },
                {
                    "id": "reader",
                    "key_sha256": hashlib.sha256(READER_KEY.encode()).hexdigest(),
                    "permissions": ["read"],
                },
                {
                    "id": "writer",
                    "key_sha256": hashlib.sha256(WRITER_KEY.encode()).hexdigest(),
                    "permissions": ["write"],
                },
            ]
        )
    )
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", clients_file=clients, worker_enabled=False
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app, headers={"Authorization": f"Bearer {OWNER_KEY}"}) as client:
        yield client


def message(message_id="1", conversation="chat-a", **overrides):
    result = {
        "source_system": "demo",
        "conversation_id": conversation,
        "message_id": message_id,
        "role": "user",
        "content": "Chci vlastnit svoji AI paměť a propojovat opakující se myšlenky.",
        "occurred_at": "2026-10-01T10:00:00Z",
        "extraction": {
            "items": [
                {
                    "kind": "Goal",
                    "label": "Vlastní AI paměť",
                    "summary": "Chci vlastnit svoji AI paměť.",
                    "quote": "Chci vlastnit svoji AI paměť",
                    "themes": ["Vlastnictví dat"],
                    "confidence": 0.9,
                }
            ]
        },
    }
    result.update(overrides)
    return result


def drain(client):
    return client.portal.call(client.app.state.memory.process_one)
