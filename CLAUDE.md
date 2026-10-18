# CLAUDE.md

Offline recipe app: browse dishes, search by one or more ingredients, keep notes, and customize built-in recipes as revertible personal versions. Single user, single PC, no network.

## Commands

```bash
python -m recipe_butler               # serve on 127.0.0.1:8765 (next free port if taken) and open the browser
python -m recipe_butler --no-browser  # also: --port N
python -m pytest                      # all tests (run from this directory)
```

No install step: runtime is stdlib only (Python 3.11+); pytest is the only dev dependency.

## Data

- **Seed recipes** — `recipe_butler/seeds/<stem>.json`, read-only, one dish per file, id `seed:<stem>`. A bad seed file aborts startup naming the file (by design; never skip it silently).
- **User data** — one SQLite file, `data/user.db` (gitignored); `RECIPE_BUTLER_DATA` overrides the directory. Holds own dishes (`user:<n>`), personal versions of seeds (full copies of ingredients + steps, plus the seed's hash at save time), hidden seed ids, and notes.
- `data/server.lock` records the running server's port; a second launch pings it and opens the browser there instead of starting another server. A stale lock is ignored.

## Module map

- `model.py` — `Dish`/`Ingredient`, `dish_from_dict` (normalizes + validates, reports every problem), `seed_hash`
- `seeds.py` — `load_seeds`
- `store.py` — `Store`: SQLite access, plain dicts only, one lock around the connection
- `catalog.py` — `Catalog`: merges seeds with the store into `DishView`s (effective dish, original, changed markers, "original updated" flag); create/save/delete/revert/hide, notes, export
- `search.py` — `parse_terms`, `search`: case-insensitive substring on ingredient names, terms ANDed, hidden dishes skipped, effective version searched
- `server.py` — `make_server`: JSON API under `/api/*` plus static files; error bodies are `{"error", "messages"}`
- `launcher.py` — `main`: lock file, port choice, browser
- `static/` — `index.html`, `app.js`, `style.css`; vanilla JS, no build step

## Rules

- Stdlib only at runtime; no CDN, fonts, or external URLs in `static/` (a test enforces this).
- The front end builds DOM with `createElement`/`textContent` only — never `innerHTML` and friends (a test enforces this).
- Pass `encoding="utf-8"` to every file read/write; the Windows default codepage breaks non-ASCII recipes.
- Customizing a seed changes only its ingredients and steps; other fields always come from the seed file.
