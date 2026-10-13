"""Run the fixed evaluation dataset and print/save the metrics report.

Default is offline (gold extraction supplied, no model, zero cost). ``--llm`` measures the configured
extractor against the same gold labels; it needs MEMORY_MODEL_* settings and sends the synthetic
sentences to that provider.
"""

import argparse
import json
from pathlib import Path

from active_memory.evaluation import evaluate, load_dataset

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "evals/cs_v1.json"))
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--proposals", action="store_true", help="also run AM-003 link proposals")
    parser.add_argument(
        "--embeddings", action="store_true", help="proposals use MEMORY_EMBEDDING_*"
    )
    parser.add_argument("--judge", action="store_true", help="proposals use the LLM relation judge")
    parser.add_argument("--output")
    args = parser.parse_args()
    overrides = {}
    if args.llm or args.embeddings or args.judge:
        from active_memory.settings import Settings

        configured = Settings()
        keys = ["timeout_seconds"]
        if args.llm or args.judge:
            keys += ["model_base_url", "model_api_key", "model_name"]
        if args.embeddings:
            keys += ["embedding_base_url", "embedding_api_key", "embedding_model"]
            overrides["similarity_mode"] = "embedding"
        if args.judge:
            overrides["judge_enabled"] = True
        if args.embeddings or args.judge:
            overrides["allow_model_calls"] = True
        overrides |= {k: getattr(configured, k) for k in keys}
    report = evaluate(
        load_dataset(args.dataset),
        extraction="llm" if args.llm else "gold",
        settings_overrides=overrides,
        proposals=args.proposals or args.embeddings or args.judge,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
