import json

from conftest import READER_KEY, WRITER_KEY, drain, message

from active_memory.api import create_app
from active_memory.settings import Settings


def test_ingest_is_queued_idempotent_and_rejects_changed_payload(client):
    first = client.post("/v1/episodes", json=message())
    assert first.status_code == 202
    assert client.get("/v1/map").json()["nodes"] == []
    duplicate = client.post("/v1/episodes", json=message()).json()
    assert duplicate["duplicate"]
    assert duplicate["episode_id"] == first.json()["episode_id"]
    changed = message(content="Jiné znění", extraction=None)
    assert client.post("/v1/episodes", json=changed).status_code == 409
    drain(client)
    assert len(client.get("/v1/map").json()["nodes"]) == 2
    assert client.get("/v1/jobs").json()["jobs"][0]["status"] == "done"


def test_scope_and_permissions_default_deny(client):
    assert client.get("/v1/map", headers={"Authorization": "Bearer invalid"}).status_code == 401
    reader = {"Authorization": f"Bearer {READER_KEY}"}
    writer = {"Authorization": f"Bearer {WRITER_KEY}"}
    assert client.post("/v1/episodes", json=message(), headers=reader).status_code == 403
    assert client.get("/v1/map", headers=writer).status_code == 403
    assert client.post("/v1/maintenance/consolidate", headers=reader).status_code == 403
    assert (
        client.post("/v1/episodes", json={**message(), "scope": "personal:someone"}).status_code
        == 422
    )
    assert (
        client.post("/v1/search", json={"query": "test", "group_ids": ["other"]}).status_code == 422
    )


def test_provenance_candidate_review_and_context_budget(client):
    episode_id = client.post("/v1/episodes", json=message()).json()["episode_id"]
    drain(client)
    assert client.post("/v1/context", json={"query": "paměť"}).json()["items"] == []
    node = next(n for n in client.get("/v1/map").json()["nodes"] if n["kind"] == "Goal")
    assert node["evidence"][0]["episode_id"] == episode_id
    response = client.post(f"/v1/nodes/{node['id']}/review", json={"status": "confirmed"})
    assert response.status_code == 200
    context = client.post("/v1/context", json={"query": "paměť", "max_chars": 1000}).json()
    assert len(context["items"]) == 1
    assert len(context["text"]) == context["used_chars"] <= 1000
    tiny = client.post("/v1/context", json={"query": "paměť", "max_chars": 100}).json()
    assert tiny["items"] == [] and tiny["truncated"]
    assert client.get(f"/v1/episodes/{episode_id}").json()["content"] == message()["content"]


def test_theme_spans_different_conversations_without_fabricating_truth(client):
    for i, conversation in enumerate(["architecture", "fitness-business"]):
        client.post("/v1/episodes", json=message(str(i), conversation))
        drain(client)
    theme = next(n for n in client.get("/v1/map").json()["nodes"] if n["kind"] == "Theme")
    assert theme["strength"] == 2
    assert theme["conversation_count"] == 2
    assert theme["status"] == "candidate"
    report = client.post("/v1/maintenance/consolidate").json()
    assert report["recurring_themes"] == 1


def test_unsupported_quotes_dates_and_secret_filter(client):
    bad = message()
    bad["extraction"]["items"][0]["quote"] = "Tohle nikdo neřekl"
    assert client.post("/v1/episodes", json=bad).status_code == 422
    assert (
        client.post("/v1/episodes", json=message(occurred_at="2026-10-01T10:00:00")).status_code
        == 422
    )
    secret = message(content="api_key=very-secret-value-abcdefghij", extraction=None)
    assert client.post("/v1/episodes", json=secret).status_code == 422


def test_same_label_different_claim_keeps_versions(client):
    first = message()
    second = message("2", content="Nechci vlastnit svoji AI paměť.")
    second["extraction"]["items"][0].update(
        summary="Nechci vlastnit svoji AI paměť.", quote="Nechci vlastnit svoji AI paměť"
    )
    for payload in (first, second):
        assert client.post("/v1/episodes", json=payload).status_code == 202
        drain(client)
    goals = [n for n in client.get("/v1/map").json()["nodes"] if n["kind"] == "Goal"]
    assert len(goals) == 2
    assert {g["summary"] for g in goals} == {
        "Chci vlastnit svoji AI paměť.",
        "Nechci vlastnit svoji AI paměť.",
    }


def test_current_and_historical_facts_have_exclusive_validity(client):
    for i, (person, start, end) in enumerate(
        [
            ("Petr", "2026-01-01T00:00:00Z", "2026-10-01T00:00:00Z"),
            ("Jana", "2026-10-01T00:00:00Z", None),
        ]
    ):
        text = f"Projekt Atlas vede {person}."
        payload = message(
            str(i),
            content=text,
            extraction={
                "items": [
                    {
                        "kind": "Fact",
                        "label": "Vedení Atlas",
                        "summary": text,
                        "quote": text,
                        "valid_from": start,
                        "valid_to": end,
                    }
                ]
            },
        )
        client.post("/v1/episodes", json=payload)
        drain(client)
    for n in client.get("/v1/map").json()["nodes"]:
        client.post(f"/v1/nodes/{n['id']}/review", json={"status": "confirmed"})
    before = client.post(
        "/v1/search", json={"query": "Atlas", "as_of": "2026-09-30T23:59:59Z"}
    ).json()
    at_change = client.post(
        "/v1/search", json={"query": "Atlas", "as_of": "2026-10-01T00:00:00Z"}
    ).json()
    assert before["items"][0]["summary"] == "Projekt Atlas vede Petr."
    assert len(before["items"]) == 1
    assert at_change["items"][0]["summary"] == "Projekt Atlas vede Jana."
    assert len(at_change["items"]) == 1


def test_delete_removes_evidence_but_keeps_other_conversation(client):
    ids = []
    for i in range(2):
        ids.append(
            client.post("/v1/episodes", json=message(str(i), f"chat-{i}")).json()["episode_id"]
        )
        drain(client)
    assert client.delete(f"/v1/episodes/{ids[0]}").status_code == 200
    assert client.get(f"/v1/episodes/{ids[0]}").status_code == 404
    assert client.post("/v1/episodes", json=message("0", "chat-0")).status_code == 409
    for n in client.get("/v1/map").json()["nodes"]:
        assert n["strength"] == 1
        assert {e["episode_id"] for e in n["evidence"]} == {ids[1]}
    assert client.delete(f"/v1/episodes/{ids[1]}").status_code == 200
    assert client.get("/v1/map").json()["nodes"] == []


def test_graph_and_queue_survive_restart(app, client):
    client.post("/v1/episodes", json=message())
    service = app.state.memory
    restarted = create_app(service.settings)
    from conftest import OWNER_KEY
    from fastapi.testclient import TestClient

    with TestClient(restarted, headers={"Authorization": f"Bearer {OWNER_KEY}"}) as new_client:
        assert new_client.get("/v1/jobs").json()["jobs"][0]["status"] == "pending"
        drain(new_client)
        assert len(new_client.get("/v1/map").json()["nodes"]) == 2
    # A fresh service reloads a persisted graph, not only in-memory state.
    assert len(create_app(service.settings).state.memory.state["nodes"]) == 2


def test_failed_job_retry_does_not_lose_source(client, monkeypatch):
    episode = client.post("/v1/episodes", json=message()).json()["episode_id"]
    service = client.app.state.memory
    original = service.graph.save

    def failure(state):
        raise RuntimeError("sensitive text must not appear in error record")

    monkeypatch.setattr(service.graph, "save", failure)
    for _ in range(3):
        drain(client)
        with service.journal.db() as db:
            db.execute("UPDATE jobs SET available=0")
    job = client.get("/v1/jobs").json()["jobs"][0]
    assert job["status"] == "failed" and job["error"] == "RuntimeError"
    assert "sensitive" not in json.dumps(job)
    assert client.get(f"/v1/episodes/{episode}").status_code == 200
    monkeypatch.setattr(service.graph, "save", original)
    assert client.post(f"/v1/jobs/{episode}/retry").status_code == 200
    drain(client)
    assert client.get("/v1/jobs").json()["jobs"][0]["status"] == "done"


def test_rejected_nodes_stay_out_of_context_and_unknown_links_fail(client):
    episode = client.post("/v1/episodes", json=message()).json()["episode_id"]
    drain(client)
    goal = next(n for n in client.get("/v1/map").json()["nodes"] if n["kind"] == "Goal")
    client.post(f"/v1/nodes/{goal['id']}/review", json={"status": "rejected"})
    assert (
        client.post("/v1/search", json={"query": "paměť", "include_candidates": True}).json()[
            "items"
        ]
        == []
    )
    assert (
        client.post(
            "/v1/links",
            json={
                "source_id": goal["id"],
                "target_id": "missing",
                "relation": "SUPPORTS",
                "episode_id": episode,
                "quote": "Chci",
            },
        ).status_code
        == 404
    )


def test_data_directory_cannot_change_owner(app):
    import pytest

    settings = Settings(
        _env_file=None,
        **{**app.state.memory.settings.model_dump(), "scope": "personal:another-owner"},
    )
    with pytest.raises(ValueError, match="different memory scope"):
        create_app(settings)


def test_raw_content_and_quotes_preserve_whitespace(client):
    content = "  První řádek.\n\n  Druhý řádek.  \n"
    payload = message(
        content=content,
        extraction={
            "items": [
                {"kind": "Thought", "label": "Řádky", "summary": "Dva řádky.", "quote": content}
            ]
        },
    )
    source = client.post("/v1/episodes", json=payload)
    assert source.status_code == 202
    episode_id = source.json()["episode_id"]
    assert client.get(f"/v1/episodes/{episode_id}").json()["content"] == content
    drain(client)
    assert client.get("/v1/map").json()["nodes"][0]["evidence"][0]["quote"] == content
