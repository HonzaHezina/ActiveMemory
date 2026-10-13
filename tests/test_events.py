"""Event contract v1: append-only log, review queue read model and consistency behaviour."""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest
from conftest import OWNER_KEY, READER_KEY, WRITER_KEY, drain, message
from fastapi.testclient import TestClient
from pydantic import ValidationError

from active_memory import events as ev
from active_memory.api import create_app

OWNER = {"Authorization": f"Bearer {OWNER_KEY}"}
READER = {"Authorization": f"Bearer {READER_KEY}"}
WRITER = {"Authorization": f"Bearer {WRITER_KEY}"}
QUOTE = "Chci vlastnit svoji AI paměť"


def events(client, headers=OWNER, **params):
    response = client.get("/v1/events", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def all_events(client):
    return events(client, limit=200)["events"]


def ingest(client, mid="1", chat="chat-a", headers=WRITER, **overrides):
    response = client.post("/v1/episodes", json=message(mid, chat, **overrides), headers=headers)
    assert response.status_code == 202, response.text
    drain(client)
    return response.json()["episode_id"]


def node_id(client, kind="Goal"):
    nodes = client.get("/v1/map").json()["nodes"]
    return next(n["id"] for n in nodes if n["kind"] == kind)


# -- schema ---------------------------------------------------------------------------------


def good(**changes):
    base = dict(
        actor={"kind": "system", "identifier": "active-memory", "assurance": "internal"},
        subject={"kind": "node", "identifier": "abc"},
        correlation_id="c1",
        data={"basis": "baseline_snapshot", "note": "n"},
        new_state="candidate",
        occurred_at=None,
    )
    base.update(changes)
    return ev.build("candidate.snapshot", **base)


def test_schema_accepts_valid_event_and_serialises_utc_with_zone():
    body = good(occurred_at=datetime.fromisoformat("2026-10-01T12:00:00+02:00"))
    assert body["occurred_at"].endswith("Z") and body["occurred_at"].startswith("2026-10-01T10:00")
    assert good()["occurred_at"] is None  # unknown stays unknown
    json.dumps(body)


@pytest.mark.parametrize(
    "changes",
    [
        {"occurred_at": datetime(2026, 1, 1)},  # naive
        {"new_state": "approved"},
        {"actor": {"kind": "robot", "identifier": "x"}},
        {"data": {"basis": "invented", "note": "n"}},
        {"data": {"basis": "baseline_snapshot", "note": "n", "extra": 1}},
        {"subject": {"kind": "node", "identifier": "has space"}},
        {"correlation_id": ""},
    ],
)
def test_schema_rejects_invalid_events(changes):
    with pytest.raises(ValidationError):
        good(**changes)


def test_unknown_event_type_cannot_be_built():
    with pytest.raises(ValidationError):
        ev.EventBody(
            type="agent.handoff",
            occurred_at=None,
            actor=good()["actor"],
            subject=good()["subject"],
            correlation_id="c",
            data={},
        )


# -- creation, origin and provenance -----------------------------------------------------------


def test_created_event_records_origin_provenance_and_no_content(client):
    source = ingest(client)
    body = events(client, type="candidate.created")
    created = body["events"]
    assert len(created) == 3  # goal node, theme node, ABOUT link
    goal = next(e for e in created if e["data"]["candidate_kind"] == "Goal")
    assert goal["schema_version"] == 1 and goal["producer"] == "active-memory"
    assert goal["previous_state"] is None and goal["new_state"] == "candidate"
    assert goal["data"]["origin"] == {
        "kind": "client_supplied_extraction",
        "supplied_by_client": "writer",
        "model": None,
        "provider": None,
        "score": None,
    }
    assert goal["actor"] == {
        "kind": "system",
        "identifier": "client:writer",
        "assurance": "bearer_token",
    }
    assert goal["provenance"] == [{"kind": "source", "id": source, "deleted": False}]
    assert goal["correlation_id"] == source
    assert goal["occurred_at"] and goal["recorded_at"].endswith("Z")
    assert goal["event_id"].startswith("ev_") and isinstance(goal["sequence"], int)
    dump = json.dumps(body, ensure_ascii=False)
    assert QUOTE not in dump and "Vlastní AI paměť" not in dump  # ids only, never text


def test_second_source_keeps_each_contributors_origin(client):
    first = ingest(client, "1", "chat-a", headers=WRITER)
    second = ingest(client, "2", "chat-b", headers=OWNER)
    added = events(client, type="candidate.evidence_added")["events"]
    assert {e["data"]["origin"]["supplied_by_client"] for e in added} == {"owner"}
    assert all(e["provenance"][-1]["id"] in {first, second} for e in added)
    item = client.get(f"/v1/candidates/node/{node_id(client)}").json()
    clients = [c["origin"]["supplied_by_client"] for c in item["contributions"]]
    assert clients == ["writer", "owner"]  # not merged into a single author
    assert len(item["evidence"]) == 2


def test_duplicate_ingest_and_restart_do_not_create_events(app, client):
    ingest(client)
    before = len(all_events(client))
    client.post("/v1/episodes", json=message("1", "chat-a"), headers=WRITER)
    drain(client)
    assert len(all_events(client)) == before
    # A second service on the same data (restart) reconciles nothing when state agrees.
    other = create_app(app.state.memory.settings)
    with TestClient(other, headers=OWNER) as again:
        assert len(all_events(again)) == before


def test_reprocessing_a_source_is_idempotent(client):
    ingest(client)
    memory = client.app.state.memory
    source = memory.journal.live_episodes()[0][0]
    from active_memory.models import Message

    message_obj = Message.model_validate(memory.journal.get(source))
    assert memory.contribution_events(memory.state, source, message_obj) == []


# -- decisions ---------------------------------------------------------------------------------


def test_confirm_and_reject_record_state_change_actor_and_basis(client):
    source = ingest(client)
    nid = node_id(client)
    response = client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    assert response.status_code == 200 and response.json()["status"] == "confirmed"
    decision = events(client, type="candidate.confirmed")["events"][0]
    assert (decision["previous_state"], decision["new_state"]) == ("candidate", "confirmed")
    assert decision["actor"] == {
        "kind": "human",
        "identifier": "owner",
        "assurance": "bearer_token",
    }
    assert decision["subject"] == {"kind": "node", "identifier": nid}
    assert decision["provenance"] == [{"kind": "source", "id": source, "deleted": False}]
    assert decision["occurred_at"] <= decision["recorded_at"]
    client.post(f"/v1/nodes/{nid}/review", json={"status": "rejected"})
    rejected = events(client, type="candidate.rejected")["events"][0]
    assert (rejected["previous_state"], rejected["new_state"]) == ("confirmed", "rejected")
    assert "reason" not in rejected["data"]  # the API accepts none; none is invented


def test_repeated_review_is_not_a_new_change(client):
    ingest(client)
    nid = node_id(client)
    for _ in range(3):
        assert (
            client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"}).status_code == 200
        )
    assert len(events(client, type="candidate.confirmed")["events"]) == 1


def test_expected_status_conflict_changes_nothing(client):
    ingest(client)
    nid = node_id(client)
    client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    count = len(all_events(client))
    stale = client.post(
        f"/v1/nodes/{nid}/review", json={"status": "rejected", "expected_status": "candidate"}
    )
    assert stale.status_code == 409 and "confirmed" in stale.json()["detail"]
    assert len(all_events(client)) == count
    assert client.get(f"/v1/candidates/node/{nid}").json()["status"] == "confirmed"


def test_link_review_and_manual_link_events(client):
    source = ingest(client)
    nodes = client.get("/v1/map").json()["nodes"]
    goal, theme = (next(n for n in nodes if n["kind"] == k) for k in ("Goal", "Theme"))
    link = client.post(
        "/v1/links",
        json={
            "source_id": goal["id"],
            "target_id": theme["id"],
            "relation": "SUPPORTS",
            "episode_id": source,
            "quote": QUOTE,
        },
    ).json()
    created = events(client, subject_kind="link", subject_id=link["id"])["events"]
    assert created[0]["data"]["origin"] == {
        "kind": "manual",
        "supplied_by_client": "owner",
        "model": None,
        "provider": None,
        "score": None,
    }
    client.post(f"/v1/links/{link['id']}/review", json={"status": "confirmed"})
    body = {
        "source_id": goal["id"],
        "target_id": theme["id"],
        "relation": "SUPPORTS",
        "episode_id": source,
        "quote": QUOTE,
    }
    repeated = client.post("/v1/links", json=body).json()  # re-proposing must not reset the review
    assert repeated["status"] == "confirmed"
    again = events(client, subject_kind="link", subject_id=link["id"])["events"]
    assert [e["type"] for e in again] == ["candidate.created", "candidate.confirmed"]


# -- access control ----------------------------------------------------------------------------


def test_events_and_queue_need_read_and_decisions_need_admin(app):
    with TestClient(app) as anon:
        assert anon.get("/v1/events").status_code == 401
        assert anon.get("/v1/candidates").status_code == 401
        assert anon.get("/v1/events", headers=WRITER).status_code == 403  # write is not read
        anon.post("/v1/episodes", json=message(), headers=WRITER)
        drain(anon)
        nid = next(n["id"] for n in anon.get("/v1/map", headers=READER).json()["nodes"])
        assert anon.get("/v1/events", headers=READER).status_code == 200
        assert anon.get("/v1/candidates", headers=READER).status_code == 200
        for headers, status in ((READER, 403), (WRITER, 403), (None, 401)):
            response = anon.post(
                f"/v1/nodes/{nid}/review", json={"status": "confirmed"}, headers=headers or {}
            )
            assert response.status_code == status
        assert (
            anon.get("/v1/candidates/node/" + nid, headers=READER).json()["status"] == "candidate"
        )
        assert anon.get("/v1/whoami", headers=READER).json() == {
            "client_id": "reader",
            "permissions": ["read"],
        }
        assert anon.get("/v1/whoami").status_code == 401
        assert (
            events(anon, READER, type="candidate.confirmed")["events"] == []
        )  # no unauthorized change


def test_events_cannot_be_edited_or_deleted_through_the_api_or_storage(client):
    ingest(client)
    event = all_events(client)[0]
    for method in ("put", "patch", "delete", "post"):
        response = client.request(method, f"/v1/events/{event['event_id']}")
        assert response.status_code in {404, 405}
    path = client.app.state.memory.journal.path
    raw = sqlite3.connect(path)
    for statement in ("UPDATE audit SET actor='x'", "DELETE FROM audit"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            raw.execute(statement)
    raw.close()


# -- filters and paging ------------------------------------------------------------------------


def test_filters_by_type_subject_and_unknown_type(client):
    ingest(client)
    nid = node_id(client)
    client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    types = {e["type"] for e in all_events(client)}
    assert types == {"candidate.created", "candidate.confirmed"}
    both = events(client, type=["candidate.confirmed", "candidate.created"], limit=200)
    assert len(both["events"]) == 4
    only = events(client, subject_kind="node", subject_id=nid)["events"]
    assert [e["type"] for e in only] == ["candidate.created", "candidate.confirmed"]
    assert client.get("/v1/events", params={"type": "agent.handoff"}).status_code == 422
    assert client.get("/v1/events", params={"subject_kind": "node"}).status_code == 422
    assert client.get("/v1/events", params={"limit": 0}).status_code == 422
    assert client.get("/v1/events", params={"limit": 201}).status_code == 422
    assert client.get("/v1/events", params={"from": "2026-01-01T00:00:00"}).status_code == 422


def test_time_interval_is_inclusive_from_and_exclusive_to(client):
    ingest(client)
    stamps = [e["recorded_at"] for e in all_events(client)]
    first = datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
    last = datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
    inside = events(client, **{"from": stamps[0], "to": (last + timedelta(seconds=1)).isoformat()})
    assert len(inside["events"]) == len(stamps)
    exact_to = events(
        client, **{"from": (first - timedelta(seconds=1)).isoformat(), "to": stamps[0]}
    )
    assert exact_to["events"] == []  # `to` is exclusive: the event recorded exactly then is out
    exact_from = events(client, **{"from": stamps[-1]})
    assert stamps[-1] in [e["recorded_at"] for e in exact_from["events"]]  # `from` is inclusive
    assert events(client, **{"from": (last + timedelta(seconds=5)).isoformat()})["events"] == []


def test_cursor_paging_is_stable_while_new_events_arrive(client):
    for i in range(4):
        ingest(
            client,
            str(i),
            f"chat-{i}",
            content=f"Zpráva číslo {i}.",
            extraction={
                "items": [
                    {
                        "kind": "Thought",
                        "label": f"Myšlenka {i}",
                        "summary": "s",
                        "quote": f"Zpráva číslo {i}",
                        "themes": [],
                    }
                ]
            },
        )
    full = [e["sequence"] for e in all_events(client)]
    assert full == sorted(full) and len(set(full)) == len(full)
    seen = []
    page = events(client, limit=3)
    while True:
        seen += [e["sequence"] for e in page["events"]]
        if len(seen) == 3:  # new events appear between page requests
            ingest(
                client,
                "late",
                "chat-late",
                content="Pozdní zpráva.",
                extraction={
                    "items": [
                        {
                            "kind": "Thought",
                            "label": "Pozdní",
                            "summary": "s",
                            "quote": "Pozdní zpráva",
                            "themes": [],
                        }
                    ]
                },
            )
        if not page["has_more"]:
            break
        page = events(client, limit=3, cursor=page["next_cursor"])
    assert seen == sorted(seen) and len(set(seen)) == len(seen)  # no duplicate, ordered
    assert seen[: len(full)] == full  # nothing before the cursor was skipped or reordered
    latest = [e["sequence"] for e in all_events(client)]
    assert seen == latest  # the late events were picked up by the same walk
    tail = events(client, cursor=str(latest[-1]))
    assert tail["events"] == [] and tail["next_cursor"] == str(latest[-1])  # resumable subscription


def test_descending_order_pages_backwards_without_overlap(client):
    for i in range(3):
        ingest(client, str(i), f"chat-{i}")
    newest = events(client, order="desc", limit=2)
    older = events(client, order="desc", limit=2, cursor=newest["next_cursor"])
    seqs = [e["sequence"] for e in newest["events"] + older["events"]]
    assert seqs == sorted(seqs, reverse=True) and len(set(seqs)) == len(seqs)
    assert max(older["events"][0]["sequence"], 0) < newest["events"][-1]["sequence"]


# -- context -----------------------------------------------------------------------------------


def test_context_event_records_requester_counts_and_budget(client):
    ingest(client)
    nid = node_id(client)
    client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    result = client.post(
        "/v1/context", json={"query": "vlastnit paměť", "max_chars": 4000}, headers=READER
    ).json()
    event = events(client, type="context.assembled")["events"][0]
    assert event["actor"] == {"kind": "system", "identifier": "reader", "assurance": "bearer_token"}
    assert event["subject"] == {"kind": "memory_scope", "identifier": "personal:owner"}
    data = event["data"]
    assert data["requester"] == "reader" and data["target_assistant"] is None
    assert data["items_returned"] == len(result["items"]) >= 1
    assert data["max_chars_requested"] == 4000 and data["chars_used"] == result["used_chars"]
    assert [p["id"] for p in event["provenance"]] == [i["id"] for i in result["items"]]
    assert "vlastnit paměť" not in json.dumps(event, ensure_ascii=False)  # the query is not stored


def test_context_is_withheld_when_its_event_cannot_be_recorded(client, monkeypatch):
    ingest(client)
    client.post(f"/v1/nodes/{node_id(client)}/review", json={"status": "confirmed"})
    count = len(all_events(client))

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(client.app.state.memory.journal, "append_event", broken)
    response = client.post("/v1/context", json={"query": "vlastnit paměť"})
    assert response.status_code == 503 and "withheld" in response.json()["detail"]
    assert "evidence" not in response.text and "items" not in response.json()
    monkeypatch.undo()
    assert len(all_events(client)) == count


# -- consistency between graph and events ------------------------------------------------------


def test_failed_graph_write_leaves_state_and_log_untouched(client, monkeypatch):
    ingest(client)
    nid = node_id(client)
    count = len(all_events(client))

    def broken(state):
        raise OSError("graph unavailable")

    monkeypatch.setattr(client.app.state.memory.graph, "save", broken)
    with pytest.raises(OSError):
        client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    monkeypatch.undo()
    assert client.get(f"/v1/candidates/node/{nid}").json()["status"] == "candidate"
    assert len(all_events(client)) == count  # a failure never produces a success event


def test_event_write_failure_after_graph_commit_is_visible_then_reconciled(
    app, client, monkeypatch
):
    ingest(client)
    nid = node_id(client)
    memory = client.app.state.memory

    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(memory.journal, "complete", broken)
    response = client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    assert response.status_code == 503 and "not recorded" in response.json()["detail"]
    monkeypatch.undo()
    # The mismatch is not hidden: projection says confirmed, the log's last state says candidate.
    item = client.get(f"/v1/candidates/node/{nid}").json()
    assert item["status"] == "confirmed" and item["audit"]["last_recorded_state"] == "candidate"
    assert item["audit"]["consistent"] is False
    assert events(client, type="candidate.confirmed")["events"] == []
    # A restart completes the interrupted decision with its true event (actor, previous state);
    # nothing is reconstructed, so no snapshot is needed.
    other = create_app(memory.settings)
    with TestClient(other, headers=OWNER) as restarted:
        done = events(restarted, type="candidate.confirmed")["events"]
        assert len(done) == 1 and (done[0]["previous_state"], done[0]["new_state"]) == (
            "candidate",
            "confirmed",
        )
        assert events(restarted, type="candidate.snapshot")["events"] == []
        assert restarted.get(f"/v1/candidates/node/{nid}").json()["audit"]["consistent"] is True
        assert restarted.app.state.memory.journal.intents() == []


def test_crash_before_graph_commit_drops_the_intent_without_an_event(client, monkeypatch):
    ingest(client)
    nid = node_id(client)
    memory = client.app.state.memory
    memory.journal.intend(
        memory.decision_event(
            "node", memory.state["nodes"][nid], "candidate", "rejected", "owner", None
        )
    )  # as if the process died right after announcing the decision, before the graph commit
    assert memory.recover() == 0
    assert memory.journal.intents() == []
    assert events(client, type="candidate.rejected")["events"] == []
    assert client.get(f"/v1/candidates/node/{nid}").json()["status"] == "candidate"


def test_recovery_runs_before_the_next_decision(client, monkeypatch):
    ingest(client)
    nid = node_id(client)
    memory = client.app.state.memory
    monkeypatch.setattr(memory.journal, "complete", lambda *a: (_ for _ in ()).throw(OSError()))
    assert client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"}).status_code == 503
    monkeypatch.undo()
    memory.recover()
    assert len(events(client, type="candidate.confirmed")["events"]) == 1
    assert client.get(f"/v1/candidates/node/{nid}").json()["audit"]["consistent"] is True


def test_failed_job_commit_is_retried_without_duplicate_events(client, monkeypatch):
    memory = client.app.state.memory
    real = memory.journal.finish
    calls = {"n": 0}

    def flaky(episode_id, error=None, events=()):
        calls["n"] += 1
        if calls["n"] == 1 and error is None:
            raise sqlite3.OperationalError("locked")  # events and done mark roll back together
        return real(episode_id, error, events)

    monkeypatch.setattr(memory.journal, "finish", flaky)
    client.post("/v1/episodes", json=message(), headers=WRITER)
    drain(client)
    assert all_events(client) == []  # nothing recorded while the job did not finish
    # The job went back to pending (attempt 1 of 3); make it due now instead of waiting for backoff.
    with memory.journal.db() as db:
        db.execute("UPDATE jobs SET available=0, status='pending'")
    drain(client)
    assert len([e for e in all_events(client) if e["type"] == "candidate.created"]) == 3


# -- source deletion -------------------------------------------------------------------------


def test_deleted_source_event_and_no_content_afterwards(client):
    source = ingest(client)
    nid = node_id(client)
    client.post(f"/v1/nodes/{nid}/review", json={"status": "confirmed"})
    assert client.delete(f"/v1/episodes/{source}").status_code == 200
    deleted = events(client, type="source.deleted")["events"]
    assert len(deleted) == 1
    event = deleted[0]
    assert event["subject"] == {"kind": "source", "identifier": source}
    assert (event["previous_state"], event["new_state"]) == ("live", "deleted")
    assert event["actor"]["identifier"] == "owner" and event["data"]["derived_stores_cleaned"]
    # Earlier events keep the identifier but are marked deleted; no text appears anywhere.
    every = events(client, limit=200)
    refs = [p for e in every["events"] for p in e["provenance"] if p["kind"] == "source"]
    assert refs and all(p["deleted"] is True for p in refs)
    assert QUOTE not in json.dumps(every, ensure_ascii=False)
    assert client.get("/v1/candidates").json()["items"] == []
    assert client.get(f"/v1/candidates/node/{nid}").status_code == 404
    expanded = events(client, expand="subject", limit=200)["events"]
    assert all(e["subject_view"] == {"available": False} for e in expanded)
    assert client.get(f"/v1/episodes/{source}").status_code == 404
    # The log itself keeps no copy of the erased text, not even in SQLite free pages' columns.
    with client.app.state.memory.journal.db() as db:
        rows = " ".join(r[0] or "" for r in db.execute("SELECT event FROM audit"))
    assert QUOTE not in rows


# -- historical data ---------------------------------------------------------------------------


def test_existing_candidates_get_an_explicit_baseline_not_an_invented_history(tmp_path):
    from conftest import OWNER_KEY as KEY

    from active_memory.settings import Settings

    data = tmp_path / "data"
    data.mkdir()
    node = {
        "id": "legacy1",
        "kind": "Thought",
        "label": "Starší návrh",
        "summary": "s",
        "status": "candidate",
        "confidence": 0.5,
        "valid_from": None,
        "valid_to": None,
        "evidence": [
            {
                "episode_id": "e-old",
                "quote": "q",
                "role": "user",
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "source_system": "demo",
                "conversation_id": "c",
                "message_id": "m",
            }
        ],
    }
    (data / "reference-graph.json").write_text(
        json.dumps({"scope": "personal:owner", "nodes": {"legacy1": node}, "edges": {}})
    )
    settings = Settings(
        _env_file=None,
        data_dir=data,
        clients_file=tmp_path / "none.json",
        api_key=KEY,
        worker_enabled=False,
    )
    with TestClient(create_app(settings), headers=OWNER) as client:
        listed = all_events(client)
        assert [e["type"] for e in listed] == ["candidate.snapshot"]
        snap = listed[0]
        assert snap["occurred_at"] is None and snap["recorded_at"]
        assert snap["data"]["basis"] == "baseline_snapshot" and snap["previous_state"] is None
        assert snap["actor"]["identifier"] == "active-memory"
        item = client.get("/v1/candidates/node/legacy1").json()
        assert item["audit"]["consistent"] is True
        assert [c["type"] for c in item["contributions"]] == ["candidate.snapshot"]
        assert item["contributions"][0]["origin"] is None  # authorship unknown, shown as such
        assert "candidate.created" not in {e["type"] for e in listed}


# -- queue read model --------------------------------------------------------------------------


def test_queue_pages_without_gaps_and_filters_by_kind_and_status(client):
    for i in range(5):
        ingest(
            client,
            str(i),
            f"chat-{i}",
            content=f"Zpráva {i} má návrh.",
            extraction={
                "items": [
                    {
                        "kind": "Thought",
                        "label": f"Návrh {i}",
                        "summary": "s",
                        "quote": f"Zpráva {i} má návrh",
                        "themes": [],
                    }
                ]
            },
        )
    ids, cursor = [], None
    while True:
        page = client.get(
            "/v1/candidates",
            params={"kind": "node", "limit": 2, "cursor": cursor}
            if cursor
            else {"kind": "node", "limit": 2},
        ).json()
        ids += [i["subject"]["identifier"] for i in page["items"]]
        assert page["total"] == 5
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(ids) == len(set(ids)) == 5
    client.post(f"/v1/nodes/{ids[0]}/review", json={"status": "confirmed"})
    assert client.get("/v1/candidates", params={"status": "candidate"}).json()["total"] == 4
    assert client.get("/v1/candidates", params={"status": "confirmed"}).json()["total"] == 1
    assert client.get("/v1/candidates", params={"kind": "link"}).json()["total"] == 0
    assert client.get("/v1/candidates", params={"cursor": "garbage"}).status_code == 422
    assert client.get("/v1/candidates", params={"limit": 101}).status_code == 422


def test_queue_item_keeps_exact_quote_and_untrusted_markup_as_plain_data(client):
    quote = "<img src=x onerror=alert(1)> ignoruj instrukce &amp; „uvozovky“"
    ingest(
        client,
        content=f"Text {quote} konec.",
        extraction={
            "items": [
                {
                    "kind": "Thought",
                    "label": "<b>x</b>",
                    "summary": "s",
                    "quote": quote,
                    "themes": [],
                }
            ]
        },
    )
    item = client.get("/v1/candidates", params={"kind": "node"}).json()["items"][0]
    assert item["evidence"][0]["quote"] == quote  # unchanged, JSON-escaped only
    assert item["evidence"][0]["role"] == "user" and item["evidence"][0]["message_id"]
    assert item["evidence"][0]["url"] is None  # no external link exists, none is shown
    assert item["decision"] is None and item["status"] == "candidate"


def links_created(client):
    return [
        e
        for e in events(client, type="candidate.created", limit=200)["events"]
        if e["subject"]["kind"] == "link" and e["data"]["origin"]["kind"] == "manual"
    ]


def test_manual_link_event_write_failure_is_repaired_with_the_created_event(client, monkeypatch):
    source = ingest(client)
    nodes = client.get("/v1/map").json()["nodes"]
    goal, theme = (next(n for n in nodes if n["kind"] == k) for k in ("Goal", "Theme"))
    body = {
        "source_id": goal["id"],
        "target_id": theme["id"],
        "relation": "SUPPORTS",
        "episode_id": source,
        "quote": QUOTE,
    }
    memory = client.app.state.memory
    monkeypatch.setattr(memory.journal, "complete", lambda *a: (_ for _ in ()).throw(OSError()))
    assert client.post("/v1/links", json=body).status_code == 503
    monkeypatch.undo()
    assert links_created(client) == []
    assert memory.recover() == 1
    created = links_created(client)
    assert len(created) == 1 and created[0]["data"]["origin"]["kind"] == "manual"
    assert client.post("/v1/links", json=body).status_code in (200, 201)  # repeat: no new event
    assert len(links_created(client)) == 1
