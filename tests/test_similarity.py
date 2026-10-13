"""AM-003: proposals are sourced candidates; nothing merges, confirms or revives on its own."""

import pytest
from conftest import OWNER_KEY, READER_KEY, drain, message
from fastapi.testclient import TestClient

from active_memory.engine import public_node, search
from active_memory.models import Query
from active_memory.similarity import clusters, lexical_similarity

CONTROL_A = ("Chci zachovat lidskou kontrolu nad výsledkem.", "zachovat lidskou kontrolu")
CONTROL_B = (
    "Důležitá je lidská kontrola nad každým výsledkem.",
    "lidská kontrola nad každým výsledkem",
)


def say(client, mid, chat, content, quote, kind="Thought", label=None, themes=(), **extra):
    payload = message(
        message_id=mid,
        conversation=chat,
        content=content,
        extraction={
            "items": [
                {
                    "kind": kind,
                    "label": label or quote,
                    "summary": content,
                    "quote": quote,
                    "themes": list(themes),
                    **extra,
                }
            ]
        },
    )
    episode = client.post("/v1/episodes", json=payload).json()["episode_id"]
    drain(client)
    return episode


def propose(client):
    return client.portal.call(client.app.state.memory.propose_links, "owner")


def links(client, **params):
    return client.get("/v1/links", params=params).json()["links"]


@pytest.fixture
def twins(client):
    return (
        say(client, "1", "chat-a", *CONTROL_A),
        say(client, "2", "chat-b", *CONTROL_B),
    )


def test_cross_chat_near_duplicates_become_sourced_candidate_alias(client, twins):
    report = propose(client)
    assert report["proposed"] == 1 and report["mode"] == "lexical"
    (edge,) = links(client)
    assert edge["relation"] == "ALIAS_OF" and edge["status"] == "candidate"
    assert edge["origin"] == "proposal" and edge["proposal"]["method"] == "similarity"
    assert {e["episode_id"] for e in edge["evidence"]} == set(twins)
    assert edge["proposal"]["signals"]["lexical"] > 0 and edge["proposal"]["reason"]
    for item in edge["evidence"]:
        assert client.get(f"/v1/episodes/{item['episode_id']}").json()["content"]
    graph = client.get("/v1/map").json()
    assert graph["total_nodes"] == 2  # nothing merged
    assert graph["clusters"] == []  # candidates do not cluster


def test_same_chat_repetition_is_not_proposed(client):
    say(client, "1", "chat-a", *CONTROL_A)
    say(client, "2", "chat-a", *CONTROL_B)
    assert propose(client)["proposed"] == 0


def test_proposals_are_idempotent_and_hidden_from_default_context(client, twins):
    propose(client)
    assert propose(client)["proposed"] == 0
    assert len(links(client)) == 1
    context = client.post("/v1/context", json={"query": "lidská kontrola"}).json()
    assert context["items"] == []  # candidates excluded by default
    found = client.post(
        "/v1/search", json={"query": "lidská kontrola", "include_candidates": True}
    ).json()["items"]
    assert found and all("embedding" not in n for n in found)


def test_temporal_supersession_uses_adjacent_validity_windows(client):
    say(
        client,
        "1",
        "chat-a",
        "Rozhodl jsem se použít PostgreSQL.",
        "použít PostgreSQL",
        kind="Decision",
        label="PostgreSQL",
        themes=["Volba databáze"],
        valid_from="2026-06-01T00:00:00Z",
        valid_to="2026-10-01T00:00:00Z",
    )
    say(
        client,
        "2",
        "chat-b",
        "Přecházím na Neo4j od října.",
        "Přecházím na Neo4j",
        kind="Decision",
        label="Neo4j",
        themes=["Volba databáze"],
        valid_from="2026-10-01T00:00:00Z",
    )
    propose(client)
    edges = [e for e in links(client) if e["relation"] == "SUPERSEDES"]
    assert len(edges) == 1
    edge = edges[0]
    assert edge["source"]["label"] == "Neo4j" and edge["target"]["label"] == "PostgreSQL"
    assert edge["status"] == "candidate" and edge["proposal"]["method"] == "temporal"
    nodes = client.get("/v1/map").json()["nodes"]
    old = next(n for n in nodes if n["label"] == "PostgreSQL")
    assert old["valid_to"] == "2026-10-01T00:00:00Z" and old["status"] == "candidate"


def test_adjacent_decisions_without_shared_theme_are_not_linked(client):
    say(
        client,
        "1",
        "chat-a",
        "Rozhodl jsem se použít PostgreSQL.",
        "použít PostgreSQL",
        kind="Decision",
        label="PostgreSQL",
        themes=["Volba databáze"],
        valid_from="2026-06-01T00:00:00Z",
        valid_to="2026-10-01T00:00:00Z",
    )
    say(
        client,
        "2",
        "chat-b",
        "Od října běhám ráno.",
        "běhám ráno",
        kind="Decision",
        label="Ranní běh",
        themes=["Běhání"],
        valid_from="2026-10-01T00:00:00Z",
    )
    assert propose(client)["proposed"] == 0


class FakeEmbedder:
    """Concept-aware stand-in: paraphrases AND opposites are close, exactly the hard case."""

    model = "fake-embedding"
    usage = {"calls": 0, "texts": 0, "tokens": 0}
    table = {
        "kontrola": [1.0, 0.0, 0.0],
        "poslední slovo": [0.97, 0.2, 0.0],
        "schvalovat automaticky": [0.9, 0.43, 0.0],
        "běhání": [0.0, 0.0, 1.0],
    }

    async def embed(self, texts):
        self.usage["calls"] += 1
        return [
            next((v for k, v in self.table.items() if text.lower().startswith(k)), [0.3, 0.3, 0.3])
            for text in texts
        ]


class FakeJudge:
    def __init__(self):
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}

    async def judge(self, a, b, evidence_a, evidence_b):
        self.usage["calls"] += 1
        labels = {a["label"], b["label"]}
        assert evidence_a and evidence_b  # the judge always sees the quoted sources
        if labels == {"kontrola", "poslední slovo"}:
            return {"relation": "SAME", "direction": "a_to_b", "reason": "same idea, other words"}
        if "schvalovat automaticky" in labels:
            return {"relation": "CONTRADICTS", "direction": "a_to_b", "reason": "opposite stance"}
        return {"relation": "UNRELATED", "direction": "a_to_b", "reason": "unrelated"}


@pytest.fixture
def stances(client):
    say(
        client,
        "1",
        "chat-a",
        "Potřebuju kontrola nad výsledkem.",
        "kontrola nad výsledkem",
        label="kontrola",
    )
    say(
        client,
        "2",
        "chat-b",
        "Poslední slovo musí mít člověk.",
        "Poslední slovo musí mít člověk",
        label="poslední slovo",
    )
    say(
        client,
        "3",
        "chat-c",
        "Chci schvalovat automaticky, ruční kontrola zdržuje.",
        "schvalovat automaticky",
        label="schvalovat automaticky",
    )
    say(client, "4", "chat-d", "Běhání mě baví.", "Běhání mě baví", label="běhání")
    return client.app.state.memory


def test_embeddings_without_judge_propose_unjudged_aliases_including_hard_negatives(
    client, stances
):
    memory = stances
    memory.embedder = FakeEmbedder()
    report = propose(client)
    rows = links(client)
    pairs = {frozenset((e["source"]["label"], e["target"]["label"])) for e in rows}
    assert report["proposed"] == 3 and len(pairs) == 3
    assert not any("běhání" in p for p in pairs)
    assert all(e["relation"] == "ALIAS_OF" and e["status"] == "candidate" for e in rows)
    assert all("could also be a CONTRADICTS" in e["proposal"]["reason"] for e in rows)
    # Vectors are cached on nodes for reuse but never returned to clients.
    assert all("embedding" in n for n in memory.state["nodes"].values())
    assert all("embedding" not in n for n in client.get("/v1/map").json()["nodes"])
    exported = client.get("/v1/export").json()["active_graph"]["nodes"].values()
    assert all("embedding" not in n for n in exported)


def test_judge_separates_paraphrase_from_contradiction_and_stays_candidate(client, stances):
    memory = stances
    memory.embedder, memory.judge = FakeEmbedder(), FakeJudge()
    report = propose(client)
    by_relation = {}
    for e in links(client):
        by_relation.setdefault(e["relation"], []).append(
            {e["source"]["label"], e["target"]["label"]}
        )
    assert by_relation.keys() == {"ALIAS_OF", "CONTRADICTS"}
    assert {"kontrola", "poslední slovo"} in by_relation["ALIAS_OF"]
    assert all("schvalovat automaticky" in pair for pair in by_relation["CONTRADICTS"])
    assert report["mode"] == "lexical+judge"
    assert all(
        e["status"] == "candidate" and e["proposal"]["method"] == "judge" for e in links(client)
    )


def test_judge_budget_limits_calls(client, stances):
    memory = stances
    memory.embedder, memory.judge = FakeEmbedder(), FakeJudge()
    memory.settings = memory.settings.model_copy(update={"max_judge_calls": 1})
    report = propose(client)
    assert memory.judge.usage["calls"] == 1 and report["skipped"]["unjudged"] >= 1


def test_rejected_proposal_is_never_revived_even_after_source_erasure(client):
    for mid, chat, text in (("1", "chat-a", CONTROL_A), ("2", "chat-b", CONTROL_B)):
        say(client, mid, chat, *text)
        say(client, mid + "b", chat, *text)  # second source so the idea survives an erasure
    propose(client)
    (edge,) = links(client)
    review = client.post(f"/v1/links/{edge['id']}/review", json={"status": "rejected"})
    assert review.status_code == 200
    assert propose(client)["proposed"] == 0
    assert links(client, status="rejected")[0]["id"] == edge["id"]
    for cited in [e["episode_id"] for e in edge["evidence"]]:
        assert client.delete(f"/v1/episodes/{cited}").status_code == 200
    memory = client.app.state.memory
    (tomb,) = [e for e in memory.state["edges"].values() if e["relation"] == "ALIAS_OF"]
    assert tomb["status"] == "rejected" and tomb["evidence"] == []  # no content kept
    assert "proposal" not in tomb and len(memory.state["nodes"]) == 2
    assert propose(client)["proposed"] == 0
    assert [e["status"] for e in memory.state["edges"].values() if e["relation"] == "ALIAS_OF"] == [
        "rejected"
    ]


def test_erasing_a_cited_source_removes_unreviewed_and_confirmed_proposals(client, twins):
    propose(client)
    (edge,) = links(client)
    client.post(f"/v1/links/{edge['id']}/review", json={"status": "confirmed"})
    assert client.delete(f"/v1/episodes/{twins[1]}").status_code == 200
    assert links(client) == []
    assert client.app.state.memory.state["nodes"]  # the surviving idea keeps its own source


def test_confirmed_alias_clusters_without_merging_and_extends_search(client):
    say(
        client,
        "1",
        "chat-a",
        "Lidská kontrola je pro mě základ.",
        "Lidská kontrola",
        kind="Theme",
        label="Lidská kontrola",
    )
    say(
        client,
        "2",
        "chat-b",
        "Poslední slovo musí mít člověk.",
        "Poslední slovo",
        kind="Theme",
        label="Poslední slovo člověka",
    )
    memory = client.app.state.memory
    a, b = sorted(memory.state["nodes"].values(), key=lambda n: n["label"])
    for node in (a, b):
        client.post(f"/v1/nodes/{node['id']}/review", json={"status": "confirmed"})
    link = client.post(
        "/v1/links",
        json={
            "source_id": a["id"],
            "target_id": b["id"],
            "relation": "ALIAS_OF",
            "episode_id": a["evidence"][0]["episode_id"],
            "quote": "Lidská kontrola",
        },
    ).json()
    request = Query(query="poslední slovo")
    assert {n["label"] for n in search(memory.state, request)} == {"Poslední slovo člověka"}
    assert clusters(memory.state) == []
    client.post(f"/v1/links/{link['id']}/review", json={"status": "confirmed"})
    assert {n["label"] for n in search(memory.state, request)} == {
        "Lidská kontrola",
        "Poslední slovo člověka",
    }
    (cluster,) = clusters(memory.state)
    assert cluster["conversation_count"] == 2 and cluster["strength"] == 2
    assert len(memory.state["nodes"]) == 2  # still two nodes with their own evidence
    client.post(f"/v1/links/{link['id']}/review", json={"status": "rejected"})
    assert clusters(memory.state) == []  # reversible


def test_propose_endpoint_needs_admin_and_links_need_read(app):
    reader = {"Authorization": f"Bearer {READER_KEY}"}
    owner = {"Authorization": f"Bearer {OWNER_KEY}"}
    with TestClient(app) as anon:
        assert anon.post("/v1/maintenance/propose").status_code == 401
        assert anon.post("/v1/maintenance/propose", headers=reader).status_code == 403
        assert anon.get("/v1/links", headers=reader).status_code == 200
        assert anon.post("/v1/maintenance/propose", headers=owner).status_code == 200


def test_auto_propose_after_ingest_and_provider_failure_does_not_fail_the_job(app):
    memory = app.state.memory
    memory.settings = memory.settings.model_copy(update={"auto_propose": True})
    with TestClient(app, headers={"Authorization": f"Bearer {OWNER_KEY}"}) as client:
        say(client, "1", "chat-a", *CONTROL_A)
        say(client, "2", "chat-b", *CONTROL_B)
        assert len(links(client)) == 1

        class Broken:
            model = "x"
            usage = {}

            async def embed(self, texts):
                raise RuntimeError("provider body with private text")

        memory.embedder = Broken()
        episode = say(client, "3", "chat-c", "Něco jiného úplně.", "Něco jiného úplně")
        jobs = {j["episode_id"]: j for j in client.get("/v1/jobs").json()["jobs"]}
        assert jobs[episode]["status"] == "done"
        with memory.journal.db() as db:
            audit = " ".join(str(tuple(r)) for r in db.execute("SELECT * FROM audit"))
        assert "auto_propose_failed" in audit and "private text" not in audit


def test_lexical_similarity_is_diacritics_and_stopword_insensitive():
    a = {"label": "Lidská kontrola", "summary": "Zachovat lidskou kontrolu"}
    b = {"label": "lidska kontrola", "summary": "chci zachovat lidskou kontrolu"}
    c = {"label": "Běhání", "summary": "Běhání mi pomáhá"}
    assert lexical_similarity(a, b) > 0.8 and lexical_similarity(a, c) == 0


def test_public_node_strips_vectors():
    assert public_node({"id": "x", "embedding": {"vector": [1]}}) == {"id": "x"}


def test_rejected_node_is_not_paired(client, twins):
    memory = client.app.state.memory
    first = next(iter(memory.state["nodes"]))
    client.post(f"/v1/nodes/{first}/review", json={"status": "rejected"})
    assert propose(client)["proposed"] == 0


def test_proposal_event_write_failure_is_repaired_with_the_true_created_events(
    client, twins, monkeypatch
):
    from active_memory.service import AuditGap

    memory = client.app.state.memory

    def created():
        found = client.get("/v1/events", params={"type": "candidate.created", "limit": 200})
        return [e for e in found.json()["events"] if e["subject"]["kind"] == "link"]

    monkeypatch.setattr(memory.journal, "complete", lambda *a: (_ for _ in ()).throw(OSError()))
    with pytest.raises(AuditGap):
        propose(client)
    monkeypatch.undo()
    assert len(links(client)) == 1 and created() == []  # applied to the graph, not yet recorded
    assert memory.recover() == 1
    (event,) = created()
    assert event["data"]["origin"]["kind"] == "similarity"
    assert event["actor"]["kind"] == "system" and event["new_state"] == "candidate"
    propose(client)  # idempotent: no second proposal, no second event
    assert len(created()) == 1
