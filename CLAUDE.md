# CLAUDE.md

Offline recipe app: browse dishes, search by one or more ingredients, rate dishes 1–5 stars, keep notes (linking other dishes, with images), and customize built-in recipes as revertible personal versions. Single user, single PC, no network.

## Commands

```bash
python -m recipe_butler               # serve on 127.0.0.1:8765 (next free port if taken) and open the browser
python -m recipe_butler --no-browser  # also: --port N
python -m pytest                      # all tests (run from this directory)
```

No install step: runtime is stdlib only (Python 3.11+); pytest is the only dev dependency.

## Data

- **Seed recipes** — `recipe_butler/seeds/<stem>.json`, read-only, one dish per file, id `seed:<stem>`. A bad seed file aborts startup naming the file (by design; never skip it silently).
- **User data** — one SQLite file, `data/user.db` (gitignored); `RECIPE_BUTLER_DATA` overrides the directory. Holds own dishes (`user:<n>`), personal versions of seeds (full copies of ingredients + steps, plus the seed's hash at save time), hidden seed ids, ratings (1–5 stars, any dish), notes, and the images notes embed (PNG/JPEG/GIF/WebP, sniffed from the bytes, ≤10 MB; an image is deleted when an edit or delete leaves no note embedding it).
- `data/server.lock` records the running server's port; a second launch pings it and opens the browser there instead of starting another server. A stale lock is ignored.

## Module map

- `model.py` — `Dish`/`Ingredient`, `dish_from_dict` (normalizes + validates, reports every problem), `seed_hash`
- `seeds.py` — `load_seeds`
- `store.py` — `Store`: SQLite access, plain dicts only, one lock around the connection
- `catalog.py` — `Catalog`: merges seeds with the store into `DishView`s (effective dish, original, changed markers, "original updated" flag); create/save/delete/revert/hide, ratings, list order (`category` | `rating` | `time`), notes and their parts, images, export
- `notes.py` — `parse_note`, `image_refs`: note markup, `[[Dish name]]` links (resolved by name, case-insensitive) and `![[image:<id>]]` embeds, split into text/link/image parts for the front end
- `search.py` — `parse_terms`, `search`: case-insensitive substring on ingredient names, terms ANDed, hidden dishes skipped, effective version searched
- `server.py` — `make_server`: threaded JSON API under `/api/*` plus static files; error bodies are `{"error", "messages"}`
- `launcher.py` — `main`: lock file, port choice, browser
- `static/` — `index.html`, `app.js`, `style.css`; vanilla JS, no build step

## Rules

- Stdlib only at runtime; no CDN, fonts, or external URLs in `static/` (a test enforces this).
- The front end builds DOM with `createElement`/`textContent` only — never `innerHTML` and friends (a test enforces this).
- Pass `encoding="utf-8"` to every file read/write; the Windows default codepage breaks non-ASCII recipes.
- The server only answers its own page: `Host` must be `127.0.0.1:<port>`/`localhost:<port>`, writes need `Content-Type: application/json` and no foreign `Origin`. The front end's `api()` always sends JSON for non-GET.
- Customizing a seed changes only its ingredients and steps; other fields always come from the seed file.
