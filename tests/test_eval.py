"""AM-002: the fixed Czech dataset is valid and the pipeline never regresses against its baseline."""

import json
from pathlib import Path

import pytest

from active_memory.evaluation import evaluate, load_dataset, to_payload

EVALS = Path(__file__).resolve().parents[1] / "evals"


@pytest.fixture(scope="module")
def dataset():
    return load_dataset(EVALS / "cs_v1.json")


@pytest.fixture(scope="module")
def report(dataset):
    return evaluate(dataset)


def test_dataset_is_large_hand_labelled_and_covers_required_categories(dataset):
    scenarios = len(dataset["queries"]) + len(dataset["pairs"])
    assert scenarios >= 30
    categories = {q["category"] for q in dataset["queries"]}
    assert {
        "paraphrase",
        "temporal",
        "irrelevant",
        "cross_chat_theme",
        "source_role",
        "hard_negative",
        "injection",
    } <= categories
    judgments = {p["judgment"] for p in dataset["pairs"]}
    assert {"same_theme", "same_thought", "distinct", "SUPERSEDES", "CONTRADICTS"} <= judgments
    roles = {m["role"] for m in dataset["messages"]}
    assert "assistant" in roles
    assert dataset["synthetic"] is True


def test_assistant_text_is_never_supplied_as_extraction(dataset):
    for message in dataset["messages"]:
        payload = to_payload(message, with_extraction=True)
        if message["role"] != "user":
            assert "extraction" not in payload


def test_invariants_hold_independently_of_model_quality(report):
    inv = report["invariants"]
    assert inv["evidence_quote_exact"] == 1.0 and inv["evidence_checked"] > 0
    assert inv["machine_nodes_not_candidate"] == 0
    assert inv["default_search_hides_candidates"]
    assert inv["context_within_budget"] and inv["context_marked_untrusted"]
    assert inv["non_user_evidence"] == 0
    assert report["model_cost"]["calls"] == 0
    assert report["linking"]["unresolved"] == 0


def test_metrics_do_not_regress_below_recorded_baseline(report):
    baseline = json.loads((EVALS / "baseline_cs_v1.json").read_text(encoding="utf-8"))
    now, before = report["retrieval"]["overall"], baseline["retrieval"]["overall"]
    for higher_is_better in ("precision", "recall"):
        assert now[higher_is_better] >= before[higher_is_better], higher_is_better
    for lower_is_better in ("violations", "future_evidence_items", "false_positives"):
        assert now[lower_is_better] <= before[lower_is_better], lower_is_better
    link, link_before = report["linking"], baseline["linking"]
    assert link["same_merge_recall"] >= link_before["same_merge_recall"]
    assert link["relation_recall"] >= link_before["relation_recall"]
    assert link["false_merge_rate"] <= link_before["false_merge_rate"]
    for category, row in baseline["retrieval"]["by_category"].items():
        assert report["retrieval"]["by_category"][category]["recall"] >= row["recall"], category


def test_evaluation_is_deterministic(dataset, report):
    again = evaluate(dataset)
    for key in ("counts", "retrieval", "linking", "invariants"):
        assert again[key] == report[key]
