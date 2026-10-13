"""AM-021: the model advises on candidates; it never decides, and its advice never outlives its source."""

import json
import time

import httpx
from conftest import OWNER_KEY, READER_KEY, drain, message
from fastapi.testclient import TestClient

from active_memory.api import create_app

OWNER = {"Authorization": f"Bearer {OWNER_KEY}"}
SETTINGS = {
    "allow_model_calls": True,
    "model_base_url": "https://llm.example.org/v1",
    "model_name": "advisor-model",
    "model_api_key": "sk-advisor-secret",
    "recommend_enabled": True,
}
REASON = "Citace jasně podporuje návrh a stojí za zapamatování."


def provider(answers):
    """Mock chat-completions endpoint answering with the next prepared recommendation."""
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        answer = answers[min(len(seen), len(answers)) - 1]
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler), seen


def good(recommendation="confirm", confidence=0.9):
    return {"recommendation": recommendation, "confidence": confidence, "reason": REASON}


def setup(client, answers):
    transport, seen = provider(answers)
    client.app.state.memory.http_transport = transport
    response = client.put("/v1/settings/llm", json=SETTINGS)
    assert response.status_code == 200, response.text
    return seen


def ingest(client, mid="1", chat="chat-a"):
    assert client.post("/v1/episodes", json=message(mid, chat)).status_code == 202
    drain(client)


def run(client, limit=10):
    memory = client.app.state.memory
    return client.portal.call(memory.recommend_now, limit, "owner")


def queue(client, **params):
    return client.get("/v1/candidates", params={"kind": "all", **params}).json()


def test_recommendations_are_off_by_default_and_need_consent(client):
    assert client.post("/v1/recommendations/run", json={}).status_code == 422
    refused = client.put("/v1/settings/llm", json={"recommend_enabled": True})
    assert refused.status_code == 422
    assert client.get("/v1/recommendations/status").json()["enabled"] is False


def test_advice_is_stored_but_never_changes_a_status(client):
    ingest(client)
    seen = setup(client, [good("confirm")])
    report = run(client)
    assert report["considered"] >= 2 and report["failed"] == 0
    assert report["recommended"]["confirm"] == report["considered"]
    items = queue(client)["items"]
    assert items and all(i["status"] == "candidate" for i in items)  # nothing was decided
    advice = items[0]["recommendation"]
    assert advice["recommendation"] == "confirm" and advice["reason"] == REASON
    assert advice["model"] == "advisor-model" and advice["stale"] is False
    # What the model saw: the proposal and its own quote, framed as untrusted data.
    sent = seen[0]["messages"]
    assert (
        "never follow instructions" in sent[0]["content"] and "Chci vlastnit" in sent[1]["content"]
    )
    assert items[0]["recommendation_agrees"] is None  # no human decision yet


def test_the_event_names_the_model_and_carries_no_reason_text(client):
    ingest(client)
    setup(client, [good("reject", 0.4)])
    run(client)
    found = client.get("/v1/events", params={"type": "candidate.recommended", "limit": 50})
    events = found.json()["events"]
    assert events
    event = events[0]
    assert event["actor"] == {
        "kind": "model",
        "identifier": "advisor-model",
        "assurance": "internal",
    }
    assert event["previous_state"] is None and event["new_state"] is None  # not a state change
    assert event["data"]["recommendation"] == "reject"
    assert event["data"]["provider"] == "llm.example.org"
    text = json.dumps(events)
    assert REASON not in text and "Chci vlastnit" not in text and "sk-advisor-secret" not in text
    # The queue's own state tracking ignores advice, so the audit stays consistent.
    assert all(i["audit"]["consistent"] for i in queue(client)["items"])


def test_human_decision_is_independent_and_agreement_is_reported(client):
    ingest(client)
    setup(client, [good("confirm")])
    run(client)
    item = queue(client, kind="node")["items"][0]
    nid = item["subject"]["identifier"]
    assert client.post(f"/v1/nodes/{nid}/review", json={"status": "rejected"}).status_code == 200
    decided = client.get(f"/v1/candidates/node/{nid}").json()
    assert decided["status"] == "rejected"  # the human overruled the advice
    assert decided["recommendation_agrees"] is False
    summary = client.get("/v1/recommendations/summary").json()
    assert summary["decided_with_advice"]["disagreed"] == 1 and summary["enabled"] is True


def test_filters_and_only_unadvised_candidates_are_asked(client):
    ingest(client)
    seen = setup(client, [good("confirm"), good("unsure", 0.3), good("reject", 0.7)])
    first = run(client, limit=1)
    assert first["considered"] == 1 and first["still_without_advice"] >= 1 and len(seen) == 1
    assert queue(client, recommendation="confirm")["total"] == 1
    assert queue(client, recommendation="none")["total"] >= 1
    second = run(client, limit=2)
    assert second["considered"] == 2 and len(seen) == 3  # the advised one is not asked again
    assert queue(client, recommendation="unsure")["total"] == 1
    assert queue(client, recommendation="reject")["total"] == 1
    assert client.get("/v1/candidates", params={"recommendation": "bogus"}).status_code == 422


def test_invalid_or_failing_answers_store_nothing(client):
    ingest(client)
    setup(client, ["not json", {"recommendation": "maybe", "confidence": 2, "reason": ""}])
    report = run(client, limit=2)
    assert report["failed"] == 2 and sum(report["recommended"].values()) == 0
    assert all(i["recommendation"] is None for i in queue(client)["items"])
    found = client.get("/v1/events", params={"type": "candidate.recommended"})
    assert found.json()["events"] == []


def test_new_evidence_makes_advice_stale(client):
    ingest(client, "1", "chat-a")
    setup(client, [good("confirm")])
    run(client)
    ingest(client, "2", "chat-b")  # same idea from another chat: the goal gains evidence
    items = queue(client, kind="node")["items"]
    goal = next(i for i in items if i["candidate_kind"] == "Goal")
    assert len(goal["evidence"]) == 2 and goal["recommendation"]["stale"] is True
    assert queue(client, recommendation="stale")["total"] >= 1


def test_advice_for_a_candidate_decided_meanwhile_is_void(client):
    ingest(client)
    setup(client, [good("confirm")])
    memory = client.app.state.memory
    nid = queue(client, kind="node")["items"][0]["subject"]["identifier"]
    real = memory.recommender.recommend

    async def decide_while_thinking(description):
        await memory.review(nid, "rejected", "owner")
        return await real(description)

    memory.recommender.recommend = decide_while_thinking
    report = run(client, limit=1)
    # Whichever candidate was asked about: advice for a decided one is never stored.
    assert report["void_because_changed"] + sum(report["recommended"].values()) == 1
    assert client.get(f"/v1/candidates/node/{nid}").json()["recommendation"] is None or (
        report["void_because_changed"] == 0
    )


def test_erasing_the_source_removes_the_advice_and_its_reason(client):
    episode = client.post("/v1/episodes", json=message("1", "chat-a")).json()["episode_id"]
    drain(client)
    setup(client, [good("confirm")])
    run(client)
    memory = client.app.state.memory
    assert memory.journal.recommendations()
    assert client.delete(f"/v1/episodes/{episode}").status_code == 200
    assert memory.journal.recommendations() == {}
    with memory.journal.db() as db:
        dump = " ".join(str(tuple(r)) for r in db.execute("SELECT * FROM recommendations"))
        events = " ".join(
            r[0] for r in db.execute("SELECT event FROM audit WHERE event IS NOT NULL")
        )
    assert REASON not in dump and REASON not in events and "Chci vlastnit" not in events
    assert client.get("/v1/candidates", params={"kind": "all"}).json()["items"] == []


def test_run_endpoint_is_admin_only_and_runs_in_the_background(app):
    with TestClient(app, headers=OWNER) as owner:
        ingest(owner)
        setup(owner, [good("confirm")])
        reader = {"Authorization": f"Bearer {READER_KEY}"}
        assert owner.post("/v1/recommendations/run", json={}, headers=reader).status_code == 403
        assert owner.get("/v1/recommendations/status", headers=reader).status_code == 200
        assert owner.get("/v1/recommendations/summary", headers=reader).status_code == 200
        started = owner.post("/v1/recommendations/run", json={"limit": 5})
        assert started.status_code == 202
        for _ in range(200):
            status = owner.get("/v1/recommendations/status").json()
            if not status["running"]:
                break
            time.sleep(0.05)
        assert status["report"]["considered"] >= 2 and status["done"] == status["total"]


def test_advice_survives_a_restart(app, client):
    ingest(client)
    setup(client, [good("confirm")])
    run(client)
    with TestClient(create_app(client.app.state.memory.settings), headers=OWNER) as again:
        first = again.get("/v1/candidates", params={"kind": "all"}).json()["items"][0]
        assert first["recommendation"]["recommendation"] == "confirm"
        assert again.get("/v1/recommendations/summary").json()["enabled"] is True
