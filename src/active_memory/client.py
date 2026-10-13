import httpx


class MemoryClient:
    """Small async SDK; useful with janAGI, OpenClaw, Hermes, custom agents and importers."""

    def __init__(self, base_url, api_key):
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120,
        )

    async def call(self, method, path, payload=None):
        response = await self.http.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()

    async def ingest(self, message):
        return await self.call("POST", "/v1/episodes", message)

    async def context(self, query, **options):
        return await self.call("POST", "/v1/context", {"query": query, **options})

    async def search(self, query, **options):
        return await self.call("POST", "/v1/search", {"query": query, **options})

    async def close(self):
        await self.http.aclose()
