from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.datasets import load_expanded_dataset, load_test_pairs
from bot import compose


def main() -> None:
    settings = get_settings()
    dataset = load_expanded_dataset(settings.dataset_expanded_dir)
    test_pairs = load_test_pairs(settings.test_pairs_path)
    output_path = Path("submission.jsonl")

    with output_path.open("w", encoding="utf-8") as handle:
        for pair in test_pairs:
            merchant = dataset["merchants"][pair["merchant_id"]]
            category = dataset["categories"][merchant["category_slug"]]
            trigger = dataset["triggers"][pair["trigger_id"]]
            customer = dataset["customers"].get(pair.get("customer_id"))
            result = compose(category=category, merchant=merchant, trigger=trigger, customer=customer)
            row = {
                "test_id": pair["test_id"],
                "body": result["body"],
                "cta": result["cta"],
                "send_as": result["send_as"],
                "suppression_key": result["suppression_key"],
                "rationale": result["rationale"],
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(test_pairs)} lines to {output_path}")


if __name__ == "__main__":
    main()