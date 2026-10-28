"""SQLite store for everything the user creates: own dishes, personal versions, hidden flags, ratings, notes,
and the images embedded in notes.

The store holds plain dicts and lists; turning them into Dish objects is the catalog's job.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_dishes (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS overrides (
    seed_id TEXT PRIMARY KEY, ingredients TEXT NOT NULL, steps TEXT NOT NULL,
    seed_hash TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hidden (seed_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS ratings (dish_id TEXT PRIMARY KEY, stars INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY, dish_id TEXT NOT NULL, body TEXT NOT NULL,
    created_at TEXT NOT NULL, edited_at TEXT);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class Override:
    ingredients: list[dict]
    steps: list[str]
    seed_hash: str
    updated_at: str


@dataclass(frozen=True)
class Note:
    id: int
    dish_id: str
    body: str
    created_at: str
    edited_at: str | None


class Store:
    def __init__(self, path: Path, clock: Callable[[], str] = utc_now):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        # The server handles requests on its own thread; the lock serializes access.
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._db.execute(sql, params)
            self._db.commit()
            return cursor

    def _read(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # -- user dishes ---------------------------------------------------------

    def create_user_dish(self, data: dict) -> int:
        return self._write("INSERT INTO user_dishes (data) VALUES (?)", (_dumps(data),)).lastrowid

    def update_user_dish(self, num: int, data: dict) -> None:
        if self._write("UPDATE user_dishes SET data = ? WHERE id = ?", (_dumps(data), num)).rowcount == 0:
            raise KeyError(num)

    def delete_user_dish(self, num: int) -> None:
        with self._lock:
            if self._db.execute("DELETE FROM user_dishes WHERE id = ?", (num,)).rowcount == 0:
                raise KeyError(num)
            self._db.execute("DELETE FROM notes WHERE dish_id = ?", (f"user:{num}",))
            self._db.execute("DELETE FROM ratings WHERE dish_id = ?", (f"user:{num}",))
            self._db.commit()

    def user_dishes(self) -> dict[int, dict]:
        return {num: json.loads(data) for num, data in self._read("SELECT id, data FROM user_dishes ORDER BY id")}

    # -- personal versions of seeds -----------------------------------------

    def set_override(self, seed_id: str, ingredients: list[dict], steps: list[str], seed_hash: str) -> None:
        self._write(
            "INSERT OR REPLACE INTO overrides (seed_id, ingredients, steps, seed_hash, updated_at) VALUES (?, ?, ?, ?, ?)",
            (seed_id, _dumps(ingredients), _dumps(steps), seed_hash, self._clock()),
        )

    def delete_override(self, seed_id: str) -> None:
        self._write("DELETE FROM overrides WHERE seed_id = ?", (seed_id,))

    def overrides(self) -> dict[str, Override]:
        rows = self._read("SELECT seed_id, ingredients, steps, seed_hash, updated_at FROM overrides ORDER BY seed_id")
        return {sid: Override(json.loads(ing), json.loads(steps), h, at) for sid, ing, steps, h, at in rows}

    # -- hidden seeds --------------------------------------------------------

    def set_hidden(self, seed_id: str, hidden: bool) -> None:
        if hidden:
            self._write("INSERT OR IGNORE INTO hidden (seed_id) VALUES (?)", (seed_id,))
        else:
            self._write("DELETE FROM hidden WHERE seed_id = ?", (seed_id,))

    def hidden_ids(self) -> set[str]:
        return {sid for (sid,) in self._read("SELECT seed_id FROM hidden")}

    # -- ratings -------------------------------------------------------------

    def set_rating(self, dish_id: str, stars: int | None) -> None:
        if stars is None:
            self._write("DELETE FROM ratings WHERE dish_id = ?", (dish_id,))
        else:
            self._write("INSERT OR REPLACE INTO ratings (dish_id, stars) VALUES (?, ?)", (dish_id, stars))

    def ratings(self) -> dict[str, int]:
        return dict(self._read("SELECT dish_id, stars FROM ratings ORDER BY dish_id"))

    # -- notes ---------------------------------------------------------------

    def note(self, note_id: int) -> Note:
        rows = self._read("SELECT id, dish_id, body, created_at, edited_at FROM notes WHERE id = ?", (note_id,))
        if not rows:
            raise KeyError(note_id)
        return Note(*rows[0])

    def add_note(self, dish_id: str, body: str) -> Note:
        cursor = self._write("INSERT INTO notes (dish_id, body, created_at) VALUES (?, ?, ?)",
                             (dish_id, body, self._clock()))
        return self.note(cursor.lastrowid)

    def update_note(self, note_id: int, body: str) -> Note:
        if self._write("UPDATE notes SET body = ?, edited_at = ? WHERE id = ?",
                       (body, self._clock(), note_id)).rowcount == 0:
            raise KeyError(note_id)
        return self.note(note_id)

    def delete_note(self, note_id: int) -> None:
        if self._write("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount == 0:
            raise KeyError(note_id)

    def notes_for(self, dish_id: str) -> list[Note]:
        rows = self._read("SELECT id, dish_id, body, created_at, edited_at FROM notes WHERE dish_id = ? ORDER BY id",
                          (dish_id,))
        return [Note(*row) for row in rows]

    def all_notes(self) -> list[Note]:
        return [Note(*row) for row in self._read("SELECT id, dish_id, body, created_at, edited_at FROM notes ORDER BY id")]

    # -- images --------------------------------------------------------------

    def add_image(self, mime: str, data: bytes) -> int:
        return self._write("INSERT INTO images (mime, data, created_at) VALUES (?, ?, ?)",
                           (mime, data, self._clock())).lastrowid

    def image(self, image_id: int) -> tuple[str, bytes]:
        rows = self._read("SELECT mime, data FROM images WHERE id = ?", (image_id,))
        if not rows:
            raise KeyError(image_id)
        return rows[0]

    def delete_images(self, image_ids: set[int]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM images WHERE id = ?", [(i,) for i in image_ids])
            self._db.commit()

    def image_ids(self) -> set[int]:
        return {i for (i,) in self._read("SELECT id FROM images")}

    def all_images(self) -> list[tuple[int, str, bytes, str]]:
        return self._read("SELECT id, mime, data, created_at FROM images ORDER BY id")
