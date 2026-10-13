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
    }
    writable = create_mcp("http://127.0.0.1:8080", "fake-key", allow_write=True)
    tools = asyncio.run(writable.list_tools())
    assert "memory_add_message" in {t.name for t in tools}
