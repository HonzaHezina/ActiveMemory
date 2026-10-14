import asyncio

from active_memory.mcp_server import create_mcp


def test_mcp_discovery_and_write_opt_in():
    read_only = create_mcp("http://127.0.0.1:8080", "fake-key")
    tools = asyncio.run(read_only.list_tools())
    assert {t.name for t in tools} == {
        "memory_search",
        "memory_get_context",
        "memory_map",
        "memory_get_source",
        "memory_list_events",
    }
    writable = create_mcp("http://127.0.0.1:8080", "fake-key", allow_write=True)
    tools = asyncio.run(writable.list_tools())
    assert "memory_add_message" in {t.name for t in tools}


def turns(*pairs):
    from active_memory.mcp_server import ChatTurn

    return [ChatTurn(role=r, content=c) for r, c in pairs]


def test_conversation_messages_are_deterministic_and_say_who_wrote_the_copy():
    from active_memory.mcp_server import conversation_messages

    t = turns(("user", "Ahoj"), ("assistant", "Dobrý den"))
    a = conversation_messages("Plán / zahrady", t, "2026-10-14", "ChatGPT Web")
    assert a == conversation_messages("Plán / zahrady", t, "2026-10-14", "ChatGPT Web")
    assert [m.message_id for m in a] == ["1", "2"] and a[0].source_system == "mcp-chatgpt-web"
    assert a[0].conversation_id.startswith("Plán zahrady (přepsal asistent, 2026-10-14, ")
    assert a[1].occurred_at > a[0].occurred_at
    other = conversation_messages("Plán / zahrady", turns(("user", "Ahoj!")), "2026-10-14")
    assert other[0].conversation_id != a[0].conversation_id


def test_save_conversation_tool_counts_new_duplicates_and_rejections(monkeypatch):
    import httpx

    from active_memory import mcp_server

    seen = []

    class Fake:
        def __init__(self, *args):
            pass

        async def call(self, method, path, payload=None):
            seen.append(payload)
            if "password" in payload["content"]:
                request = httpx.Request("POST", "http://x/v1/episodes")
                raise httpx.HTTPStatusError(
                    "bad", request=request, response=httpx.Response(422, request=request)
                )
            return {"duplicate": payload["message_id"] == "1"}

    monkeypatch.setattr(mcp_server, "MemoryClient", Fake)
    server = mcp_server.create_mcp("http://x", "k", allow_write=True)
    messages = [
        {"role": "user", "content": "Ahoj"},
        {"role": "assistant", "content": "Dobrý den"},
        {"role": "user", "content": "password=tajne12345678"},
    ]
    result = asyncio.run(
        server.call_tool("memory_save_conversation", {"title": "T", "messages": messages})
    )
    text = str(result)
    assert len(seen) == 3
    assert '"new": 1' in text.replace("'", '"') and '"rejected": 1' in text.replace("'", '"')
    assert "memory_save_conversation" not in {
        t.name for t in asyncio.run(mcp_server.create_mcp("http://x", "k").list_tools())
    }
