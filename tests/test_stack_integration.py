"""End-to-end stack tests: ingest -> done job -> source UUID -> search -> restart -> delete/rebuild.

Opt-in only; the ordinary suite stays local and never calls a model.

* ``MEMORY_TEST_DOCKER=true``           Docker Compose stack (API image + Neo4j), no model, no cost.
* ``MEMORY_TEST_DOCKER_GRAPHITI=true``  same stack with Graphiti 0.30.2; needs the model and
  embedding keys below and sends a handful of synthetic sentences to that provider.
* ``MEMORY_TEST_STACK_URI``             Docker-less variant: an already running Neo4j is used and
  the API is started as a local subprocess (keyless; developers without Docker).

Model settings: MEMORY_TEST_MODEL_KEY, MEMORY_TEST_EMBEDDING_KEY and optionally
MEMORY_TEST_MODEL_URL, MEMORY_TEST_EMBEDDING_URL, MEMORY_TEST_MODEL_NAME,
MEMORY_TEST_EMBEDDING_MODEL, MEMORY_TEST_EMBEDDING_DIM.
"""

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
DOCKER = os.environ.get("MEMORY_TEST_DOCKER") == "true"
DOCKER_GRAPHITI = os.environ.get("MEMORY_TEST_DOCKER_GRAPHITI") == "true"
LOCAL_URI = os.environ.get("MEMORY_TEST_STACK_URI")
pytestmark = pytest.mark.integration

FOREIGN_GROUP = "am_foreign_group_must_survive"
FIRST = "Jana vede projekt Atlas a projekt Atlas používá graf Neo4j."
SECOND = "Projekt Atlas dodá tým z Brna do konce roku."


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def provided(kind, label, summary, quote, themes):
    return {
        "items": [
            {
                "kind": kind,
                "label": label,
                "summary": summary,
                "quote": quote,
                "themes": themes,
                "confidence": 0.8,
            }
        ]
    }


def episode(message_id, conversation, content, extraction=None, role="user"):
    return {
        "source_system": "stack-test",
        "conversation_id": conversation,
        "message_id": message_id,
        "role": role,
        "content": content,
        "occurred_at": "2026-10-01T10:00:00Z",
        "extraction": extraction,
    }


class Stack:
    """A running API with its Neo4j. Subclasses only differ in how they start and restart."""

    graphiti = False

    def __init__(self, workdir, graphiti):
        self.graphiti = graphiti
        self.workdir = workdir
        self.owner_key = secrets.token_urlsafe(32)
        self.neo4j_password = secrets.token_urlsafe(18)
        self.scope = "personal:stack-" + uuid4().hex[:12]
        self.group_id = "am_" + hashlib.sha256(self.scope.encode()).hexdigest()[:32]
        self.api_port = free_port()
        self.clients = workdir / "clients.json"
        self.clients.write_text(
            json.dumps(
                [
                    {
                        "id": "owner",
                        "key_sha256": hashlib.sha256(self.owner_key.encode()).hexdigest(),
                        "permissions": ["read", "write", "admin"],
                    }
                ]
            )
        )

    def memory_env(self):
        env = {
            "MEMORY_SCOPE": self.scope,
            "MEMORY_BACKEND": "neo4j",
            "MEMORY_NEO4J_PASSWORD": self.neo4j_password,
            "MEMORY_WORKER_ENABLED": "true",
            "MEMORY_EXTRACTION_MODE": "provided",
            "GRAPHITI_TELEMETRY_ENABLED": "false",
        }
        if self.graphiti:
            env |= {
                "MEMORY_ALLOW_MODEL_CALLS": "true",
                "MEMORY_GRAPHITI_ENABLED": "true",
                "MEMORY_MODEL_API_KEY": os.environ["MEMORY_TEST_MODEL_KEY"],
                "MEMORY_EMBEDDING_API_KEY": os.environ["MEMORY_TEST_EMBEDDING_KEY"],
            }
            for source, target in {
                "MEMORY_TEST_MODEL_URL": "MEMORY_MODEL_BASE_URL",
                "MEMORY_TEST_EMBEDDING_URL": "MEMORY_EMBEDDING_BASE_URL",
                "MEMORY_TEST_MODEL_NAME": "MEMORY_MODEL_NAME",
                "MEMORY_TEST_EMBEDDING_MODEL": "MEMORY_EMBEDDING_MODEL",
                "MEMORY_TEST_EMBEDDING_DIM": "MEMORY_EMBEDDING_DIM",
            }.items():
                if os.environ.get(source):
                    env[target] = os.environ[source]
        return env

    # -- API helpers ---------------------------------------------------------------------
    @property
    def base(self):
        return f"http://127.0.0.1:{self.api_port}"

    def api(self):
        return httpx.Client(
            base_url=self.base,
            headers={"Authorization": f"Bearer {self.owner_key}"},
            timeout=300,
        )

    def wait_ready(self, seconds=300):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if httpx.get(self.base + "/readyz", timeout=5).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
        raise AssertionError("API did not become ready")

    def wait_jobs(self, ids, seconds=600):
        deadline = time.monotonic() + seconds
        with self.api() as client:
            while time.monotonic() < deadline:
                jobs = {j["episode_id"]: j for j in client.get("/v1/jobs").json()["jobs"]}
                states = {i: jobs.get(i, {}).get("status") for i in ids}
                assert "failed" not in states.values(), jobs  # class name only, no content
                if all(s == "done" for s in states.values()):
                    return
                time.sleep(1)
        raise AssertionError(f"jobs not done: {states}")

    # -- Neo4j helper --------------------------------------------------------------------
    def cypher(self, query, **params):
        driver = GraphDatabase.driver(self.bolt, auth=("neo4j", self.neo4j_password))
        try:
            with driver.session() as session:
                return [r.data() for r in session.run(query, **params)]
        finally:
            driver.close()

    def start(self):
        raise NotImplementedError

    def restart_api(self):
        raise NotImplementedError

    def restart_all(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class ComposeStack(Stack):
    def __init__(self, workdir, graphiti):
        super().__init__(workdir, graphiti)
        self.project = "amtest" + uuid4().hex[:8]
        self.bolt_port = free_port()
        self.bolt = f"bolt://127.0.0.1:{self.bolt_port}"
        env_file = workdir / "memory.env"
        env_file.write_text("".join(f"{k}={v}\n" for k, v in self.memory_env().items()))
        env_file.chmod(0o600)
        override = workdir / "compose.override.yaml"
        override.write_text(
            f"""services:
  memory:
    env_file: !override ["{env_file.as_posix()}"]
    ports: !override ["127.0.0.1:{self.api_port}:8080"]
    volumes:
      - {self.clients.as_posix()}:/app/config/clients.json:ro
  neo4j:
    ports: ["127.0.0.1:{self.bolt_port}:7687"]
"""
        )
        self.base_cmd = [
            "docker",
            "compose",
            "--project-directory",
            str(ROOT),
            "-p",
            self.project,
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(ROOT / "compose.graph.yaml"),
            "-f",
            str(override),
        ]
        self.env = os.environ | {"MEMORY_NEO4J_PASSWORD": self.neo4j_password}

    def run(self, *args, check=True):
        return subprocess.run(
            [*self.base_cmd, *args], env=self.env, check=check, capture_output=True, text=True
        )

    def start(self):
        self.run("up", "-d", "--build", "--wait", "--wait-timeout", "600")
        self.wait_ready()

    def restart_api(self):
        self.run("restart", "memory")
        self.wait_ready()

    def restart_all(self):
        # Containers are removed, named volumes are kept: this proves persisted state only.
        self.run("down")
        self.run("up", "-d", "--wait", "--wait-timeout", "600")
        self.wait_ready()

    def logs_tail(self):
        return self.run("logs", "--tail", "40", "memory", check=False).stdout

    def stop(self):
        self.run("down", "-v", "--remove-orphans", check=False)


class ProcessStack(Stack):
    """Docker-less: the API is a local subprocess; Neo4j is whatever MEMORY_TEST_STACK_URI names."""

    def __init__(self, workdir, graphiti):
        super().__init__(workdir, graphiti)
        self.bolt = LOCAL_URI
        self.neo4j_password = os.environ["MEMORY_TEST_NEO4J_PASSWORD"]
        self.process = None

    def start(self):
        env = os.environ | self.memory_env()
        env |= {
            "MEMORY_NEO4J_URI": self.bolt,
            "MEMORY_NEO4J_PASSWORD": self.neo4j_password,
            "MEMORY_DATA_DIR": str(self.workdir / "data"),
            "MEMORY_CLIENTS_FILE": str(self.clients),
            "MEMORY_HOST": "127.0.0.1",
            "MEMORY_PORT": str(self.api_port),
        }
        self.env = env
        self.process = subprocess.Popen(
            [sys.executable, "-m", "active_memory.cli", "serve"],
            env=env,
            cwd=self.workdir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.wait_ready(60)

    def restart_api(self):
        self.process.terminate()
        self.process.wait(30)
        self.start()

    restart_all = restart_api

    def logs_tail(self):
        return ""

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(30)
        try:
            self.cypher("MATCH (n {scope:$s}) DETACH DELETE n", s=self.scope)
        except Exception:
            pass


def _stack(tmp_path, graphiti):
    if LOCAL_URI and not graphiti:
        return ProcessStack(tmp_path, graphiti)
    if shutil.which("docker") is None:
        pytest.fail("docker is required for the Compose stack test")
    return ComposeStack(tmp_path, graphiti)


def scenario(stack):
    """Shared checks; Graphiti-only assertions are guarded by ``stack.graphiti``."""
    try:
        stack.start()
        with stack.api() as client:
            first = client.post(
                "/v1/episodes",
                json=episode(
                    "1",
                    "chat-it",
                    FIRST,
                    provided(
                        "Fact",
                        "Atlas vede Jana",
                        "Jana vede projekt Atlas.",
                        "Jana vede projekt Atlas",
                        ["Projekt Atlas"],
                    ),
                ),
            ).json()["episode_id"]
            second = client.post(
                "/v1/episodes",
                json=episode(
                    "2",
                    "chat-work",
                    SECOND,
                    provided(
                        "Goal",
                        "Dodání Atlasu",
                        "Tým z Brna dodá projekt Atlas.",
                        "Projekt Atlas dodá tým z Brna",
                        ["Projekt Atlas"],
                    ),
                ),
            ).json()["episode_id"]
            # An assistant turn is raw provenance only: never extracted, never sent to Graphiti.
            assistant = client.post(
                "/v1/episodes",
                json=episode("3", "chat-it", "Doporučuji verzovat graf.", role="assistant"),
            ).json()["episode_id"]
        stack.wait_jobs([first, second, assistant])

        # Source UUID provenance in the native active map.
        with stack.api() as client:
            nodes = client.get("/v1/map").json()["nodes"]
            theme = next(n for n in nodes if n["kind"] == "Theme")
            assert {e["episode_id"] for e in theme["evidence"]} == {first, second}
            assert theme["conversation_count"] == 2
            assert client.get(f"/v1/episodes/{first}").json()["content"] == FIRST
        native = stack.cypher("MATCH (n:AMNode {scope:$s}) RETURN count(n) AS c", s=stack.scope)[0][
            "c"
        ]
        assert native >= 3

        if stack.graphiti:
            # Graphiti stores the same UUID as its Episodic node (users only, not the assistant).
            rows = stack.cypher(
                "MATCH (e:Episodic {group_id:$g}) RETURN e.uuid AS u", g=stack.group_id
            )
            assert {r["u"] for r in rows} == {first, second}
            stack.cypher(
                "CREATE (:Episodic {uuid:$u,group_id:$g,name:'foreign',content:$c,"
                "source_description:'foreign',created_at:datetime(),valid_at:datetime()})",
                u="foreign-" + uuid4().hex,
                g=FOREIGN_GROUP,
                c=FIRST,
            )

        def search():
            with stack.api() as client:
                response = client.post(
                    "/v1/search",
                    json={"query": "Kdo vede projekt Atlas?", "include_candidates": True},
                )
                assert response.status_code == 200, response.text
                return response.json()

        before = search()
        assert any(first in n["evidence"][0]["episode_id"] for n in before["items"])
        if stack.graphiti:
            facts = before["inferred_facts"]
            assert facts, "scoped hybrid search returned no facts"
            for fact in facts:
                assert fact["status"] == "candidate"
                assert set(fact["episode_ids"]) <= {first, second}
            assert any(first in f["episode_ids"] for f in facts)

        # Restart the API only, then the whole stack: state must come from persistent storage.
        for restart in (stack.restart_api, stack.restart_all):
            restart()
            with stack.api() as client:
                jobs = {j["episode_id"]: j["status"] for j in client.get("/v1/jobs").json()["jobs"]}
                assert set(jobs.values()) == {"done"}
                assert client.get(f"/v1/episodes/{first}").status_code == 200
            after = search()
            assert {n["id"] for n in after["items"]} == {n["id"] for n in before["items"]}
            if stack.graphiti:
                assert after["inferred_facts"], "facts lost after restart"

        # Deletion (and, with Graphiti, projection rebuild from the surviving source only).
        with stack.api() as client:
            assert client.delete(f"/v1/episodes/{first}").status_code == 200
            assert client.get(f"/v1/episodes/{first}").status_code == 404
            nodes = client.get("/v1/map").json()["nodes"]
            for node in nodes:
                assert first not in {e["episode_id"] for e in node["evidence"]}
            assert any(second in {e["episode_id"] for e in n["evidence"]} for n in nodes)
            export = client.get("/v1/export").json()
            assert first not in {e["episode_id"] for e in export["episodes"]}
        assert (
            stack.cypher(
                "MATCH (n:AMNode {scope:$s}) WHERE n.payload CONTAINS $u RETURN count(n) AS c",
                s=stack.scope,
                u=first,
            )[0]["c"]
            == 0
        )
        if stack.graphiti:
            rows = stack.cypher(
                "MATCH (e:Episodic {group_id:$g}) RETURN e.uuid AS u", g=stack.group_id
            )
            assert {r["u"] for r in rows} == {second}
            assert (
                stack.cypher(
                    "MATCH (e:Episodic {group_id:$g}) RETURN count(e) AS c", g=FOREIGN_GROUP
                )[0]["c"]
                == 1
            ), "rebuild touched another group"
            # Nothing derived from the erased source may remain in this group's text fields.
            leaked = stack.cypher(
                "MATCH (n {group_id:$g}) WHERE any(v IN [n.content,n.summary,n.fact] "
                "WHERE v IS NOT NULL AND v CONTAINS 'Jana') RETURN count(n) AS c",
                g=stack.group_id,
            )[0]["c"]
            assert leaked == 0, "derived graph text still mentions erased source"
            for fact in search()["inferred_facts"]:
                assert first not in fact["episode_ids"]
    except Exception:
        tail = stack.logs_tail()
        if tail:
            print(tail[-4000:])  # service logs never contain message bodies by design
        raise
    finally:
        if stack.graphiti:
            try:
                stack.cypher("MATCH (n {group_id:$g}) DETACH DELETE n", g=FOREIGN_GROUP)
            except Exception:
                pass
        stack.stop()


@pytest.mark.skipif(not (DOCKER or LOCAL_URI), reason="stack opt-in: MEMORY_TEST_DOCKER or URI")
def test_stack_native_graph_without_models(tmp_path):
    scenario(_stack(tmp_path, graphiti=False))


@pytest.mark.skipif(not DOCKER_GRAPHITI, reason="paid model opt-in: MEMORY_TEST_DOCKER_GRAPHITI")
def test_stack_graphiti_provenance_search_restart_delete(tmp_path):
    for name in ("MEMORY_TEST_MODEL_KEY", "MEMORY_TEST_EMBEDDING_KEY"):
        assert os.environ.get(name), f"{name} is required"
    scenario(_stack(tmp_path, graphiti=True))
