"""Candidate links between ideas/themes (AM-003).

Everything here only *proposes*. A proposal is an ordinary graph edge with ``status: candidate`` and
``origin: proposal`` that cites exact quotes from both sides. Nothing is merged, nothing confirmed
and no node or source is changed; an owner reviews each edge and a rejected proposal is never revived.
Signals: embedding cosine (optional), lexical overlap, shared graph neighbours and cross-conversation
recurrence. Typed relations other than ALIAS_OF/SUPERSEDES come only from an optional judge.
"""

import hashlib
import re
import unicodedata
from datetime import datetime

from .engine import identity, normalize

STOPWORDS = frozenset(
    "a aby ale ani asi az bez bych by byl byla bylo byt co ci do i jak jako je jeho jej jen jeste "
    "jsem jsou k kdo kdy kde ktery ma mam me mi mit moc musi muze my na nad nebo nechci nejsem "
    "neni o od on po pod pro protoze pri se si s sve svuj ta tak tam te ten to tu u uz v ve vsak "
    "z za ze chci chtel bych bude bylo".split()
)
TYPED = ("SUPPORTS", "REFINES", "CONTRADICTS", "SUPERSEDES")
TEMPORAL_KINDS = {"Decision", "Fact", "Goal"}
ABOUT_SCOPE = "ABOUT"


def fold(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", normalize(text)) if not unicodedata.combining(c)
    )


def stems(text):
    """Crude Czech-friendly stems: no diacritics, no stopwords, first five letters."""
    out = set()
    for token in re.findall(r"[a-z0-9]+", fold(text)):
        if token not in STOPWORDS and len(token) > 2:
            out.add(token[:5])
    return out


def lexical_similarity(a, b):
    left, right = stems(a["label"] + " " + a["summary"]), stems(b["label"] + " " + b["summary"])
    shared = len(left & right)
    if shared < 2:  # one shared word is topic overlap, not similarity
        return 0.0
    return 0.5 * (shared / len(left | right) + shared / min(len(left), len(right)))


def embedding_text(node):
    return f"{node['label']}. {node['summary']}"


def text_hash(node):
    return hashlib.sha256(embedding_text(node).encode()).hexdigest()[:16]


def cosine(a, b):
    # Vectors are stored L2-normalised, so the dot product is the cosine.
    return sum(x * y for x, y in zip(a, b, strict=False))


def unit(vector):
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector] if norm else vector


def usable_vector(node, model):
    stored = node.get("embedding")
    if stored and stored["model"] == model and stored["text_hash"] == text_hash(node):
        return stored["vector"]
    return None


def neighbours(state):
    """Nodes a node is connected to by non-rejected ABOUT edges (themes of ideas, ideas of themes)."""
    result = {}
    for edge in state["edges"].values():
        if edge["relation"] != ABOUT_SCOPE or edge["status"] == "rejected":
            continue
        result.setdefault(edge["source_id"], set()).add(edge["target_id"])
        result.setdefault(edge["target_id"], set()).add(edge["source_id"])
    return result


def conversations(node):
    return {(e["source_system"], e["conversation_id"]) for e in node["evidence"]}


def crosses_conversations(a, b):
    """True when the two sides were expressed in at least two different chats."""
    return len(conversations(a) | conversations(b)) >= 2


def representative(node, other):
    """Most recent evidence, preferring a conversation the other side does not share."""
    other_chats = conversations(other)
    ordered = sorted(node["evidence"], key=lambda e: e["occurred_at"], reverse=True)
    for entry in ordered:
        if (entry["source_system"], entry["conversation_id"]) not in other_chats:
            return entry
    return ordered[0]


def recent_evidence(node, limit=4):
    """Newest quotes of a node, shown to the judge (and cited by it)."""
    return sorted(node["evidence"], key=lambda e: e["occurred_at"], reverse=True)[:limit]


def point(value):
    return datetime.fromisoformat(value) if value else None


def temporal_supersession(a, b, shared_theme):
    """Return (newer, older, score, reason) when decisions/facts/goals visibly follow each other."""
    if a["kind"] != b["kind"] or a["kind"] not in TEMPORAL_KINDS or not shared_theme:
        return None
    for newer, older in ((a, b), (b, a)):
        start, end = point(newer.get("valid_from")), point(older.get("valid_to"))
        if start and end and start == end:
            return (
                newer,
                older,
                0.9,
                "valid_from of the newer claim equals the exclusive valid_to of the older one",
            )
    return None


def pair_id(a, b):
    return tuple(sorted((a["id"], b["id"])))


def build_edge(source, target, relation, score, signals, reason, method, evidence, now):
    edge_id = identity(source["id"], relation, target["id"])
    return {
        "id": edge_id,
        "source_id": source["id"],
        "target_id": target["id"],
        "relation": relation,
        "status": "candidate",
        "origin": "proposal",
        "evidence": evidence,
        "proposal": {
            "score": round(score, 4),
            "signals": {k: round(v, 4) if isinstance(v, float) else v for k, v in signals.items()},
            "reason": reason,
            "method": method,
            "generated_at": now.isoformat(),
        },
    }


def evidence_pair(a, b):
    return [representative(a, b), representative(b, a)]


def candidate_pairs(state, vectors, threshold, only_ids=None):
    """Score same-kind node pairs from different chats; yield those at or above ``threshold``."""
    links = neighbours(state)
    nodes = sorted(state["nodes"].values(), key=lambda n: n["id"])
    for i, a in enumerate(nodes):
        for b in nodes[i + 1 :]:
            if a["kind"] != b["kind"] or a["status"] == "rejected" or b["status"] == "rejected":
                continue
            if only_ids is not None and a["id"] not in only_ids and b["id"] not in only_ids:
                continue
            if not crosses_conversations(a, b):
                continue
            lexical = lexical_similarity(a, b)
            shared = len(links.get(a["id"], set()) & links.get(b["id"], set()))
            graph = min(shared, 2) / 2
            vec_a, vec_b = vectors.get(a["id"]), vectors.get(b["id"])
            signals = {"lexical": lexical, "graph": graph}
            if vec_a and vec_b:
                signals["embedding"] = max(cosine(vec_a, vec_b), 0.0)
                score = 0.6 * signals["embedding"] + 0.25 * lexical + 0.15 * graph
            else:
                score = min(1.0, lexical + 0.25 * graph)  # shared neighbours are a bonus only
            signals["shared_neighbours"] = shared
            if score >= threshold:
                yield a, b, score, signals


def propose(state, vectors=None, threshold=0.6, verdicts=None, only_ids=None, now=None):
    """Return new candidate edges (not yet in ``state``) plus a report.

    ``verdicts`` maps ``pair_id(a, b)`` to a judge answer {"relation": SAME|SUPPORTS|REFINES|
    CONTRADICTS|SUPERSEDES|UNRELATED, "direction": "a_to_b"|"b_to_a", "reason": str}; it is the only
    source of typed relations beyond temporal supersession. When given, pairs without a verdict
    (judge budget exhausted) are not proposed at all.
    """
    from .models import utcnow

    now = now or utcnow()
    vectors = vectors or {}
    existing = set(state["edges"])
    new = {}
    skipped = {"existing_or_rejected": 0, "judged_unrelated": 0, "unjudged": 0}
    links = neighbours(state)
    nodes = state["nodes"]

    def add(edge):
        if edge["id"] in existing or edge["id"] in new:
            skipped["existing_or_rejected"] += 1  # includes rejected tombstones: never revived
        else:
            new[edge["id"]] = edge

    # Temporal supersession needs no similarity score: adjacency of validity windows is the signal.
    ordered = sorted(nodes.values(), key=lambda n: n["id"])
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if only_ids is not None and a["id"] not in only_ids and b["id"] not in only_ids:
                continue
            shared = links.get(a["id"], set()) & links.get(b["id"], set())
            found = temporal_supersession(a, b, shared)
            if found:
                newer, older, score, reason = found
                add(
                    build_edge(
                        newer,
                        older,
                        "SUPERSEDES",
                        score,
                        {"shared_neighbours": len(shared)},
                        reason,
                        "temporal",
                        evidence_pair(newer, older),
                        now,
                    )
                )

    for a, b, score, signals in candidate_pairs(state, vectors, threshold, only_ids):
        if verdicts is not None:
            verdict = verdicts.get(pair_id(a, b))
            if verdict is None:
                skipped["unjudged"] += 1
                continue
            if verdict["relation"] == "UNRELATED":
                skipped["judged_unrelated"] += 1
                continue
            relation = "ALIAS_OF" if verdict["relation"] == "SAME" else verdict["relation"]
            first, second = (b, a) if verdict.get("direction") == "b_to_a" else (a, b)
            add(
                build_edge(
                    first,
                    second,
                    relation,
                    score,
                    signals,
                    verdict["reason"],
                    "judge",
                    evidence_pair(first, second),
                    now,
                )
            )
        else:
            first, second = (a, b)
            reason = (
                "Similar wording/context across different chats; relation type not judged "
                "(could also be a CONTRADICTS or an unrelated near-duplicate)."
            )
            add(
                build_edge(
                    first,
                    second,
                    "ALIAS_OF",
                    score,
                    signals,
                    reason,
                    "similarity",
                    evidence_pair(first, second),
                    now,
                )
            )
    return new, skipped


def clusters(state):
    """Groups of nodes joined by *confirmed* ALIAS_OF edges, with aggregated recurrence.

    A view only: nodes, evidence and counts stay untouched and a rejected/removed edge splits it again.
    """
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for edge in state["edges"].values():
        if edge["relation"] == "ALIAS_OF" and edge["status"] == "confirmed":
            if edge["source_id"] in state["nodes"] and edge["target_id"] in state["nodes"]:
                parent[find(edge["source_id"])] = find(edge["target_id"])
    groups = {}
    for node_id in list(parent):
        groups.setdefault(find(node_id), []).append(node_id)
    result = []
    for members in groups.values():
        records = [state["nodes"][m] for m in members]
        evidence = [e for r in records for e in r["evidence"]]
        result.append(
            {
                "id": identity("cluster", *sorted(members)),
                "kind": records[0]["kind"],
                "members": sorted(members),
                "labels": sorted(r["label"] for r in records),
                "strength": len({e["episode_id"] for e in evidence}),
                "conversation_count": len(
                    {(e["source_system"], e["conversation_id"]) for e in evidence}
                ),
            }
        )
    return sorted(result, key=lambda c: c["id"])
