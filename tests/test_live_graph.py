"""Opt-in integration tests; ordinary test runs never call a paid model."""

import os
import time
from uuid import uuid4

import pytest
from conftest import OWNER_KEY, message
from fastapi.testclient import TestClient

from active_memory.api import create_app
from active_memory.settings import Settings


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("MEMORY_TEST_NEO4J") != "true", reason="live Neo4j opt-in")
def test_native_neo4j_roundtrip(tmp_path):
    scope = "personal:test-" + uuid4().hex
    settings = Settings(
        _env_file=None,
        backend="neo4j",
        scope=scope,
        data_dir=tmp_path,
        clients_file=tmp_path / "no-clients.json",
        api_key=OWNER_KEY,
        neo4j_uri=os.environ.get("MEMORY_TEST_NEO4J_URI", "bolt://localhost:7687"),
        neo4j_password=os.environ["MEMORY_TEST_NEO4J_PASSWORD"],
        worker_enabled=False,
    )
    app = create_app(settings)
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {OWNER_KEY}"}) as client:
            source = client.post("/v1/episodes", json=message()).json()["episode_id"]
            client.portal.call(app.state.memory.process_one)
            state = app.state.memory.graph.load()
            assert len(state["nodes"]) == 2 and len(state["edges"]) == 1
            for node in state["nodes"].values():
                assert node["evidence"][0]["episode_id"] == source
            assert client.delete(f"/v1/episodes/{source}").status_code == 200
            assert app.state.memory.graph.load()["nodes"] == {}
    finally:
        # The adapter has closed; a fresh scoped adapter can clean up a failed assertion too.
        from active_memory.graph import Neo4jGraph

        graph = Neo4jGraph(settings)
        graph.save({"scope": scope, "nodes": {}, "edges": {}})
        graph.close()


@pytest.mark.integration
@pytest.mark.skipif(os.environ.get("MEMORY_TEST_GRAPHITI") != "true", reason="paid model opt-in")
def test_graphiti_live_provenance_search_and_delete(tmp_path):
    settings = Settings(
        _env_file=None,
        backend="neo4j",
        scope="personal:test-" + uuid4().hex,
        data_dir=tmp_path,
        clients_file=tmp_path / "none.json",
        api_key=OWNER_KEY,
        neo4j_uri=os.environ.get("MEMORY_TEST_NEO4J_URI", "bolt://localhost:7687"),
        neo4j_password=os.environ["MEMORY_TEST_NEO4J_PASSWORD"],
        graphiti_enabled=True,
        allow_model_calls=True,
        model_api_key=os.environ["MEMORY_TEST_MODEL_KEY"],
        embedding_api_key=os.environ["MEMORY_TEST_EMBEDDING_KEY"],
        model_base_url=os.environ.get("MEMORY_TEST_MODEL_URL", "https://api.openai.com/v1"),
        embedding_base_url=os.environ.get("MEMORY_TEST_EMBEDDING_URL", "https://api.openai.com/v1"),
    )
    app = create_app(settings)
    with TestClient(app, headers={"Authorization": f"Bearer {OWNER_KEY}"}) as client:
        source = client.post(
            "/v1/episodes", json=message(content="Jana vede projekt Atlas.", extraction=None)
        ).json()["episode_id"]
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = client.get("/v1/jobs").json()["jobs"][0]
            if job["status"] in {"done", "failed"}:
                break
            time.sleep(0.2)
        assert job["status"] == "done", job
        results = client.post(
            "/v1/search", json={"query": "Kdo vede projekt Atlas?", "include_candidates": True}
        )
        assert results.status_code == 200
        facts = results.json()["inferred_facts"]
        assert facts and any(source in f["episode_ids"] for f in facts)
        assert client.delete(f"/v1/episodes/{source}").status_code == 200
        assert client.get(f"/v1/episodes/{source}").status_code == 404
        assert (
            client.post("/v1/search", json={"query": "Atlas", "include_candidates": True}).json()[
                "inferred_facts"
            ]
            == []
        )
