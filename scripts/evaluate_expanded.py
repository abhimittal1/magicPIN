from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.composer import ComposeService
from app.config import get_settings
from app.datasets import load_expanded_dataset, load_test_pairs
from app.evidence import EvidenceSelector
from app.llm_client import WordingService
from app.planner import PlanBuilder
from app.resolver import ContextResolver
from app.store import RuntimeStore
from app.validator import MessageValidator


def main() -> None:
    settings = get_settings()
    dataset = load_expanded_dataset(settings.dataset_expanded_dir)
    test_pairs = load_test_pairs(settings.test_pairs_path)
    resolver = ContextResolver(RuntimeStore())
    compose_service = ComposeService(
        planner=PlanBuilder(),
        evidence_selector=EvidenceSelector(),
        wording_service=WordingService(settings),
        validator=MessageValidator(),
    )

    output_path = Path("expanded-evaluation.jsonl")
    rows = []
    for pair in test_pairs:
        merchant = dataset["merchants"][pair["merchant_id"]]
        category = dataset["categories"][merchant["category_slug"]]
        trigger = dataset["triggers"][pair["trigger_id"]]
        customer = dataset["customers"].get(pair.get("customer_id"))
        resolved = resolver.resolve_contexts(category=category, merchant=merchant, trigger=trigger, customer=customer)
        plan = compose_service.plan(resolved)
        composed = compose_service.compose_resolved(resolved)
        rows.append(
            {
                "test_id": pair["test_id"],
                "trigger_id": pair["trigger_id"],
                "family": plan.trigger_family,
                "risk_flags": plan.risk_flags,
                "body": composed.body,
                "cta": composed.cta,
                "send_as": composed.send_as,
                "rationale": composed.rationale,
            }
        )

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Evaluated {len(rows)} canonical pairs into {output_path}")


if __name__ == "__main__":
    main()