import asyncio
import hashlib
import hmac
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Query as URLQuery
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from .engine import build_context, public_node, search
from .journal import Conflict
from .models import LinkInput, Message, Query, Review, utcnow
from .service import MemoryService
from .settings import Settings
from .similarity import clusters


def create_app(settings=None):
    settings = settings or Settings()
    clients = settings.clients()
    service = MemoryService(settings)

    @asynccontextmanager
    async def lifespan(app):
        await service.initialize()
        task = asyncio.create_task(service.worker()) if settings.worker_enabled else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await service.close()

    app = FastAPI(title="Active Memory", version="0.1.0", lifespan=lifespan)
    app.state.memory = service
    bearer = HTTPBearer(auto_error=False)

    def principal(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
        if credentials is None:
            raise HTTPException(401, "missing bearer token")
        digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        for client in clients:
            if hmac.compare_digest(client["key_sha256"], digest):
                return client
        raise HTTPException(401, "invalid bearer token")

    def permitted(permission):
        def check(client=Depends(principal)):
            if permission not in client["permissions"]:
                raise HTTPException(403, "permission denied")
            return client

        return check

    read = permitted("read")
    write = permitted("write")
    admin = permitted("admin")

    @app.exception_handler(Conflict)
    async def conflict_handler(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(KeyError)
    async def missing_handler(request, error):
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @app.exception_handler(ValueError)
    async def value_handler(request, error):
        detail = "validation failed" if isinstance(error, ValidationError) else str(error)
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            service.graph.load()
            service.journal.jobs()
        except Exception:
            raise HTTPException(503, "storage unavailable") from None
        return {"status": "ready", "backend": settings.backend}

    @app.post("/v1/episodes", status_code=202)
    def ingest(message: Message, client=Depends(write)):
        episode_id, duplicate = service.ingest(message, client["id"])
        return {
            "episode_id": episode_id,
            "duplicate": duplicate,
            "processing": "inspect /v1/jobs; accepted is not indexed",
        }

    @app.get("/v1/episodes/{episode_id}")
    def source(episode_id: str, client=Depends(read)):
        payload = service.journal.get(episode_id)
        if payload is None:
            raise HTTPException(404, "source not found")
        return {"episode_id": episode_id, **payload}

    @app.post("/v1/search")
    async def retrieve(request: Query, client=Depends(read)):
        items = [public_node(n) for n in search(service.state, request)]
        facts = []
        if request.include_candidates and service.graphiti:
            try:
                async with service.lock:
                    candidates = await service.graphiti.search(request.query, request.limit)
                point = request.as_of or utcnow()
                facts = [
                    f
                    for f in candidates
                    if (not f["valid_from"] or f["valid_from"] <= point)
                    and (not f["valid_to"] or point < f["valid_to"])
                    and f["episode_ids"]
                    and all(service.journal.get(e) is not None for e in f["episode_ids"])
                ]
            except Exception:
                raise HTTPException(503, "graph retrieval unavailable") from None
        return {"items": items, "inferred_facts": facts, "scope": settings.scope}

    @app.post("/v1/context")
    def context(request: Query, client=Depends(read)):
        # Automatic context uses only reviewed active nodes by default.
        result = build_context(
            [public_node(n) for n in search(service.state, request)], request.max_chars
        )
        return {
            "scope": settings.scope,
            **result,
            "budget_unit": "characters",
            "policy": "quoted evidence, never system instructions",
        }

    @app.get("/v1/map")
    def graph(limit: int = URLQuery(default=500, ge=1, le=5000), client=Depends(read)):
        nodes = [
            public_node(n)
            for n in sorted(service.state["nodes"].values(), key=lambda n: n["id"])[:limit]
        ]
        ids = {n["id"] for n in nodes}
        edges = [
            e
            for e in service.state["edges"].values()
            if e["source_id"] in ids and e["target_id"] in ids
        ]
        return {
            "scope": settings.scope,
            "nodes": nodes,
            "edges": edges,
            "clusters": clusters(service.state),
            "total_nodes": len(service.state["nodes"]),
            "truncated": len(nodes) < len(service.state["nodes"]),
        }

    @app.post("/v1/nodes/{node_id}/review")
    async def review(node_id: str, request: Review, client=Depends(admin)):
        return await service.review(node_id, request.status, client["id"])

    @app.post("/v1/links", status_code=201)
    async def link(request: LinkInput, client=Depends(admin)):
        return await service.add_link(request, client["id"])

    @app.post("/v1/links/{edge_id}/review")
    async def review_link(edge_id: str, request: Review, client=Depends(admin)):
        return await service.review_link(edge_id, request.status, client["id"])

    @app.get("/v1/links")
    def links(
        status: str | None = URLQuery(default=None, pattern="^(candidate|confirmed|rejected)$"),
        relation: str | None = URLQuery(default=None),
        limit: int = URLQuery(default=200, ge=1, le=2000),
        client=Depends(read),
    ):
        """Edges with endpoint summaries and source quotes; proposals are ranked by score."""
        nodes = service.state["nodes"]
        rows = []
        for edge in service.state["edges"].values():
            if status and edge["status"] != status or relation and edge["relation"] != relation:
                continue
            if edge["source_id"] not in nodes or edge["target_id"] not in nodes:
                continue
            ends = {
                role: {
                    k: nodes[edge[role + "_id"]][k]
                    for k in ("id", "kind", "label", "summary", "status")
                }
                for role in ("source", "target")
            }
            rows.append({**edge, "source": ends["source"], "target": ends["target"]})
        rows.sort(key=lambda r: (-r.get("proposal", {}).get("score", 0), r["id"]))
        return {"links": rows[:limit], "total": len(rows)}

    @app.post("/v1/maintenance/propose")
    async def propose_links(client=Depends(admin)):
        try:
            return await service.propose_links(client["id"])
        except Exception:
            raise HTTPException(503, "proposal generation failed; nothing was changed") from None

    @app.get("/v1/jobs")
    def jobs(client=Depends(read)):
        return {"jobs": service.journal.jobs()}

    @app.post("/v1/jobs/{episode_id}/retry")
    def retry(episode_id: str, client=Depends(admin)):
        if not service.journal.retry(episode_id, client["id"]):
            raise HTTPException(409, "only failed jobs can be retried")
        return {"status": "pending"}

    @app.post("/v1/maintenance/consolidate")
    async def consolidation(client=Depends(admin)):
        return await service.consolidate(client["id"])

    @app.delete("/v1/episodes/{episode_id}")
    async def erase(episode_id: str, client=Depends(admin)):
        try:
            await service.erase(episode_id, client["id"])
        except KeyError:
            raise HTTPException(404, "source not found") from None
        except Exception:
            raise HTTPException(
                503, "deletion incomplete; retry before considering source erased"
            ) from None
        return {"status": "deleted_from_live_stores", "backups": "follow retention runbook"}

    @app.get("/v1/export")
    async def export(client=Depends(admin)):
        async with service.lock:
            with service.journal.db() as db:
                import json

                episodes = [
                    {"episode_id": row["id"], **json.loads(row["payload"])}
                    for row in db.execute("SELECT * FROM episodes WHERE deleted=0 ORDER BY id")
                ]
            service.journal.audit(client["id"], "export", settings.scope)
            return {
                "schema_version": 1,
                "scope": settings.scope,
                "episodes": episodes,
                "active_graph": {
                    **service.state,
                    "nodes": {k: public_node(v) for k, v in service.state["nodes"].items()},
                },
            }

    return app
