"""Runtime LLM settings: admin only, secrets write-only, nothing is sent without explicit consent."""

import json

import httpx
import pytest
from conftest import OWNER_KEY, READER_KEY, WRITER_KEY
from fastapi.testclient import TestClient

from active_memory.api import create_app

OWNER = {"Authorization": f"Bearer {OWNER_KEY}"}
SECRET = "sk-test-secret-0123456789"
GOOD = {
    "extraction_mode": "llm",
    "allow_model_calls": True,
    "model_base_url": "https://llm.example.org/v1",
    "model_name": "test-model",
    "model_api_key": SECRET,
}


def put(client, body, headers=OWNER):
    return client.put("/v1/settings/llm", json=body, headers=headers)


def test_settings_need_admin(app):
    with TestClient(app) as anonymous:
        for headers, code in (
            ({}, 401),
            ({"Authorization": f"Bearer {READER_KEY}"}, 403),
            ({"Authorization": f"Bearer {WRITER_KEY}"}, 403),
        ):
            assert anonymous.get("/v1/settings", headers=headers).status_code == code
            assert anonymous.put("/v1/settings/llm", json={}, headers=headers).status_code == code
            test = anonymous.post(
                "/v1/settings/llm/test", json={"target": "model"}, headers=headers
            )
            assert test.status_code == code
        assert anonymous.get("/v1/settings", headers=OWNER).status_code == 200


def test_defaults_are_off_and_keys_are_never_returned(client):
    view = client.get("/v1/settings").json()
    assert view["runtime"]["extraction_mode"] == "provided"
    assert view["runtime"]["allow_model_calls"] is False
    assert view["active"] == {
        "extraction": "provided",
        "embeddings": False,
        "judge": False,
        "recommendations": False,
    }
    assert view["secrets"] == {"model_api_key": False, "embedding_api_key": False}
    changed = put(client, GOOD)
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert body["active"]["extraction"] == "llm" and body["secrets"]["model_api_key"] is True
    assert body["providers"]["model_host"] == "llm.example.org"
    assert SECRET not in json.dumps(body) and SECRET not in client.get("/v1/settings").text


def test_invalid_changes_are_refused_and_change_nothing(client):
    refused = [
        {"extraction_mode": "llm"},  # no consent, no key
        {"extraction_mode": "llm", "allow_model_calls": True},  # no key
        {**GOOD, "model_base_url": "ftp://x"},
        {**GOOD, "model_base_url": "https://user:pw@llm.example.org/v1"},
        {**GOOD, "model_base_url": "http://169.254.169.254/v1"},
        {"similarity_mode": "embedding"},  # needs consent and an embedding key
    ]
    for body in refused:
        response = put(client, body)
        assert response.status_code == 422, (body, response.text)
        assert "validation failed" != response.json()["detail"]  # says why
    view = client.get("/v1/settings").json()
    assert view["runtime"]["extraction_mode"] == "provided" and view["overridden"] == []
    assert client.put("/v1/settings/llm", json={"surprise": 1}, headers=OWNER).status_code == 422


def test_settings_survive_a_restart_and_audit_records_names_only(app, client):
    assert put(client, GOOD).status_code == 200
    with client.app.state.memory.journal.db() as db:
        audit = [dict(r) for r in db.execute("SELECT * FROM audit WHERE action='settings_changed'")]
    assert audit and SECRET not in json.dumps(audit) and "model_api_key" in audit[-1]["target"]
    with TestClient(create_app(client.app.state.memory.settings), headers=OWNER) as again:
        view = again.get("/v1/settings").json()
        assert view["runtime"]["model_name"] == "test-model"
        assert view["secrets"]["model_api_key"] is True and view["active"]["extraction"] == "llm"
        assert "model_api_key" in view["overridden"]


def test_removing_the_key_while_in_use_is_refused_and_clearing_consent_switches_off(client):
    put(client, GOOD)
    assert put(client, {"model_api_key": ""}).status_code == 422
    off = put(client, {"extraction_mode": "provided", "allow_model_calls": False})
    assert off.status_code == 200 and off.json()["active"]["extraction"] == "provided"


def test_provider_test_uses_only_synthetic_text_and_hides_provider_errors(client):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "bad.example.org":
            return httpx.Response(401, text="invalid key " + SECRET)
        return httpx.Response(200, json={"choices": []})

    memory = client.app.state.memory
    memory.http_transport = httpx.MockTransport(handler)
    refused = client.post("/v1/settings/llm/test", json={"target": "model"})
    assert refused.status_code == 422 and not seen  # no consent: nothing leaves the machine
    put(client, GOOD)
    ok = client.post("/v1/settings/llm/test", json={"target": "model"}).json()
    assert ok["ok"] is True and ok["host"] == "llm.example.org" and len(seen) == 1
    sent = json.loads(seen[0].content)
    assert sent["messages"] == [{"role": "user", "content": "Reply with the single word OK."}]
    assert seen[0].headers["authorization"] == f"Bearer {SECRET}"
    put(client, {"model_base_url": "https://bad.example.org/v1"})
    bad = client.post("/v1/settings/llm/test", json={"target": "model"})
    assert bad.json()["ok"] is False and bad.json()["status"] == 401
    assert SECRET not in bad.text  # the provider's body is never relayed


def test_changed_settings_take_effect_for_new_ingests(client, monkeypatch):
    from conftest import drain, message

    from active_memory.models import Extraction

    put(client, GOOD)
    memory = client.app.state.memory
    calls = []

    async def fake(msg, themes):
        calls.append(msg.content)
        return Extraction()

    monkeypatch.setattr(memory.extractor, "extract", fake)
    body = message("1", "chat-x")
    body.pop("extraction")
    assert client.post("/v1/episodes", json=body).status_code == 202
    drain(client)
    assert calls == [body["content"]]  # the model path is now used for user messages
    put(client, {"extraction_mode": "provided"})
    assert memory.extractor is None


def test_test_endpoint_rejects_unknown_target(client):
    assert client.post("/v1/settings/llm/test", json={"target": "other"}).status_code == 422


# -- providers: presets, one key for everything by default, per-task models -------------------


def test_presets_name_current_models_per_task_and_are_served_to_the_ui(client):
    presets = {p["id"]: p for p in client.get("/v1/settings").json()["presets"]}
    assert {"gemini", "mistral", "openai", "ollama"} <= set(presets)
    gemini, mistral = presets["gemini"], presets["mistral"]
    assert gemini["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert (gemini["model"], gemini["advice_model"]) == (
        "gemini-3.5-flash-lite",
        "gemini-3.8-flash",
    )
    assert gemini["embedding_model"] == "gemini-embedding-001"
    assert mistral["base_url"] == "https://api.mistral.ai/v1"
    assert (mistral["model"], mistral["advice_model"]) == (
        "mistral-small-2603",
        "mistral-medium-3-5",
    )
    assert mistral["embedding_model"] == "mistral-embed-2312"
    assert all("note" in p for p in presets.values())  # each says what is and is not verified


def test_embeddings_use_the_model_provider_and_key_unless_told_otherwise():
    from active_memory.settings import Settings

    base = {"_env_file": None, "allow_model_calls": True, "model_api_key": "k1"}
    mistral = Settings(
        **base, model_base_url="https://api.mistral.ai/v1", similarity_mode="embedding"
    )
    assert mistral.effective_embedding_base_url == "https://api.mistral.ai/v1"
    assert mistral.effective_embedding_api_key == "k1"
    assert (mistral.effective_embedding_model, mistral.effective_embedding_dim) == (
        "mistral-embed-2312",
        1024,
    )
    split = Settings(
        **base,
        model_base_url="https://api.mistral.ai/v1",
        embedding_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        embedding_api_key="k2",
        similarity_mode="embedding",
    )
    assert split.effective_embedding_api_key == "k2"
    assert split.effective_embedding_model == "gemini-embedding-001"
    assert split.effective_embedding_dim == 3072
    explicit = Settings(**base, embedding_model="custom-embed", embedding_dim=512)
    assert (explicit.effective_embedding_model, explicit.effective_embedding_dim) == (
        "custom-embed",
        512,
    )
    with pytest.raises(ValueError, match="no known default"):
        Settings(**base, model_base_url="https://llm.example.org/v1", similarity_mode="embedding")


def test_one_save_configures_everything_and_advice_model_is_separate(client):
    body = {
        **GOOD,
        "model_base_url": "https://api.mistral.ai/v1",
        "model_name": "mistral-small-2603",
        "advice_model": "mistral-medium-3-5",
        "similarity_mode": "embedding",
        "recommend_enabled": True,
    }
    response = put(client, body)
    assert response.status_code == 200, response.text
    view = response.json()
    effective = view["effective"]
    assert effective["advice_model"] == "mistral-medium-3-5"
    assert (
        effective["embedding_model"] == "mistral-embed-2312" and effective["embedding_dim"] == 1024
    )
    assert effective["embedding_same_provider"] is True and effective["embedding_same_key"] is True
    assert view["providers"]["embedding_host"] == "api.mistral.ai" and view["active"]["embeddings"]
    # An empty value hands the field back to "same as the model".
    assert (
        put(client, {"advice_model": ""}).json()["effective"]["advice_model"]
        == "mistral-small-2603"
    )


def test_models_are_used_per_task(client):
    transport_seen = []

    def handler(request):
        transport_seen.append(json.loads(request.content)["model"])
        content = json.dumps({"recommendation": "confirm", "confidence": 0.5, "reason": "ok"})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    memory = client.app.state.memory
    memory.http_transport = httpx.MockTransport(handler)
    put(client, {**GOOD, "advice_model": "advice-big", "recommend_enabled": True})
    from conftest import drain, message

    client.post("/v1/episodes", json=message("1", "chat-a"))
    drain(client)
    client.portal.call(memory.recommend_now, 1, "owner")
    assert transport_seen == ["advice-big"]  # advice uses the advice model, not the extraction one
    event = client.get("/v1/events", params={"type": "candidate.recommended"}).json()["events"][0]
    assert event["actor"]["identifier"] == "advice-big"


def test_json_mode_fallback_when_a_provider_rejects_json_schema():
    import asyncio

    from active_memory.providers import chat_json
    from active_memory.settings import Settings

    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body["response_format"]["type"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "unsupported schema keyword"})
        assert "JSON schema" in body["messages"][0]["content"]  # the schema is spelled out
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    settings = Settings(_env_file=None, allow_model_calls=True, model_api_key="k")
    messages = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "x"}]
    body = asyncio.run(
        chat_json(settings, httpx.MockTransport(handler), "m", messages, "n", {"type": "object"})
    )
    assert body["choices"][0]["message"]["content"] == "{}"
    assert seen == ["json_schema", "json_object"]
    assert messages[0]["content"] == "be brief"  # the caller's messages are not modified


def test_the_model_key_is_never_lent_to_a_different_embedding_provider():
    from active_memory.settings import Settings

    base = {"_env_file": None, "allow_model_calls": True, "model_api_key": "model-secret"}
    other = Settings(
        **base,
        model_base_url="https://api.mistral.ai/v1",
        embedding_base_url="https://api.openai.com/v1",
    )
    assert other.effective_embedding_api_key == ""  # different host: no borrowed key
    with pytest.raises(ValueError, match="own key"):
        Settings(
            **base,
            model_base_url="https://api.mistral.ai/v1",
            embedding_base_url="https://api.openai.com/v1",
            similarity_mode="embedding",
        )
    same_host = Settings(
        **base,
        model_base_url="https://api.mistral.ai/v1",
        embedding_base_url="https://api.mistral.ai/v1",
    )
    assert same_host.effective_embedding_api_key == "model-secret"


def test_empty_environment_values_mean_unset(monkeypatch):
    from active_memory.settings import Settings

    for name in ("MEMORY_EMBEDDING_DIM", "MEMORY_EMBEDDING_BASE_URL", "MEMORY_EMBEDDING_MODEL"):
        monkeypatch.setenv(name, "")  # as written by .env.example and the compose files
    settings = Settings(_env_file=None)
    assert settings.embedding_dim is None and settings.embedding_base_url == ""
    assert settings.effective_embedding_base_url == settings.model_base_url
