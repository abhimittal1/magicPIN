from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def load_category_map(base_dir: str | Path) -> dict[str, dict[str, Any]]:
    category_dir = Path(base_dir) / "categories"
    categories: dict[str, dict[str, Any]] = {}
    for path in sorted(category_dir.glob("*.json")):
        payload = load_json(path)
        categories[payload["slug"]] = payload
    return categories


def load_entity_map(base_dir: str | Path, folder: str, key_name: str) -> dict[str, dict[str, Any]]:
    entity_dir = Path(base_dir) / folder
    entities: dict[str, dict[str, Any]] = {}
    for path in sorted(entity_dir.glob("*.json")):
        payload = load_json(path)
        entities[payload[key_name]] = payload
    return entities


def load_expanded_dataset(expanded_dir: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    expanded_path = Path(expanded_dir)
    return {
        "categories": load_category_map(expanded_path),
        "merchants": load_entity_map(expanded_path, "merchants", "merchant_id"),
        "customers": load_entity_map(expanded_path, "customers", "customer_id"),
        "triggers": load_entity_map(expanded_path, "triggers", "id"),
    }


def load_seed_dataset(seed_dir: str | Path) -> dict[str, dict[str, Any]]:
    seed_path = Path(seed_dir)
    categories = load_category_map(seed_path)
    merchants = {item["merchant_id"]: item for item in load_json(seed_path / "merchants_seed.json")["merchants"]}
    customers = {item["customer_id"]: item for item in load_json(seed_path / "customers_seed.json")["customers"]}
    triggers = {item["id"]: item for item in load_json(seed_path / "triggers_seed.json")["triggers"]}
    return {
        "categories": categories,
        "merchants": merchants,
        "customers": customers,
        "triggers": triggers,
    }


def load_test_pairs(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    return payload.get("pairs", [])