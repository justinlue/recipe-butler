"""Merges read-only seeds with the user's store into effective dish views.

A customized seed shows its personal version (the override's ingredients and steps on top of the
seed's other fields); the original stays available for comparison and revert.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from typing import Literal

from .model import Dish, Ingredient, ValidationError, dish_from_dict, dish_to_dict, seed_hash
from .notes import image_refs, parse_note
from .store import Note, Store, utc_now

MAX_STARS = 5
MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Raster formats only: an SVG served from this origin could run script.
IMAGE_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg",
                    b"GIF87a": "image/gif", b"GIF89a": "image/gif"}


class NotFound(KeyError):
    pass


class CatalogError(Exception):
    """The operation is not allowed for this kind of dish."""


@dataclass(frozen=True)
class DishView:
    dish: Dish
    source: Literal["seed", "user"]
    customized: bool
    hidden: bool
    original: Dish | None
    original_updated: bool
    changed_ingredients: tuple[bool, ...]
    changed_steps: tuple[bool, ...]
    rating: int | None = None


SortOrder = Literal["category", "rating", "time"]

# Sort keys for the dish list: highest rating first, quickest first; unrated/untimed dishes go last.
SORT_KEYS = {
    "category": lambda v: v.dish.category.casefold(),
    "rating": lambda v: -(v.rating or 0),
    "time": lambda v: (v.dish.total_minutes is None, v.dish.total_minutes or 0),
}


def _user_num(dish_id: str) -> int | None:
    prefix, _, rest = dish_id.partition(":")
    if prefix == "user" and rest.isdigit():
        return int(rest)
    return None


def _embedded_images(notes: list[Note]) -> set[int]:
    return set().union(*(image_refs(n.body) for n in notes))


class Catalog:
    def __init__(self, seeds: dict[str, Dish], store: Store):
        self.seeds = seeds
        self.store = store

    # -- reading -------------------------------------------------------------

    def _seed_view(self, seed: Dish, overrides: dict, hidden: set[str], ratings: dict[str, int]) -> DishView:
        override = overrides.get(seed.id)
        is_hidden = seed.id in hidden
        rating = ratings.get(seed.id)
        if override is None:
            return DishView(seed, "seed", False, is_hidden, None, False,
                            (False,) * len(seed.ingredients), (False,) * len(seed.steps), rating)
        dish = replace(seed, ingredients=tuple(Ingredient(i["name"], i.get("amount", "")) for i in override.ingredients),
                       steps=tuple(override.steps))
        return DishView(
            dish, "seed", True, is_hidden, seed, override.seed_hash != seed_hash(seed),
            tuple(i not in seed.ingredients for i in dish.ingredients),
            tuple(s not in seed.steps for s in dish.steps),
            rating,
        )

    @staticmethod
    def _user_view(num: int, data: dict, ratings: dict[str, int]) -> DishView:
        dish = dish_from_dict(data, f"user:{num}")
        return DishView(dish, "user", False, False, None, False,
                        (False,) * len(dish.ingredients), (False,) * len(dish.steps), ratings.get(dish.id))

    def _all_views(self) -> list[DishView]:
        overrides, hidden, ratings = self.store.overrides(), self.store.hidden_ids(), self.store.ratings()
        views = [self._seed_view(seed, overrides, hidden, ratings) for seed in self.seeds.values()]
        views += [self._user_view(num, data, ratings) for num, data in self.store.user_dishes().items()]
        return views

    def list_views(self, include_hidden: bool = False, sort: SortOrder = "category") -> list[DishView]:
        """Dishes in the requested order; every order breaks ties by name."""
        if sort not in SORT_KEYS:
            raise ValidationError([f"Unknown sort order: {sort}."])
        views = [v for v in self._all_views() if include_hidden or not v.hidden]
        return sorted(views, key=lambda v: (SORT_KEYS[sort](v), v.dish.name.casefold()))

    def get_view(self, dish_id: str) -> DishView:
        if dish_id in self.seeds:
            return self._seed_view(self.seeds[dish_id], self.store.overrides(), self.store.hidden_ids(),
                                   self.store.ratings())
        num = _user_num(dish_id)
        data = self.store.user_dishes().get(num) if num is not None else None
        if data is None:
            raise NotFound(dish_id)
        return self._user_view(num, data, self.store.ratings())

    # -- writing dishes ------------------------------------------------------

    def _duplicate_warnings(self, name: str, dish_id: str | None) -> list[str]:
        key = name.strip().casefold()
        if any(v.dish.name.casefold() == key and v.dish.id != dish_id for v in self._all_views()):
            return [f'Another dish is already named "{name.strip()}".']
        return []

    @staticmethod
    def _stored_form(dish: Dish) -> dict:
        data = dish_to_dict(dish)
        del data["id"]
        return data

    def create(self, data: dict) -> tuple[str, list[str]]:
        dish = dish_from_dict(data, "user:new")
        warnings = self._duplicate_warnings(dish.name, None)
        num = self.store.create_user_dish(self._stored_form(dish))
        return f"user:{num}", warnings

    def save(self, dish_id: str, data: dict) -> list[str]:
        if dish_id in self.seeds:
            seed = self.seeds[dish_id]
            if not isinstance(data, dict):
                raise ValidationError(["Expected a dish object."])
            merged = {**self._stored_form(seed), "ingredients": data.get("ingredients"), "steps": data.get("steps")}
            custom = dish_from_dict(merged, dish_id)
            if custom == seed:
                self.store.delete_override(dish_id)
            else:
                stored = self._stored_form(custom)
                self.store.set_override(dish_id, stored["ingredients"], stored["steps"], seed_hash(seed))
            return []
        self.get_view(dish_id)  # raises NotFound
        dish = dish_from_dict(data, dish_id)
        warnings = self._duplicate_warnings(dish.name, dish_id)
        self.store.update_user_dish(_user_num(dish_id), self._stored_form(dish))
        return warnings

    def _require_seed(self, dish_id: str, action: str) -> None:
        if dish_id not in self.seeds:
            self.get_view(dish_id)  # raises NotFound for unknown ids
            raise CatalogError(f"Only built-in recipes can be {action}.")

    def delete(self, dish_id: str) -> None:
        if dish_id in self.seeds:
            raise CatalogError("Seed recipes can be hidden, not deleted.")
        self.get_view(dish_id)
        embedded = _embedded_images(self.store.notes_for(dish_id))
        self.store.delete_user_dish(_user_num(dish_id))
        self._prune_images(embedded)

    def revert(self, dish_id: str) -> None:
        self._require_seed(dish_id, "reverted")
        self.store.delete_override(dish_id)

    def set_hidden(self, dish_id: str, hidden: bool) -> None:
        self._require_seed(dish_id, "hidden")
        self.store.set_hidden(dish_id, hidden)

    # -- ratings -------------------------------------------------------------

    def set_rating(self, dish_id: str, stars: object) -> None:
        """Rate a dish 1–5 stars; None clears the rating."""
        self.get_view(dish_id)  # raises NotFound
        if stars is not None and (isinstance(stars, bool) or not isinstance(stars, int) or not 1 <= stars <= MAX_STARS):
            raise ValidationError([f"Rating must be a whole number of stars from 1 to {MAX_STARS}."])
        self.store.set_rating(dish_id, stars)

    # -- notes ---------------------------------------------------------------

    @staticmethod
    def _note_body(body: object) -> str:
        if not isinstance(body, str) or not body.strip():
            raise ValidationError(["Note is empty."])
        return body.strip()

    def note_parts(self, body: str) -> list[dict]:
        """A note body split into text, dish links and images (see notes.parse_note).

        Links resolve by name against every dish, hidden ones included; a built-in recipe wins a shared name.
        """
        dish_ids: dict[str, str] = {}
        for view in self._all_views():  # seeds come first
            dish_ids.setdefault(view.dish.name.casefold(), view.dish.id)
        return parse_note(body, dish_ids, self.store.image_ids())

    def notes(self, dish_id: str) -> list[Note]:
        self.get_view(dish_id)
        return self.store.notes_for(dish_id)

    def add_note(self, dish_id: str, body: object) -> Note:
        self.get_view(dish_id)
        return self.store.add_note(dish_id, self._note_body(body))

    def update_note(self, note_id: int, body: object) -> Note:
        text = self._note_body(body)
        try:
            old = self.store.note(note_id)
            note = self.store.update_note(note_id, text)
        except KeyError:
            raise NotFound(note_id) from None
        self._prune_images(image_refs(old.body))
        return note

    def delete_note(self, note_id: int) -> None:
        try:
            old = self.store.note(note_id)
            self.store.delete_note(note_id)
        except KeyError:
            raise NotFound(note_id) from None
        self._prune_images(image_refs(old.body))

    # -- images --------------------------------------------------------------

    @staticmethod
    def _image_type(data: bytes) -> str:
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        for signature, mime in IMAGE_SIGNATURES.items():
            if data.startswith(signature):
                return mime
        raise ValidationError(["Images must be PNG, JPEG, GIF or WebP."])

    def add_image(self, data: bytes) -> int:
        if len(data) > MAX_IMAGE_BYTES:
            raise ValidationError([f"Images can be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB."])
        return self.store.add_image(self._image_type(data), data)

    def image(self, image_id: int) -> tuple[str, bytes]:
        """(content type, bytes) of a stored image."""
        try:
            return self.store.image(image_id)
        except KeyError:
            raise NotFound(image_id) from None

    def _prune_images(self, candidates: set[int]) -> None:
        """Delete those of the candidate images that no note embeds any more.

        Uploads not yet saved into a note are never candidates, so a note being written keeps its images.
        """
        if candidates:
            in_use = _embedded_images(self.store.all_notes())
            self.store.delete_images(candidates - in_use)

    # -- export --------------------------------------------------------------

    def export(self) -> dict:
        """All user data, including rows that point at seeds which no longer exist."""
        return {
            "app": "recipe-butler",
            "exported_at": utc_now(),
            "user_dishes": [dish_to_dict(dish_from_dict(data, f"user:{num}"))
                            for num, data in self.store.user_dishes().items()],
            "personal_versions": [
                {"seed_id": sid, "ingredients": o.ingredients, "steps": o.steps,
                 "seed_hash": o.seed_hash, "updated_at": o.updated_at}
                for sid, o in self.store.overrides().items()
            ],
            "hidden": sorted(self.store.hidden_ids()),
            "ratings": self.store.ratings(),
            "notes": [{"id": n.id, "dish_id": n.dish_id, "body": n.body,
                       "created_at": n.created_at, "edited_at": n.edited_at} for n in self.store.all_notes()],
            "images": [{"id": i, "type": mime, "data_base64": base64.b64encode(data).decode("ascii"),
                        "created_at": at} for i, mime, data, at in self.store.all_images()],
        }
