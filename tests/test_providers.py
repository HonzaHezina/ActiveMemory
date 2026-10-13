import asyncio

import pytest

from active_memory.providers import GraphitiAdapter
from active_memory.settings import Settings


def test_explicit_model_authorization_required():
    with pytest.raises(ValueError, match="ALLOW_MODEL_CALLS"):
        Settings(_env_file=None, extraction_mode="llm", model_api_key="fake-key")


def test_graphiti_adapter_constructs_against_pinned_sdk(monkeypatch):
    pytest.importorskip("graphiti_core")
    monkeypatch.setenv("GRAPHITI_TELEMETRY_ENABLED", "false")
    settings = Settings(
        _env_file=None,
        backend="neo4j",
        graphiti_enabled=True,
        allow_model_calls=True,
        neo4j_password="fake-local-password",
        model_api_key="fake-model-key",
        embedding_api_key="fake-embedding-key",
    )
    adapter = GraphitiAdapter(settings)
    assert adapter.client.driver is not None
    from graphiti_core.helpers import validate_group_id

    assert validate_group_id(adapter.group_id)
    asyncio.run(adapter.close())


def test_graphiti_creates_episode_before_uuid_update(monkeypatch):
    pytest.importorskip("graphiti_core")
    from unittest.mock import AsyncMock

    from conftest import message
    from graphiti_core.errors import NodeNotFoundError
    from graphiti_core.nodes import EpisodicNode

    from active_memory.models import Message

    settings = Settings(
        _env_file=None,
        backend="neo4j",
        graphiti_enabled=True,
        allow_model_calls=True,
        neo4j_password="fake-password",
        model_api_key="fake-key",
        embedding_api_key="fake-key",
    )
    adapter = GraphitiAdapter(settings)
    source_id = "cf732712-4ab8-4f19-9ef0-654bed311534"
    monkeypatch.setattr(
        EpisodicNode, "get_by_uuid", AsyncMock(side_effect=NodeNotFoundError(source_id))
    )
    saved = AsyncMock()
    monkeypatch.setattr(EpisodicNode, "save", saved)
    projected = AsyncMock()
    monkeypatch.setattr(adapter.client, "add_episode", projected)
    asyncio.run(adapter.add(source_id, Message.model_validate(message())))
    saved.assert_awaited_once()
    assert projected.call_args.kwargs["uuid"] == source_id
    assert projected.call_args.kwargs["group_id"] == adapter.group_id
    asyncio.run(adapter.close())


@pytest.mark.parametrize(
    "quote,valid", [("Chci vlastnit svoji AI paměť", True), ("Tohle se nestalo", False)]
)
def test_llm_extraction_requires_supported_quotes(monkeypatch, quote, valid):
    import httpx
    from conftest import message

    from active_memory.models import Message
    from active_memory.providers import LLMExtractor

    result = {
        "items": [
            {"kind": "Goal", "label": "Vlastní paměť", "summary": "Vlastní paměť", "quote": quote}
        ]
    }

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            import json

            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"choices": [{"message": {"content": json.dumps(result)}}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    settings = Settings(
        _env_file=None, extraction_mode="llm", allow_model_calls=True, model_api_key="fake-key"
    )
    coro = LLMExtractor(settings).extract(Message.model_validate(message()), [])
    if valid:
        assert asyncio.run(coro).items[0].quote == quote
    else:
        with pytest.raises(ValueError, match="unsupported evidence quote"):
            asyncio.run(coro)
