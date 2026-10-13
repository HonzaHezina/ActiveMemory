import asyncio
import copy
import re

from .engine import add_extraction, consolidate, identity, remove_episode
from .graph import Neo4jGraph, ReferenceGraph
from .journal import Journal
from .models import Extraction, Message, utcnow
from .providers import GraphitiAdapter, LLMExtractor, LLMRelationJudge, OpenAIEmbeddings
from .similarity import (
    candidate_pairs,
    embedding_text,
    pair_id,
    propose,
    recent_evidence,
    text_hash,
    unit,
    usable_vector,
)


class MemoryService:
    def __init__(self, settings):
        self.settings = settings
        self.journal = Journal(settings.data_dir, settings.scope)
        self.graph = (
            Neo4jGraph(settings)
            if settings.backend == "neo4j"
            else ReferenceGraph(settings.data_dir, settings.scope)
        )
        self.state = self.graph.load()
        self.lock = asyncio.Lock()
        self.extractor = LLMExtractor(settings) if settings.extraction_mode == "llm" else None
        self.graphiti = GraphitiAdapter(settings) if settings.graphiti_enabled else None
        self.embedder = (
            OpenAIEmbeddings(settings) if settings.similarity_mode == "embedding" else None
        )
        self.judge = LLMRelationJudge(settings) if settings.judge_enabled else None

    async def initialize(self):
        if self.graphiti:
            await self.graphiti.initialize()

    def ingest(self, message, actor):
        # Minimal known credential filter. This does not certify arbitrary raw messages as secret-free.
        if re.search(
            r"(?:sk-[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----|"
            r"(?i:password|api[_-]?key|access[_-]?token)\s*[:=]\s*\S{8,})",
            message.content,
        ):
            raise ValueError("possible credential detected; redact before ingestion")
        return self.journal.ingest(message, actor)

    async def process_one(self):
        async with self.lock:
            episode_id = self.journal.claim()
            if not episode_id:
                return False
            payload = self.journal.get(episode_id)
            if not payload:
                return False
            try:
                message = Message.model_validate(payload)
                extraction = message.extraction
                # Assistant/tool/system text is kept as raw provenance, not auto-promoted to knowledge.
                if extraction is None and self.extractor and message.role == "user":
                    themes = [
                        n["label"] for n in self.state["nodes"].values() if n["kind"] == "Theme"
                    ]
                    extraction = await self.extractor.extract(message, themes)
                if self.graphiti and message.role == "user":
                    await self.graphiti.add(episode_id, message)
                updated = copy.deepcopy(self.state)
                before = set(updated["nodes"])
                add_extraction(updated, episode_id, message, extraction or Extraction())
                self.commit(updated)
                self.journal.finish(episode_id)
                if self.settings.auto_propose:
                    # Best effort and separate from ingestion: a provider failure must not fail the job.
                    try:
                        await self._propose(before=before)
                    except Exception as error:
                        self.journal.audit("system", "auto_propose_failed", type(error).__name__)
            except Exception as error:
                # Only exception class is persisted; upstream errors may contain sensitive text.
                self.journal.finish(episode_id, type(error).__name__)
            return True

    def commit(self, state):
        self.graph.save(state)
        self.state = state

    async def worker(self):
        while True:
            processed = await self.process_one()
            if not processed:
                await asyncio.sleep(self.settings.poll_seconds)

    async def review(self, node_id, status, actor):
        async with self.lock:
            if node_id not in self.state["nodes"]:
                raise KeyError(node_id)
            updated = copy.deepcopy(self.state)
            updated["nodes"][node_id]["status"] = status
            # Review does not silently validate relations or other claims.
            self.commit(updated)
            self.journal.audit(actor, "review_" + status, node_id)
            return updated["nodes"][node_id]

    async def add_link(self, link, actor):
        async with self.lock:
            if link.source_id == link.target_id:
                raise ValueError("self links are not supported")
            if any(key not in self.state["nodes"] for key in (link.source_id, link.target_id)):
                raise KeyError("unknown node")
            episode = self.journal.get(link.episode_id)
            if not episode or link.quote not in episode["content"]:
                raise ValueError("link needs an exact quote in a live source episode")
            updated = copy.deepcopy(self.state)
            edge_id = identity(
                link.source_id, link.relation, link.target_id, link.episode_id, link.quote
            )
            updated["edges"][edge_id] = {
                "id": edge_id,
                **link.model_dump(mode="json"),
                "status": "candidate",
                "evidence": [{"episode_id": link.episode_id, "quote": link.quote}],
            }
            self.commit(updated)
            self.journal.audit(actor, "link_proposal", edge_id)
            return updated["edges"][edge_id]

    async def review_link(self, edge_id, status, actor):
        async with self.lock:
            if edge_id not in self.state["edges"]:
                raise KeyError(edge_id)
            updated = copy.deepcopy(self.state)
            edge = updated["edges"][edge_id]
            # A change relation is information; temporal windows remain explicit reviewed data.
            edge["status"] = status
            if status == "rejected" and edge.get("origin") == "proposal":
                edge["rejected_at"] = utcnow().isoformat()
            self.commit(updated)
            self.journal.audit(actor, "review_link_" + status, edge_id)
            return edge

    async def propose_links(self, actor):
        async with self.lock:
            report = await self._propose()
            self.journal.audit(actor, "propose_links", f"{report['proposed']}")
            return report

    async def _propose(self, before=None):
        """Create candidate edges. ``before``: node ids already examined (only new ones are paired)."""
        s = self.settings
        updated = copy.deepcopy(self.state)
        only_ids = None
        if before is not None:
            only_ids = set(updated["nodes"]) - before
            if not only_ids:
                return {"proposed": 0, "edges": [], "skipped": {}, "usage": {}}
        vectors = {}
        if self.embedder:
            missing = [
                n
                for n in updated["nodes"].values()
                if n["status"] != "rejected" and not usable_vector(n, self.embedder.model)
            ]
            if missing:
                for node, vector in zip(
                    missing,
                    await self.embedder.embed([embedding_text(n) for n in missing]),
                    strict=True,
                ):
                    node["embedding"] = {
                        "model": self.embedder.model,
                        "dim": len(vector),
                        "text_hash": text_hash(node),
                        "vector": unit(vector),
                    }
            vectors = {
                n["id"]: usable_vector(n, self.embedder.model) for n in updated["nodes"].values()
            }
            vectors = {k: v for k, v in vectors.items() if v}
        verdicts = None
        if self.judge:
            verdicts = {}
            ranked = sorted(
                candidate_pairs(updated, vectors, s.effective_threshold, only_ids),
                key=lambda row: -row[2],
            )[: s.max_judge_calls]
            for a, b, _, _ in ranked:
                try:
                    verdicts[pair_id(a, b)] = await self.judge.judge(
                        a, b, recent_evidence(a), recent_evidence(b)
                    )
                except Exception as error:  # an invalid verdict is dropped, never guessed
                    self.journal.audit("system", "judge_rejected", type(error).__name__)
        new, skipped = propose(updated, vectors, s.effective_threshold, verdicts, only_ids)
        updated["edges"].update(new)
        self.commit(updated)
        usage = {
            "embedder": getattr(self.embedder, "usage", {}),
            "judge": getattr(self.judge, "usage", {}),
        }
        return {
            "proposed": len(new),
            "edges": sorted(new),
            "skipped": skipped,
            "threshold": s.effective_threshold,
            "mode": s.similarity_mode + ("+judge" if self.judge else ""),
            "usage": usage,
        }

    async def consolidate(self, actor):
        async with self.lock:
            updated = copy.deepcopy(self.state)
            report = consolidate(updated)
            self.commit(updated)
            self.journal.audit(actor, "consolidate", self.settings.scope)
            return report

    async def erase(self, episode_id, actor):
        async with self.lock:
            payload = self.journal.get(episode_id)
            if not payload:
                raise KeyError(episode_id)
            if self.graphiti and payload["role"] == "user":
                await self.graphiti.rebuild_without(episode_id, self.journal)
            updated = copy.deepcopy(self.state)
            remove_episode(updated, episode_id)
            self.commit(updated)
            self.journal.erase(episode_id, actor)

    async def close(self):
        self.graph.close()
        if self.graphiti:
            await self.graphiti.close()
