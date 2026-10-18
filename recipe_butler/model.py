"""Dish model: normalization, validation, and the stable hash used to detect seed changes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Ingredient:
    name: str
    amount: str = ""


@dataclass(frozen=True)
class Dish:
    id: str
    name: str
    description: str
    servings: int | None
    total_minutes: int | None
    category: str
    ingredients: tuple[Ingredient, ...]
    steps: tuple[str, ...]


class ValidationError(ValueError):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


def _text(value: object, label: str, errors: list[str]) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        errors.append(f"{label} must be text.")
        return ""
    return value.strip()


def _number(value: object, label: str, minimum: int, errors: list[str]) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        errors.append(f"{label} must be a whole number of at least {minimum}.")
        return None
    return value


def dish_from_dict(data: object, dish_id: str) -> Dish:
    """Normalize and validate raw dish data; raises ValidationError listing every problem."""
    if not isinstance(data, dict):
        raise ValidationError(["Expected a dish object."])
    errors: list[str] = []

    name = _text(data.get("name"), "Name", errors)
    description = _text(data.get("description"), "Description", errors)
    category = _text(data.get("category"), "Category", errors) or "Uncategorized"
    servings = _number(data.get("servings"), "Servings", 1, errors)
    total_minutes = _number(data.get("total_minutes"), "Total time", 0, errors)

    ingredients: list[Ingredient] = []
    raw_ingredients = data.get("ingredients", [])
    if not isinstance(raw_ingredients, list):
        errors.append("Ingredients must be a list.")
        raw_ingredients = []
    for position, row in enumerate(raw_ingredients, start=1):
        if not isinstance(row, dict):
            errors.append(f"Ingredient {position} must have a name and an amount.")
            continue
        ing_name = _text(row.get("name"), f"Ingredient {position} name", errors)
        amount = _text(row.get("amount"), f"Ingredient {position} amount", errors)
        if not ing_name and not amount:
            continue
        if not ing_name:
            errors.append(f"Ingredient {position} needs a name.")
            continue
        ingredients.append(Ingredient(ing_name, amount))

    steps: list[str] = []
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        errors.append("Steps must be a list.")
        raw_steps = []
    for position, step in enumerate(raw_steps, start=1):
        text = _text(step, f"Step {position}", errors)
        if text:
            steps.append(text)

    if not name:
        errors.insert(0, "Name is required.")
    if not ingredients:
        errors.append("Add at least one ingredient.")
    if not steps:
        errors.append("Add at least one step.")
    if errors:
        raise ValidationError(errors)

    return Dish(dish_id, name, description, servings, total_minutes, category, tuple(ingredients), tuple(steps))


def dish_to_dict(dish: Dish) -> dict:
    return {
        "id": dish.id,
        "name": dish.name,
        "description": dish.description,
        "servings": dish.servings,
        "total_minutes": dish.total_minutes,
        "category": dish.category,
        "ingredients": [{"name": i.name, "amount": i.amount} for i in dish.ingredients],
        "steps": list(dish.steps),
    }


def seed_hash(dish: Dish) -> str:
    canonical = json.dumps(dish_to_dict(dish), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
