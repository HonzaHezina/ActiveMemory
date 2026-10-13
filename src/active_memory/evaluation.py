"""Fixed-dataset evaluation of the memory pipeline (AM-002).

Runs the real ingest -> job -> active graph -> search/context code in process. The dataset holds the
human gold labels; nothing here asks a model to judge a model. By default the gold extraction is
supplied (``provided`` mode: no model, no cost), so the numbers measure linking, retrieval,
temporal correctness and provenance. ``extraction="llm"`` instead measures an extractor against the
same gold labels and reports its call/token usage.
"""

import asyncio
import json
import statistics
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .engine import build_context, normalize, search
from .models import Message, Query
from .service import MemoryService
from .settings import Settings
from .similarity import clusters

OWNER_ID = "eval"
KEY_PLACEHOLDER = "eval-only-key-not-used-for-auth-0000"


def load_dataset(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_dataset(data)
    return data


def validate_dataset(data):
    """Structural + annotation sanity: exact quotes, known concepts/themes, resolvable refs."""
    ids = [m["id"] for m in data["messages"]]
    assert len(ids) == len(set(ids)), "duplicate message ids"
    for message in data["messages"]:
        for item in message["gold"]:
            assert item["quote"] in message["content"], f"{message['id']}: quote not in content"
            assert item["concept"] in data["concepts"], f"{message['id']}: unknown concept"
            for theme in item["themes"]:
                assert theme["theme"] in data["themes"], f"{message['id']}: unknown theme"
        assert message["role"] == "user" or not message["gold"], "assistant text must stay raw"
        for quote in message.get("forbidden_quotes", []):
            assert quote in message["content"], f"{message['id']}: forbidden quote not in content"
    for query in data["queries"]:
        for key, vocabulary in (
            ("expect_concepts", data["concepts"]),
            ("forbid_concepts", data["concepts"]),
            ("expect_themes", data["themes"]),
            ("forbid_themes", data["themes"]),
        ):
            for name in query.get(key, []):
                assert name in vocabulary, f"{query['id']}: unknown {name}"
    by_id = {m["id"]: m for m in data["messages"]}
    for pair in data["pairs"]:
        for side in ("a", "b"):
            resolve_ref(by_id, pair[side])


def resolve_ref(by_id, ref):
    message_id, _, spec = ref.partition("#")
    message = by_id[message_id]
    if spec.startswith("item"):
        return message, message["gold"][int(spec[4:])], None
    index = int(spec[5:])
    item = message["gold"][0]
    return message, item, item["themes"][index]


def to_payload(message, with_extraction):
    payload = {
        "source_system": "eval-cs",
        "conversation_id": message["conversation"],
        "message_id": message["id"],
        "role": message["role"],
        "content": message["content"],
        "occurred_at": message["at"],
    }
    if with_extraction and message["role"] == "user":
        items = []
        for item in message["gold"]:
            entry = {k: item[k] for k in ("kind", "label", "summary", "quote") if k in item} | {
                "themes": [t["label"] for t in item["themes"]],
                "confidence": 0.8,
            }
            for key in ("valid_from", "valid_to"):
                if key in item:
                    entry[key] = item[key]
            items.append(entry)
        payload["extraction"] = {"items": items}
    return payload


def percentile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def latency(values):
    return {
        "mean_ms": round(statistics.fmean(values), 2) if values else 0.0,
        "p95_ms": round(percentile(values, 0.95), 2),
    }


def gold_messages(data, concepts=(), themes=()):
    found = set()
    for message in data["messages"]:
        for item in message["gold"]:
            if item["concept"] in concepts or any(t["theme"] in themes for t in item["themes"]):
                found.add(message["id"])
    return found


def evaluate(data, workdir=None, extraction="gold", settings_overrides=None, proposals=False):
    """Return a metrics report. ``extraction``: ``gold`` (provided labels) or ``llm``."""
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(workdir) if workdir else Path(temporary)
        settings = Settings(
            _env_file=None,
            data_dir=directory,
            clients_file=directory / "none.json",
            api_key=KEY_PLACEHOLDER,
            worker_enabled=False,
            **(
                {"extraction_mode": "llm", "allow_model_calls": True} if extraction == "llm" else {}
            ),
            **(settings_overrides or {}),
        )
        return asyncio.run(_evaluate(data, settings, extraction, proposals))


async def _evaluate(data, settings, extraction, proposals):
    service = MemoryService(settings)
    await service.initialize()
    try:
        episode_of, ingest_ms = {}, []
        for message in data["messages"]:
            payload = to_payload(message, with_extraction=extraction == "gold")
            started = time.perf_counter()
            episode_id, _ = service.ingest(Message.model_validate(payload), OWNER_ID)
            episode_of[message["id"]] = episode_id
            while await service.process_one():
                pass
            ingest_ms.append((time.perf_counter() - started) * 1000)
        assert all(j["status"] == "done" for j in service.journal.jobs()), "ingest job failed"
        report = {
            "dataset": data["name"],
            "extraction": extraction,
            "counts": {
                "messages": len(data["messages"]),
                "queries": len(data["queries"]),
                "pairs": len(data["pairs"]),
                "nodes": len(service.state["nodes"]),
                "edges": len(service.state["edges"]),
            },
            "latency": {"ingest_and_process": latency(ingest_ms)},
        }
        if extraction == "llm":
            report["extraction_quality"] = extraction_quality(data, service)
            usage = getattr(service.extractor, "usage", {})
            report["model_cost"] = {**usage, "price_usd": None}
        else:
            report["model_cost"] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        report["retrieval"], report["latency"]["query"] = evaluate_queries(
            data, service, episode_of
        )
        report["linking"] = evaluate_pairs(data, service, episode_of)
        report["invariants"] = evaluate_invariants(data, service)
        if proposals:
            started = time.perf_counter()
            report["propose_run"] = await service._propose()
            report["latency"]["propose"] = {
                "total_ms": round((time.perf_counter() - started) * 1000, 2)
            }
            report["proposals"] = evaluate_proposals(data, service, episode_of)
            oracle_review(data, service, episode_of)
            report["retrieval_after_oracle_review"], _ = evaluate_queries(data, service, episode_of)
            report["clusters_after_oracle_review"] = len(clusters(service.state))
        return report
    finally:
        await service.close()


def evidence_messages(node):
    return {e["message_id"] for e in node["evidence"]}


def evaluate_queries(data, service, episode_of):
    categories = defaultdict(list)
    query_ms = []
    details = []
    for spec in data["queries"]:
        expected = gold_messages(
            data, spec.get("expect_concepts", ()), spec.get("expect_themes", ())
        )
        forbidden = gold_messages(
            data, spec.get("forbid_concepts", ()), spec.get("forbid_themes", ())
        )
        started = time.perf_counter()
        request = Query(
            query=spec["query"], include_candidates=True, as_of=spec.get("as_of"), limit=12
        )
        items = search(service.state, request)
        query_ms.append((time.perf_counter() - started) * 1000)
        returned = set().union(*(evidence_messages(n) for n in items)) if items else set()
        useful = [n for n in items if evidence_messages(n) & expected]
        violations = sorted(violating_messages(items, forbidden, spec.get("forbid_quotes", ())))
        future = future_evidence_items(items, spec.get("as_of"))
        covered = len(returned & expected)
        row = {
            "id": spec["id"],
            "category": spec["category"],
            "precision": (len(useful) / len(items)) if items else 1.0,
            "recall": (covered / len(expected)) if expected else 1.0,
            "returned": len(items),
            "violations": violations,
            "future_evidence_items": future,
            "false_positive": bool(spec.get("expect_none") and items),
        }
        details.append(row)
        categories[spec["category"]].append(row)
    summary = {
        category: {
            "queries": len(rows),
            "precision": round(statistics.fmean(r["precision"] for r in rows), 4),
            "recall": round(statistics.fmean(r["recall"] for r in rows), 4),
            "violations": sum(len(r["violations"]) for r in rows),
            "future_evidence_items": sum(r["future_evidence_items"] for r in rows),
            "false_positives": sum(r["false_positive"] for r in rows),
        }
        for category, rows in sorted(categories.items())
    }
    overall = {
        "precision": round(statistics.fmean(r["precision"] for r in details), 4),
        "recall": round(statistics.fmean(r["recall"] for r in details), 4),
        "violations": sum(len(r["violations"]) for r in details),
        "future_evidence_items": sum(r["future_evidence_items"] for r in details),
        "false_positives": sum(r["false_positive"] for r in details),
    }
    return {"overall": overall, "by_category": summary, "queries": details}, latency(query_ms)


def violating_messages(items, forbidden, forbidden_quotes):
    """Forbidden sources that a returned item stands for.

    A Theme is a timeless grouping, so it only violates when all of its evidence is forbidden;
    any other item violates when it cites a forbidden source. Quote bans apply to every item.
    """
    found = set()
    for node in items:
        messages = evidence_messages(node)
        if node["kind"] == "Theme":
            if messages and messages <= forbidden:
                found |= messages
        else:
            found |= messages & forbidden
        for evidence in node["evidence"]:
            if any(quote in evidence["quote"] for quote in forbidden_quotes):
                found.add(evidence["message_id"])
    return found


def future_evidence_items(items, as_of):
    """Returned items citing a message written after the as-of point (anachronistic context)."""
    if not as_of:
        return 0
    point = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    return sum(
        any(datetime.fromisoformat(e["occurred_at"]) > point for e in node["evidence"])
        for node in items
    )


def system_node(data, service, episode_of, ref):
    by_id = {m["id"]: m for m in data["messages"]}
    message, item, theme = resolve_ref(by_id, ref)
    episode_id = episode_of[message["id"]]
    for node in service.state["nodes"].values():
        if not any(e["episode_id"] == episode_id for e in node["evidence"]):
            continue
        if theme is not None:
            if node["kind"] == "Theme" and normalize(node["label"]) == normalize(theme["label"]):
                return node
        elif node["kind"] == item["kind"] and normalize(node["label"]) == normalize(item["label"]):
            return node
    return None


def evaluate_pairs(data, service, episode_of):
    counts = defaultdict(int)
    missed = []
    for pair in data["pairs"]:
        a = system_node(data, service, episode_of, pair["a"])
        b = system_node(data, service, episode_of, pair["b"])
        judgment = pair["judgment"]
        if a is None or b is None:
            counts["unresolved"] += 1
            missed.append(pair["id"])
            continue
        if judgment.startswith("same_"):
            counts["same_total"] += 1
            counts["same_merged"] += a["id"] == b["id"]
            if a["id"] != b["id"]:
                missed.append(pair["id"])
        elif judgment == "distinct":
            counts["distinct_total"] += 1
            counts["false_merges"] += a["id"] == b["id"]
        else:
            counts["relation_total"] += 1
            symmetric = judgment == "CONTRADICTS"
            found = any(
                e["relation"] == judgment
                and (
                    (e["source_id"], e["target_id"]) == (a["id"], b["id"])
                    or (symmetric and (e["source_id"], e["target_id"]) == (b["id"], a["id"]))
                )
                for e in service.state["edges"].values()
            )
            counts["relation_found"] += found
            if not found:
                missed.append(pair["id"])
    ratio = lambda n, d: round(n / d, 4) if d else None  # noqa: E731
    return {
        "same_merge_recall": ratio(counts["same_merged"], counts["same_total"]),
        "false_merge_rate": ratio(counts["false_merges"], counts["distinct_total"]),
        "relation_recall": ratio(counts["relation_found"], counts["relation_total"]),
        "unresolved": counts["unresolved"],
        "counts": dict(counts),
        "missed_pairs": missed,
    }


def evaluate_invariants(data, service):
    """Properties that must hold regardless of model quality."""
    quotes_ok = checked = 0
    for node in list(service.state["nodes"].values()) + list(service.state["edges"].values()):
        for evidence in node["evidence"]:
            checked += 1
            source = service.journal.get(evidence["episode_id"])
            quotes_ok += bool(source and evidence["quote"] in source["content"])
    machine_confirmed = sum(n["status"] != "candidate" for n in service.state["nodes"].values())
    default = search(service.state, Query(query="lidská kontrola"))
    context = build_context(
        search(service.state, Query(query="lidská kontrola", include_candidates=True)), 2000
    )
    assistant_nodes = sum(
        e["role"] != "user" for n in service.state["nodes"].values() for e in n["evidence"]
    )
    return {
        "evidence_checked": checked,
        "evidence_quote_exact": round(quotes_ok / checked, 4) if checked else 1.0,
        "machine_nodes_not_candidate": machine_confirmed,
        "default_search_hides_candidates": default == [],
        "context_within_budget": context["used_chars"] <= 2000,
        "context_marked_untrusted": "untrusted" in context["text"].splitlines()[0],
        "non_user_evidence": assistant_nodes,
    }


def extraction_quality(data, service):
    """LLM mode: compare extracted evidence quotes with gold quotes (overlap = same span)."""
    matched = gold_total = spurious = extracted = 0
    for message in data["messages"]:
        found = [
            e["quote"]
            for n in service.state["nodes"].values()
            for e in n["evidence"]
            if e["message_id"] == message["id"]
        ]
        extracted += len(found)
        if not message["gold"]:
            spurious += len(found)
        for item in message["gold"]:
            gold_total += 1
            matched += any(item["quote"] in q or q in item["quote"] for q in found)
    return {
        "gold_items": gold_total,
        "matched": matched,
        "recall": round(matched / gold_total, 4) if gold_total else None,
        "extracted_evidence": extracted,
        "spurious_on_empty_gold": spurious,
    }


def pair_judgments(data, service, episode_of):
    """{frozenset(node ids): judgment} for gold pairs both of whose sides exist."""
    found = {}
    for pair in data["pairs"]:
        a = system_node(data, service, episode_of, pair["a"])
        b = system_node(data, service, episode_of, pair["b"])
        if a and b and a["id"] != b["id"]:
            found[frozenset((a["id"], b["id"]))] = (pair["judgment"], a["id"], b["id"])
    return found


def proposal_verdict(edge, judged):
    """correct / wrong / unjudged for one proposal edge against the gold pair judgments."""
    entry = judged.get(frozenset((edge["source_id"], edge["target_id"])))
    if entry is None:
        return "unjudged"
    judgment, a_id, b_id = entry
    if judgment.startswith("same_"):
        return "correct" if edge["relation"] == "ALIAS_OF" else "wrong"
    if judgment == "distinct":
        return "wrong"
    if edge["relation"] != judgment:
        return "wrong"
    forward = (edge["source_id"], edge["target_id"]) == (a_id, b_id)
    return "correct" if forward or judgment == "CONTRADICTS" else "wrong"


def evaluate_proposals(data, service, episode_of):
    judged = pair_judgments(data, service, episode_of)
    edges = [e for e in service.state["edges"].values() if e.get("origin") == "proposal"]
    verdicts = [proposal_verdict(e, judged) for e in edges]
    gold_links = [j for j in judged.values() if j[0] != "distinct"]
    recovered = sum(
        any(
            proposal_verdict(e, judged) == "correct"
            and frozenset((e["source_id"], e["target_id"])) == frozenset((a, b))
            for e in edges
        )
        for _, a, b in gold_links
    )
    sourced = sum(
        len(e["evidence"]) >= 2
        and all(
            (src := service.journal.get(x["episode_id"])) and x["quote"] in src["content"]
            for x in e["evidence"]
        )
        for e in edges
    )
    judged_total = verdicts.count("correct") + verdicts.count("wrong")
    return {
        "total": len(edges),
        "by_relation": {
            r: sum(e["relation"] == r for e in edges)
            for r in sorted({e["relation"] for e in edges})
        },
        "all_candidate": all(e["status"] == "candidate" for e in edges),
        "all_sourced": sourced == len(edges),
        "correct": verdicts.count("correct"),
        "wrong": verdicts.count("wrong"),
        "unjudged": verdicts.count("unjudged"),
        "precision_on_judged": round(verdicts.count("correct") / judged_total, 4)
        if judged_total
        else None,
        "gold_links": len(gold_links),
        "gold_links_recovered": recovered,
        "recall": round(recovered / len(gold_links), 4) if gold_links else None,
        "false_proposals_on_distinct": sum(
            judged[frozenset((e["source_id"], e["target_id"]))][0] == "distinct"
            for e in edges
            if frozenset((e["source_id"], e["target_id"])) in judged
        ),
    }


def oracle_review(data, service, episode_of):
    """Stand-in for the owner: confirm gold-correct proposals, reject the wrong ones (eval only)."""
    judged = pair_judgments(data, service, episode_of)
    for edge in service.state["edges"].values():
        if edge.get("origin") == "proposal":
            verdict = proposal_verdict(edge, judged)
            if verdict == "correct":
                edge["status"] = "confirmed"
            elif verdict == "wrong":
                edge["status"] = "rejected"
