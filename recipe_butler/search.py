"""Ingredient search: every term must be a case-insensitive substring of some ingredient name."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .catalog import DishView


@dataclass(frozen=True)
class SearchHit:
    dish_id: str
    name: str
    category: str
    matches: dict[str, list[str]]


def parse_terms(query: str) -> list[str]:
    terms: list[str] = []
    for part in re.split(r"[,+]", query):
        term = part.strip().casefold()
        if term and term not in terms:
            terms.append(term)
    return terms


def search(views: Iterable[DishView], terms: list[str]) -> list[SearchHit]:
    if not terms:
        return []
    hits: list[SearchHit] = []
    for view in views:
        if view.hidden:
            continue
        names = [i.name for i in view.dish.ingredients]
        matches = {term: [n for n in names if term.casefold() in n.casefold()] for term in terms}
        if all(matches.values()):
            hits.append(SearchHit(view.dish.id, view.dish.name, view.dish.category, matches))
    return sorted(hits, key=lambda h: h.name.casefold())
