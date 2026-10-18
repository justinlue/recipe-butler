"""Read-only seed recipes shipped with the app, one JSON file per dish."""

from __future__ import annotations

import json
from pathlib import Path

from .model import Dish, ValidationError, dish_from_dict

SEED_DIR = Path(__file__).resolve().parent / "seeds"


class SeedError(Exception):
    pass


def load_seeds(directory: Path = SEED_DIR) -> dict[str, Dish]:
    """Load every seed file; a bad seed raises SeedError naming the file instead of being skipped."""
    seeds: dict[str, Dish] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SeedError(f"{path.name}: cannot read seed recipe ({e})") from e
        try:
            dish = dish_from_dict(data, f"seed:{path.stem}")
        except ValidationError as e:
            raise SeedError(f"{path.name}: {' '.join(e.messages)}") from e
        seeds[dish.id] = dish
    return seeds
