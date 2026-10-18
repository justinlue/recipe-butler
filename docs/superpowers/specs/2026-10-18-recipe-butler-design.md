# recipe-butler — Design

Agreed 2026-10-18 in a grilling session (Q1–Q23). Offline recipe app for one user on one PC.

## Platform

- Local web app: stdlib Python server + plain HTML/CSS/JS front end. No build step, no CDN, no network access needed.
- Python 3.11+, stdlib only at runtime (`http.server`, `sqlite3`, `json`). pytest is the only dev dependency.
- `python -m recipe_butler` serves on `127.0.0.1:8765` (next free port if taken) and opens the browser.
- A lock file records the running server's port; a second launch opens the browser on the existing server instead of starting another.
- Single user, no accounts, no sync.

## Data

- **Seed recipes**: 10–20 English dishes as read-only JSON files in the repo.
- **User data**: one SQLite file, gitignored — the user's own recipes, personal versions, hidden flags, notes.
- **Dish fields**: name, short description, servings, total time, category, ingredients, steps. No photos.
- **Ingredient**: `name` (searched) + free-text `amount` (e.g. "2 cups", "a pinch").
- **Validation**: name, ≥1 ingredient and ≥1 step required. Duplicate dish names allowed, with a warning.

## Customization

- **Seed dishes**: customizing saves a *personal version* — a full copy of the ingredients and steps list.
  - The personal version is shown by default; the user can view the original or revert (revert = delete the personal version). Items that differ from the original are marked.
  - The seed's hash is stored at customize time; if the seed later changes, an "original updated since you customized this" badge shows, with a link to view the new original. No auto-merge.
  - Seeds can be hidden, never deleted. A "Show hidden" toggle lists them greyed with "Unhide". Hidden dishes are excluded from ingredient search.
- **User-created dishes**: edited in place, deletable.
- **Notes**: a timestamped list per dish, separate from the recipe. Editable and deletable; show created and edited times; survive revert.

## UI & search

- Sidebar: all dishes grouped by category, with a name filter box.
- Dish view: ingredients, steps, notes; customize / revert actions.
- "By ingredient" tab: case-insensitive substring matching on ingredient names ("tomato" matches "cherry tomatoes"); several terms are ANDed; each result shows which terms it matched. Search runs over the effective (personal-if-present) version.
- Export button: downloads all user data as one JSON file. No import in v1.

## Project

- Own git repo at `D:\Workshop\recipe-butler\`, pytest tests for storage, overrides and search, a `CLAUDE.md`, and an entry in the workshop `CLAUDE.md` index.
