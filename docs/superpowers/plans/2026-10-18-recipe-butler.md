# recipe-butler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An offline recipe app where you browse dishes, search by one or more ingredients, add notes, and customize seed recipes with personal versions you can revert.

**Architecture:** Seed recipes are read-only JSON files inside the package. User data (own dishes, personal versions, hidden flags, notes) lives in one SQLite file. A `Catalog` merges the two into *effective* dish views. A stdlib `http.server` exposes a JSON API plus static files, and a plain-JS single page consumes them. `python -m recipe_butler` takes care of the lock file, picks the port and opens the browser.

**Tech Stack:** Python 3.11+ stdlib only (`http.server`, `sqlite3`, `json`, `hashlib`, `webbrowser`); vanilla HTML/CSS/JS; pytest for tests. (Machine has Python 3.14.2, pytest 8.3.5.)

**Spec:** `docs/superpowers/specs/2026-10-18-recipe-butler-design.md`

## Global Constraints

- Runtime imports are stdlib only. pytest is the only dev dependency, and there's no `requirements.txt`.
- `requires-python = ">=3.11"`.
- Server binds `127.0.0.1` only; the default port is `8765`. If it's taken, try the next 20 ports.
- No network access at runtime: no CDN, fonts or external URLs in the front end.
- Every file read/write passes `encoding="utf-8"`, because the Windows default is cp1252.
- Seed dish ids are `seed:<file stem>`; user dish ids are `user:<integer>`.
- Timestamps are ISO-8601 UTC strings with second precision, e.g. `2026-10-18T09:30:00+00:00`.
- Run all commands from `D:\Workshop\recipe-butler`. The test command is `python -m pytest`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Non-ASCII text** ("jalapeño", "葱") must load from seeds, round-trip through SQLite and the API, and match in search. Tests are in Tasks 2, 5 and 6.
2. **A seed file deleted or renamed** while personal versions, hidden flags or notes still reference it: listing must not crash, and export must still include the orphaned user data. The test is in Task 4.
3. **Malformed API input** (invalid JSON, a JSON array body, `servings: "four"`, a missing name) must return a 400 with readable messages, and the server must keep serving. The test is in Task 6.
4. **A stale lock file** left by a crashed or killed server must not stop the next launch. The test is in Task 7.
5. **User text containing HTML** (`<b>`, `<script>`) in names, ingredients or notes must display literally, never be interpreted. The front end must never use `innerHTML`/`insertAdjacentHTML`/`outerHTML`. The test is in Task 8.

---

## File Structure

```
recipe-butler/
  .gitignore                    data/, __pycache__/, .pytest_cache/
  pyproject.toml                metadata + pytest config (pythonpath ["."], testpaths ["tests"])
  CLAUDE.md
  recipe_butler/
    __init__.py
    __main__.py                 calls launcher.main()
    model.py                    Ingredient, Dish, ValidationError, dish_from_dict, dish_to_dict, seed_hash
    seeds.py                    load_seeds, SeedError, SEED_DIR
    seeds/*.json                one file per seed dish
    store.py                    Store (SQLite), Override, Note, utc_now
    catalog.py                  Catalog, DishView, NotFound, CatalogError
    search.py                   parse_terms, search, SearchHit
    server.py                   make_server (routing, JSON, static files)
    launcher.py                 data_dir, find_running, pick_port, write_lock, remove_lock, main
    static/index.html, app.js, style.css
  tests/
    test_model.py  test_seeds.py  test_store.py  test_catalog.py
    test_search.py test_server.py test_launcher.py test_frontend.py
```

---

### Task 1: Scaffold and dish model

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `recipe_butler/__init__.py`, `recipe_butler/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) Ingredient(name: str, amount: str = "")`
  - `@dataclass(frozen=True) Dish(id: str, name: str, description: str, servings: int | None, total_minutes: int | None, category: str, ingredients: tuple[Ingredient, ...], steps: tuple[str, ...])`
  - `class ValidationError(ValueError)` with attribute `messages: list[str]`
  - `dish_from_dict(data: object, dish_id: str) -> Dish`: normalizes, then validates, and raises `ValidationError` listing **every** problem found
  - `dish_to_dict(dish: Dish) -> dict`: keys `id, name, description, servings, total_minutes, category, ingredients` (a list of `{"name","amount"}`), and `steps` (a list of str)
  - `seed_hash(dish: Dish) -> str`: sha256 hex of `json.dumps(dish_to_dict(dish), sort_keys=True, ensure_ascii=False)`

**Normalization rules** (these are the spec's decisions, so implement them exactly):
- Strip all strings.
- An empty or missing `description` becomes `""`. An empty or missing `category` becomes `"Uncategorized"`.
- Drop ingredient rows whose name **and** amount are both blank, and drop blank steps. The UI's empty form rows arrive this way.
- An ingredient with an amount but a blank name is an error: `Ingredient 2 needs a name.` (1-based).
- `servings` is `None` or an int ≥ 1, and `total_minutes` is `None` or an int ≥ 0. `bool` and str values are errors.
- Required: `Name is required.`, `Add at least one ingredient.`, `Add at least one step.`
- If `data` is not a dict, or `ingredients`/`steps` is not a list, raise `ValidationError(["Expected a dish object."])` or the matching field message. Never let a `TypeError` escape.

- [ ] **Step 1: Scaffold the repo**

Run `git init` in `D:\Workshop\recipe-butler`. Write `.gitignore` and `pyproject.toml` (`[project] name="recipe-butler" version="0.1.0" requires-python=">=3.11"`, `[tool.pytest.ini_options] pythonpath=["."] testpaths=["tests"]`). Create an empty `recipe_butler/__init__.py`.

- [ ] **Step 2: Write the failing tests**

```python
import pytest
from recipe_butler.model import Dish, Ingredient, ValidationError, dish_from_dict, dish_to_dict, seed_hash

VALID = {"name": " Toast ", "servings": 1, "total_minutes": 5, "category": "",
         "ingredients": [{"name": "bread", "amount": "2 slices"}, {"name": "", "amount": ""}],
         "steps": ["Toast it.", "  "]}

def test_normalizes_and_drops_blank_rows():
    d = dish_from_dict(VALID, "user:1")
    assert d.name == "Toast" and d.category == "Uncategorized" and d.description == ""
    assert d.ingredients == (Ingredient("bread", "2 slices"),)
    assert d.steps == ("Toast it.",)

def test_reports_every_problem():
    with pytest.raises(ValidationError) as e:
        dish_from_dict({"name": " ", "ingredients": [], "steps": []}, "user:1")
    assert e.value.messages == ["Name is required.", "Add at least one ingredient.", "Add at least one step."]

def test_amount_without_name_is_an_error():
    data = {**VALID, "ingredients": [{"name": "bread", "amount": "1"}, {"name": "", "amount": "2 tbsp"}]}
    with pytest.raises(ValidationError) as e:
        dish_from_dict(data, "user:1")
    assert "Ingredient 2 needs a name." in e.value.messages

@pytest.mark.parametrize("field,value", [("servings", "four"), ("servings", 0), ("servings", True), ("total_minutes", -1)])
def test_bad_numbers(field, value):
    with pytest.raises(ValidationError):
        dish_from_dict({**VALID, field: value}, "user:1")

@pytest.mark.parametrize("data", [[], "x", None, {**VALID, "ingredients": "bread"}, {**VALID, "steps": {"a": 1}}])
def test_wrong_shapes_raise_validation_error(data):
    with pytest.raises(ValidationError):
        dish_from_dict(data, "user:1")

def test_round_trip_and_hash_is_stable_and_sensitive():
    d = dish_from_dict(VALID, "user:1")
    assert dish_from_dict(dish_to_dict(d), "user:1") == d
    assert seed_hash(d) == seed_hash(dish_from_dict(VALID, "user:1"))
    assert seed_hash(d) != seed_hash(dish_from_dict({**VALID, "steps": ["Toast it well."]}, "user:1"))
```

- [ ] **Step 3: Run to verify failure.** Run `python -m pytest tests/test_model.py -v`. Expected: an ImportError, or failures.
- [ ] **Step 4: Implement `recipe_butler/model.py`** to match the interfaces and rules above.
- [ ] **Step 5: Run to verify pass.** Run `python -m pytest tests/test_model.py -v`. Expected: all pass.
- [ ] **Step 6: Commit** the scaffold, model, tests and the `docs/` folder with message `feat: dish model with validation`.

---

### Task 2: Seed recipes and loader

**Files:**
- Create: `recipe_butler/seeds.py`, `recipe_butler/seeds/*.json` (13 files)
- Test: `tests/test_seeds.py`

**Interfaces:**
- Consumes: `dish_from_dict`, `ValidationError` (Task 1)
- Produces:
  - `SEED_DIR: Path` (the `recipe_butler/seeds` directory)
  - `class SeedError(Exception)`
  - `load_seeds(directory: Path = SEED_DIR) -> dict[str, Dish]`, keyed `seed:<stem>`. It reads every `*.json` file with `encoding="utf-8"`. Invalid JSON or a failed validation raises `SeedError` whose message starts with the file name. A bad seed must fail loudly at startup, never be skipped silently.

**Seed set:** write one JSON file per dish, in the `dish_from_dict` input shape without `id`, with real English recipes. The overlap on garlic, onion, tomato, egg and chicken is deliberate, so that multi-ingredient search returns interesting results:

| stem | category | must include ingredients |
|---|---|---|
| spaghetti-pomodoro | Pasta | spaghetti, canned tomatoes, garlic, olive oil, basil |
| garlic-butter-chicken | Mains | chicken thighs, butter, garlic, parsley |
| chicken-stir-fry | Mains | chicken breast, soy sauce, garlic, ginger, bell pepper |
| fried-rice | Mains | cooked rice, eggs, soy sauce, green onion, peas |
| shakshuka | Breakfast | eggs, canned tomatoes, onion, garlic, cumin, bell pepper |
| french-omelette | Breakfast | eggs, butter, chives |
| pancakes | Breakfast | flour, milk, eggs, baking powder, butter |
| greek-salad | Salads | tomatoes, cucumber, red onion, feta, olives, olive oil |
| caesar-salad | Salads | romaine lettuce, parmesan, croutons, garlic, lemon, egg yolk |
| tomato-soup | Soups | tomatoes, onion, garlic, vegetable stock, cream |
| chicken-noodle-soup | Soups | chicken breast, egg noodles, carrot, celery, onion, chicken stock |
| guacamole | Sides | avocado, lime, red onion, **jalapeño**, cilantro |
| banana-bread | Baking | ripe bananas, flour, sugar, eggs, butter, baking soda |

- [ ] **Step 1: Write the failing tests**

```python
import json, pytest
from recipe_butler.seeds import SeedError, load_seeds

def test_shipped_seeds_load():
    seeds = load_seeds()
    assert len(seeds) == 13
    assert all(k.startswith("seed:") for k in seeds)
    assert seeds["seed:shakshuka"].category == "Breakfast"

def test_non_ascii_survives():
    names = [i.name for i in load_seeds()["seed:guacamole"].ingredients]
    assert "jalapeño" in names

def test_bad_seed_fails_loudly_with_filename(tmp_path):
    (tmp_path / "broken.json").write_text(json.dumps({"name": "", "ingredients": [], "steps": []}), encoding="utf-8")
    with pytest.raises(SeedError, match="broken.json"):
        load_seeds(tmp_path)

def test_invalid_json_fails_with_filename(tmp_path):
    (tmp_path / "junk.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(SeedError, match="junk.json"):
        load_seeds(tmp_path)
```

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_seeds.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `load_seeds`, then write the 13 seed files.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat: seed recipes and loader`.

---

### Task 3: SQLite store

**Files:**
- Create: `recipe_butler/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces (the store holds plain dicts and lists, and never imports `model`):
  - `utc_now() -> str`
  - `@dataclass(frozen=True) Override(ingredients: list[dict], steps: list[str], seed_hash: str, updated_at: str)`
  - `@dataclass(frozen=True) Note(id: int, dish_id: str, body: str, created_at: str, edited_at: str | None)`
  - `class Store(path: Path, clock: Callable[[], str] = utc_now)`. It creates parent directories and the schema on open, and uses `sqlite3.connect(path, check_same_thread=False)` with a `threading.Lock` around every operation, because the server runs requests on its own thread. Each mutating call commits.
    - `create_user_dish(data: dict) -> int`, `update_user_dish(num: int, data: dict) -> None` (raises `KeyError` if missing), `delete_user_dish(num: int) -> None` (raises `KeyError` if missing; also deletes notes whose `dish_id == f"user:{num}"`), `user_dishes() -> dict[int, dict]`
    - `set_override(seed_id: str, ingredients: list[dict], steps: list[str], seed_hash: str) -> None` (an upsert), `delete_override(seed_id: str) -> None`, `overrides() -> dict[str, Override]`
    - `set_hidden(seed_id: str, hidden: bool) -> None`, `hidden_ids() -> set[str]`
    - `add_note(dish_id: str, body: str) -> Note`, `update_note(note_id: int, body: str) -> Note` (sets `edited_at`; raises `KeyError` if missing), `delete_note(note_id: int) -> None` (raises `KeyError` if missing), `notes_for(dish_id: str) -> list[Note]` (oldest first), `all_notes() -> list[Note]`
    - `close() -> None`
- Schema: `user_dishes(id INTEGER PRIMARY KEY, data TEXT)`, `overrides(seed_id TEXT PRIMARY KEY, ingredients TEXT, steps TEXT, seed_hash TEXT, updated_at TEXT)`, `hidden(seed_id TEXT PRIMARY KEY)`, `notes(id INTEGER PRIMARY KEY, dish_id TEXT, body TEXT, created_at TEXT, edited_at TEXT)`. JSON columns use `json.dumps(..., ensure_ascii=False)`.

- [ ] **Step 1: Write the failing tests**

```python
from recipe_butler.store import Store

def clock_from(*stamps):
    it = iter(stamps)
    return lambda: next(it)

def test_user_dish_crud_and_persistence(tmp_path):
    db = tmp_path / "sub" / "user.db"
    s = Store(db)
    n = s.create_user_dish({"name": "葱油饼"})
    s.update_user_dish(n, {"name": "Scallion pancake"})
    s.close()
    s = Store(db)
    assert s.user_dishes() == {n: {"name": "Scallion pancake"}}

def test_deleting_user_dish_deletes_its_notes(tmp_path):
    s = Store(tmp_path / "u.db")
    n = s.create_user_dish({"name": "x"})
    s.add_note(f"user:{n}", "mine"); s.add_note("seed:shakshuka", "keep")
    s.delete_user_dish(n)
    assert [x.body for x in s.all_notes()] == ["keep"]

def test_override_upsert_and_delete(tmp_path):
    s = Store(tmp_path / "u.db", clock=clock_from("t1", "t2"))
    s.set_override("seed:a", [{"name": "x", "amount": ""}], ["one"], "h1")
    s.set_override("seed:a", [{"name": "y", "amount": ""}], ["two"], "h1")
    o = s.overrides()["seed:a"]
    assert o.steps == ["two"] and o.updated_at == "t2"
    s.delete_override("seed:a")
    assert s.overrides() == {}

def test_hidden_toggle(tmp_path):
    s = Store(tmp_path / "u.db")
    s.set_hidden("seed:a", True); s.set_hidden("seed:a", True)
    assert s.hidden_ids() == {"seed:a"}
    s.set_hidden("seed:a", False)
    assert s.hidden_ids() == set()

def test_note_timestamps(tmp_path):
    s = Store(tmp_path / "u.db", clock=clock_from("t1", "t2"))
    note = s.add_note("seed:a", "too salty")
    assert (note.created_at, note.edited_at) == ("t1", None)
    edited = s.update_note(note.id, "less salt")
    assert (edited.body, edited.created_at, edited.edited_at) == ("less salt", "t1", "t2")
```

Also add a test that `update_user_dish`, `delete_user_dish`, `update_note` and `delete_note` each raise `KeyError` for an unknown id.

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_store.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `recipe_butler/store.py`.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat: sqlite store for user data`.

---

### Task 4: Catalog (effective dishes, customization, notes, export)

**Files:**
- Create: `recipe_butler/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: Task 1 model, `Store` / `Override` / `Note` (Task 3)
- Produces:
  - `class NotFound(KeyError)`, `class CatalogError(Exception)` (the operation is not allowed for this dish)
  - `@dataclass(frozen=True) DishView(dish: Dish, source: Literal["seed", "user"], customized: bool, hidden: bool, original: Dish | None, original_updated: bool, changed_ingredients: tuple[bool, ...], changed_steps: tuple[bool, ...])`
    - `dish` is the effective dish. For a customized seed it is the seed with the override's ingredients and steps; otherwise it is the seed or user dish as stored.
    - `original` is the current seed dish, and is set only when `customized`.
    - `original_updated` is `override.seed_hash != seed_hash(current seed)`.
    - `changed_*[i]` is True when effective item `i` does not appear in the original's list (compared by equality). Without a customization, every entry is False.
  - `class Catalog(seeds: dict[str, Dish], store: Store)`
    - `list_views(include_hidden: bool = False) -> list[DishView]`: seeds plus user dishes, sorted by `(category.casefold(), name.casefold())`. Override, hidden and note rows whose seed id is not in `seeds` are ignored here.
    - `get_view(dish_id: str) -> DishView`: raises `NotFound`. A hidden seed is still returned.
    - `create(data: dict) -> tuple[str, list[str]]` returns `(new id, warnings)`
    - `save(dish_id: str, data: dict) -> list[str]`:
      - For a user dish, it replaces the whole dish.
      - For a seed, it reads only `data["ingredients"]` and `data["steps"]`. It validates them by running `dish_from_dict` on the seed's own fields with those lists swapped in, and stores an override with the current seed hash. If the result equals the seed exactly, it deletes the override instead.
      - Returns warnings.
    - `delete(dish_id)`: user dishes only. On a seed it raises `CatalogError("Seed recipes can be hidden, not deleted.")`.
    - `revert(dish_id)` and `set_hidden(dish_id, hidden: bool)`: seeds only. Otherwise they raise `CatalogError`.
    - `notes(dish_id) -> list[Note]`, `add_note(dish_id, body) -> Note`, `update_note(note_id, body) -> Note`, `delete_note(note_id)`. An unknown dish or note raises `NotFound`. A blank body raises `ValidationError(["Note is empty."])`.
    - `export() -> dict` with keys `app` (`"recipe-butler"`), `exported_at`, `user_dishes` (a list of `dish_to_dict`), `personal_versions` (a list of `{seed_id, ingredients, steps, seed_hash, updated_at}`), `hidden` (a sorted list), and `notes` (a list of the Note fields). It includes orphaned rows.
  - Duplicate warning text: `Another dish is already named "<name>".` It compares `name.strip().casefold()` against every other dish, including hidden ones, excluding the dish itself. It applies to `create` and to `save` on user dishes.

- [ ] **Step 1: Write the failing tests.** Build a fixture with two small seeds made by `dish_from_dict` (`seed:a` "Alpha" in category Mains with ingredients garlic and onion; `seed:b` "Beta") and a `Store(tmp_path/"u.db")`.

```python
def test_customize_shows_personal_version_and_marks_changes(cat):
    cat.save("seed:a", {"ingredients": [{"name": "garlic", "amount": ""}, {"name": "olive oil", "amount": "1 tbsp"}],
                        "steps": ORIGINAL_A_STEPS})
    v = cat.get_view("seed:a")
    assert v.customized and v.original.ingredients != v.dish.ingredients
    assert v.changed_ingredients == (False, True) and not any(v.changed_steps)
    assert not v.original_updated

def test_saving_identical_to_original_removes_override(cat): ...   # save the seed's own lists → customized is False
def test_revert_keeps_notes(cat): ...                              # customize, add note, revert → not customized, the note is still there
def test_original_updated_when_seed_changes(cat, store): ...       # customize, then rebuild the Catalog with a modified seed:a → original_updated is True
def test_hidden_seed_excluded_unless_requested(cat): ...           # set_hidden → missing from list_views(), present in list_views(True), get_view still works
def test_seed_cannot_be_deleted_user_dish_can(cat): ...            # delete("seed:a") raises CatalogError; create+delete user dish → NotFound afterwards
def test_user_dish_rejects_revert_and_hide(cat): ...               # CatalogError for both
def test_duplicate_name_warns_case_insensitively(cat):
    _, warnings = cat.create({"name": " alpha ", "ingredients": [{"name": "x"}], "steps": ["y"]})
    assert warnings == ['Another dish is already named "alpha".']
def test_saving_user_dish_does_not_warn_about_itself(cat): ...
def test_blank_note_rejected_and_unknown_dish_not_found(cat): ...

def test_orphaned_seed_rows_do_not_break_listing_and_are_exported(store, seeds):
    # Review Focus 2
    store.set_override("seed:gone", [{"name": "x", "amount": ""}], ["y"], "h")
    store.set_hidden("seed:gone", True)
    store.add_note("seed:gone", "remember this")
    cat = Catalog(seeds, store)
    assert {v.dish.id for v in cat.list_views(include_hidden=True)} == set(seeds)
    exported = cat.export()
    assert exported["personal_versions"][0]["seed_id"] == "seed:gone"
    assert exported["hidden"] == ["seed:gone"]
    assert exported["notes"][0]["body"] == "remember this"
```

The `...` tests take their assertions from the inline comments.

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_catalog.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `recipe_butler/catalog.py`.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat: catalog merging seeds with personal versions`.

---

### Task 5: Ingredient search

**Files:**
- Create: `recipe_butler/search.py`
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `DishView` (Task 4)
- Produces:
  - `parse_terms(query: str) -> list[str]`: split on `,` and `+`, strip, `casefold()`, drop empties, and dedupe preserving first-seen order.
  - `@dataclass(frozen=True) SearchHit(dish_id: str, name: str, category: str, matches: dict[str, list[str]])`: maps each term to the ingredient names (original casing) that contain it.
  - `search(views: Iterable[DishView], terms: list[str]) -> list[SearchHit]`:
    - Searches the effective `view.dish.ingredients` only.
    - Skips views where `hidden` is True.
    - A dish is a hit only if **every** term is a substring of at least one ingredient name's `casefold()`.
    - Sorted by `name.casefold()`. Empty `terms` returns `[]`.

- [ ] **Step 1: Write the failing tests.** Build views with `Catalog(load_seeds(), Store(tmp_path/"u.db")).list_views(include_hidden=True)`.

```python
def test_parse_terms():
    assert parse_terms(" Garlic, tomato + garlic ,, ") == ["garlic", "tomato"]

def test_substring_and_case_insensitive(views):
    names = {h.name for h in search(views, ["TOMATO"])}
    assert {"Greek Salad", "Shakshuka", "Spaghetti Pomodoro", "Tomato Soup"} <= names

def test_terms_are_anded_and_matches_reported(views):
    hits = search(views, ["egg", "tomato"])
    assert [h.dish_id for h in hits] == ["seed:shakshuka"]
    assert hits[0].matches == {"egg": ["eggs"], "tomato": ["canned tomatoes"]}

def test_non_ascii_term(views):                      # Review Focus 1
    assert [h.dish_id for h in search(views, ["JALAPEÑO"])] == ["seed:guacamole"]

def test_searches_personal_version_not_original(cat): ...   # customize spaghetti-pomodoro to swap olive oil for butter → "olive oil" no longer finds it, "butter" does
def test_hidden_excluded(cat): ...                          # hide guacamole → "avocado" returns []
def test_empty_terms_return_nothing(views): assert search(views, []) == []
```

The display names in the assertions must match the names written in Task 2's seed files. The `...` tests take their assertions from the inline comments.

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_search.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `recipe_butler/search.py`.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat: multi-ingredient search`.

---

### Task 6: HTTP server and JSON API

**Files:**
- Create: `recipe_butler/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Catalog`, `NotFound`, `CatalogError`, `ValidationError`, `dish_to_dict`, `parse_terms`, `search`
- Produces: `make_server(catalog: Catalog, port: int, host: str = "127.0.0.1") -> http.server.HTTPServer` (not threading, since one user is enough). `port=0` picks a free port, which tests read from `server.server_address[1]`.

**Routes.** All `/api/*` responses are `application/json; charset=utf-8`, and bodies are UTF-8 JSON.

| Method | Path | Result |
|---|---|---|
| GET | `/api/ping` | `{"app": "recipe-butler"}` |
| GET | `/api/dishes?hidden=1` | list of summaries `{id, name, category, source, customized, hidden}`; `hidden=1` includes hidden seeds |
| GET | `/api/dishes/<id>` | `{dish, source, customized, hidden, original, original_updated, changed_ingredients, changed_steps, notes}`; `dish` and `original` are `dish_to_dict` or null; `notes` are lists of Note fields |
| POST | `/api/dishes` | 201 `{id, warnings}` |
| PUT | `/api/dishes/<id>` | `{warnings}` |
| DELETE | `/api/dishes/<id>` | `{}` |
| POST | `/api/dishes/<id>/revert` \| `/hide` \| `/unhide` | `{}` |
| POST | `/api/dishes/<id>/notes` body `{body}` | 201 note |
| PUT / DELETE | `/api/notes/<int>` | note / `{}` |
| GET | `/api/search?q=<terms>` | `{"terms": [...], "hits": [{dish_id, name, category, matches}]}` |
| GET | `/api/export` | the export JSON with `Content-Disposition: attachment; filename="recipe-butler-export-<YYYY-MM-DD>.json"` |
| GET | `/` and `/static/<file>` | files from `recipe_butler/static/`; paths that resolve outside that directory return 404 |

Dish ids contain `:`, so the client URL-encodes them and the server URL-decodes path segments.

**Errors** are always JSON `{"error": <code>, "messages": [str]}`:
- An invalid JSON body, a body that isn't an object, or `ValidationError` returns 400 (`bad_request` / `invalid`).
- `CatalogError` returns 400 `not_allowed`.
- `NotFound` or an unknown route returns 404 `not_found`.
- Any other exception returns 500 `internal`, logged to stderr, and the server keeps serving.
- Silence `log_message` for 2xx responses.

- [ ] **Step 1: Write the failing tests.** Use a fixture that starts `make_server(Catalog(load_seeds(), Store(tmp_path/"u.db")), 0)` with `serve_forever` in a daemon thread, plus a helper `api(method, path, body=None, raw: bytes | None = None) -> (status, json)` (`raw` sends bytes as-is) built on `urllib.request` that treats `HTTPError` as a response.

```python
def test_list_and_get(api):
    status, dishes = api("GET", "/api/dishes")
    assert status == 200 and len(dishes) == 13
    status, view = api("GET", "/api/dishes/seed%3Ashakshuka")
    assert view["dish"]["name"] == "Shakshuka" and view["customized"] is False and view["notes"] == []

def test_create_customize_note_search_flow(api): ...  # POST dish (201 + id); PUT seed:guacamole with a changed ingredient → GET shows customized; POST note; search "avocado" finds guacamole

def test_unicode_and_html_round_trip(api):           # Review Focus 1 + 5 (server half)
    _, note = api("POST", "/api/dishes/seed%3Aguacamole/notes", {"body": "多放葱 <script>alert(1)</script>"})
    _, view = api("GET", "/api/dishes/seed%3Aguacamole")
    assert view["notes"][0]["body"] == "多放葱 <script>alert(1)</script>"

@pytest.mark.parametrize("raw", [b"{not json", b"[1,2]", json.dumps({"name": "x", "servings": "four", "ingredients": [], "steps": []}).encode()])
def test_malformed_input_is_400_and_server_survives(api, raw):  # Review Focus 3
    status, err = api("POST", "/api/dishes", raw=raw)
    assert status == 400 and err["messages"]
    assert api("GET", "/api/ping")[0] == 200

def test_delete_seed_not_allowed(api): ...           # DELETE seed:shakshuka → 400 not_allowed
def test_unknown_dish_404(api): ...                  # GET /api/dishes/seed%3Anope → 404 not_found
def test_export_is_attachment(api): ...              # read the raw response: Content-Disposition contains "recipe-butler-export-"
def test_static_traversal_blocked(api): ...          # GET /static/..%2F..%2Fpyproject.toml → 404
def test_index_served(api): ...                      # GET / → 200, text/html
```

Create a placeholder `recipe_butler/static/index.html` so that `test_index_served` passes. Task 8 replaces it. The `...` tests take their assertions from the inline comments.

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_server.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `recipe_butler/server.py`.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Commit** with message `feat: JSON API server`.

---

### Task 7: Launcher

**Files:**
- Create: `recipe_butler/launcher.py`, `recipe_butler/__main__.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `load_seeds`, `Store`, `Catalog`, `make_server`
- Produces:
  - `data_dir() -> Path`: the env var `RECIPE_BUTLER_DATA` if set, else `<repo root>/data`, where the repo root is `Path(__file__).resolve().parent.parent`. The database is `data_dir()/user.db` and the lock is `data_dir()/server.lock`.
  - `find_running(lock: Path, timeout: float = 1.0) -> int | None`: reads `{"port": int, "pid": int}` from the lock and GETs `http://127.0.0.1:<port>/api/ping`. It returns the port only if the reply is `{"app": "recipe-butler"}`. A missing lock, unreadable lock, refused connection or wrong app all return None.
  - `pick_port(start: int = 8765, tries: int = 20) -> int`: returns the first port that binds on `127.0.0.1`. If all are taken it raises `OSError("No free port in 8765–8784")`.
  - `write_lock(lock: Path, port: int) -> None` and `remove_lock(lock: Path, port: int) -> None`. `remove_lock` deletes the lock only if it still names `port`.
  - `main(argv: list[str] | None = None) -> int` with flags `--port N` (skips `pick_port`) and `--no-browser`. Its flow:
    1. If `find_running` returns a port, open the browser there (unless `--no-browser`), print `recipe-butler already running at http://127.0.0.1:<port>/`, and return 0.
    2. Otherwise load the seeds. On `SeedError`, print it to stderr and return 1.
    3. Open the store, make the server, write the lock, open the browser and print the URL.
    4. `serve_forever`. On `KeyboardInterrupt` or exit, call `remove_lock` and `store.close()`, then return 0.
  - `__main__.py`: `raise SystemExit(main())`

- [ ] **Step 1: Write the failing tests**

```python
def test_stale_lock_is_ignored(tmp_path):            # Review Focus 4
    lock = tmp_path / "server.lock"
    lock.write_text(json.dumps({"port": free_unused_port(), "pid": 999999}), encoding="utf-8")
    assert find_running(lock) is None

def test_garbage_lock_is_ignored(tmp_path): ...      # lock contains "not json" → None
def test_detects_running_server(tmp_path, api_server): ...  # write_lock(lock, live port) → find_running == that port
def test_pick_port_skips_taken(): ...                # bind a socket on p, then pick_port(p, 3) != p
def test_remove_lock_only_if_ours(tmp_path): ...     # write_lock(lock, 1); remove_lock(lock, 2) keeps it; remove_lock(lock, 1) deletes it
def test_main_reports_bad_seed(monkeypatch, tmp_path, capsys): ...  # monkeypatch load_seeds to raise SeedError("x.json: bad") → main(["--no-browser"]) == 1, "x.json" in stderr
```

`free_unused_port()` binds to port 0, records the port and closes the socket. `api_server` reuses the server-thread pattern from Task 6. Move that helper into `tests/conftest.py` so both test files can share it. The `...` tests take their assertions from the inline comments.

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_launcher.py -v`. Expected: an ImportError.
- [ ] **Step 3: Implement `recipe_butler/launcher.py` and `recipe_butler/__main__.py`.**
- [ ] **Step 4: Run to verify pass.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Smoke run.** Run `RECIPE_BUTLER_DATA=<scratch dir> python -m recipe_butler --no-browser` in the background, then `curl http://127.0.0.1:8765/api/ping`. Expected: `{"app": "recipe-butler"}`. Run the same command a second time. Expected: it prints "already running" and exits 0. Then stop the first server.
- [ ] **Step 6: Commit** with message `feat: launcher with lock file and port selection`.

---

### Task 8: Front end, docs, and index entry

**Files:**
- Create: `recipe_butler/static/index.html` (replacing the placeholder), `recipe_butler/static/app.js`, `recipe_butler/static/style.css`, `CLAUDE.md`
- Modify: `D:\Workshop\CLAUDE.md` (Projects list, under "Python tools")
- Test: `tests/test_frontend.py`

**Interfaces:**
- Consumes: the Task 6 API only.

**UI (from the spec):**
- **Two-pane layout**:
  - The left sidebar has tabs **Dishes** | **By ingredient** and a **+ New dish** button.
  - The Dishes tab has a name-filter box and dishes grouped under category headings.
  - At the bottom of the sidebar is a **Show hidden** checkbox. Hidden dishes appear greyed with an **Unhide** button.
  - The By ingredient tab has one input that accepts `chicken, garlic`, and results that show each dish with "matched: garlic → garlic, chicken → chicken breast".
- **Dish view**:
  - Shows the name, description, servings, total time, the ingredients list (`amount name`), numbered steps, and a Notes section. Each note shows its created time and, if edited, "edited <time>", with Edit and Delete buttons, plus an add-note textarea.
  - A seed dish has **Customize** and **Hide** buttons. When customized it shows a "Your version" label, marks changed items (a CSS class `changed`), and has **View original** (a toggle that renders `original`) and **Revert to original** (behind a confirm).
  - When `original_updated` is set, show the badge "Original updated since you customized this", which links to View original.
  - A user dish has **Edit** and **Delete** (behind a confirm).
- **Edit form** (shared by new, edit and customize):
  - Ingredient rows (amount + name) and step rows, each with add/remove buttons. Customize shows only the ingredient and step rows.
  - API `messages` appear as an error list above the form, and `warnings` appear as a non-blocking notice after saving.
- An **Export** button in the header navigates to `/api/export`.
- **Rendering**: build all DOM with `createElement` and `textContent`, and URL-encode dish ids in fetch paths.
- **Styling**: system font stack, CSS custom properties, and a light/dark theme via `prefers-color-scheme`. No external assets.

- [ ] **Step 1: Write the failing test** (Review Focus 5)

```python
from pathlib import Path
STATIC = Path(__file__).resolve().parent.parent / "recipe_butler" / "static"

def test_frontend_never_injects_html():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js

def test_frontend_has_no_external_urls():
    for f in STATIC.iterdir():
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f.name
```

- [ ] **Step 2: Run to verify failure.** Run `python -m pytest tests/test_frontend.py -v`. Expected: FAIL, because `app.js` doesn't exist.
- [ ] **Step 3: Implement `index.html`, `app.js` and `style.css`.**
- [ ] **Step 4: Run all tests.** Run `python -m pytest -v`. Expected: all pass.
- [ ] **Step 5: Manual check in the browser.** Run `RECIPE_BUTLER_DATA=<scratch dir> python -m recipe_butler`, then verify each of these:
  - The dishes are grouped by category, and the filter narrows them.
  - Searching `egg, tomato` shows Shakshuka with its matches.
  - Customizing Spaghetti Pomodoro to swap olive oil for butter marks the change; View original and Revert work; and a note added before the revert survives it.
  - A note `<b>hi</b>` displays literally.
  - Hiding Guacamole removes it from the list and from an `avocado` search, and Show hidden plus Unhide restores it.
  - A new dish with a duplicate name shows the warning.
  - Saving an empty form shows all three validation messages.
  - Export downloads a JSON file.
- [ ] **Step 6: Write `CLAUDE.md`.** Cover the run command, the test command, the data location and the `RECIPE_BUTLER_DATA` env var, the module map (one line per file), the seed-vs-SQLite model, and the "stdlib only, no CDN, UTF-8 everywhere" rules.
- [ ] **Step 7: Add the index entry.** In `D:\Workshop\CLAUDE.md`, under "Python tools", add a bullet like the others: ``- `recipe-butler/` — offline recipe app (stdlib web server + vanilla JS, `python -m recipe_butler`): browse dishes, multi-ingredient search, notes, revertible personal versions of seed recipes. **Has its own `CLAUDE.md`.**``
- [ ] **Step 8: Commit** with message `feat: browser UI, docs`. Only the recipe-butler repo is committed; the workshop `CLAUDE.md` is not in any repo.
