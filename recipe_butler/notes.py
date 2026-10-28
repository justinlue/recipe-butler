"""Note markup: [[Dish name]] links to another dish, ![[image:<id>]] shows a stored image.

Everything else is plain text. Parsing happens here so the front end only lays out ready-made parts.
"""

from __future__ import annotations

import re
from collections.abc import Container, Mapping

IMAGE_EMBED = r"!\[\[\s*image:(\d+)\s*\]\]"
DISH_LINK = r"\[\[([^\[\]\n]*[^\[\]\s][^\[\]\n]*)\]\]"  # needs a visible character between the brackets
MARKUP = re.compile(f"{IMAGE_EMBED}|{DISH_LINK}")


def parse_note(body: str, dish_ids: Mapping[str, str], image_ids: Container[int]) -> list[dict]:
    """Split a note body into text, link and image parts.

    dish_ids maps casefolded dish names to ids; a link to an unknown name gets dish_id None.
    """
    parts: list[dict] = []
    pos = 0
    for match in MARKUP.finditer(body):
        if match.start() > pos:
            parts.append({"type": "text", "text": body[pos:match.start()]})
        image, name = match.groups()
        if image is not None:
            parts.append({"type": "image", "image_id": int(image), "found": int(image) in image_ids})
        else:
            name = name.strip()
            parts.append({"type": "link", "text": name, "dish_id": dish_ids.get(name.casefold())})
        pos = match.end()
    if pos < len(body):
        parts.append({"type": "text", "text": body[pos:]})
    return parts


def image_refs(body: str) -> set[int]:
    """Ids of the images a note body embeds."""
    return {int(m.group(1)) for m in MARKUP.finditer(body) if m.group(1) is not None}
