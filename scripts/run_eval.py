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
    parser.add_argument("--output")
    args = parser.parse_args()
    overrides = {}
    if args.llm:
        from active_memory.settings import Settings

        configured = Settings()
        overrides = {
            k: getattr(configured, k)
            for k in ("model_base_url", "model_api_key", "model_name", "timeout_seconds")
        }
    report = evaluate(
        load_dataset(args.dataset),
        extraction="llm" if args.llm else "gold",
        settings_overrides=overrides,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
