import pytest

from recipe_butler.catalog import Catalog
from recipe_butler.search import parse_terms, search
from recipe_butler.seeds import load_seeds
from recipe_butler.store import Store


@pytest.fixture
def cat(tmp_path):
    store = Store(tmp_path / "u.db")
    yield Catalog(load_seeds(), store)
    store.close()


@pytest.fixture
def views(cat):
    return cat.list_views(include_hidden=True)


def test_parse_terms():
    assert parse_terms(" Garlic, tomato + garlic ,, ") == ["garlic", "tomato"]
    assert parse_terms("   ") == []


def test_substring_and_case_insensitive(views):
    names = {h.name for h in search(views, ["TOMATO"])}
    assert {"Greek Salad", "Shakshuka", "Spaghetti Pomodoro", "Tomato Soup"} <= names


def test_terms_are_anded_and_matches_reported(views):
    hits = search(views, ["egg", "tomato"])
    assert [h.dish_id for h in hits] == ["seed:shakshuka"]
    assert hits[0].matches == {"egg": ["eggs"], "tomato": ["canned tomatoes"]}
    assert hits[0].category == "Breakfast"


def test_results_sorted_by_name(views):
    names = [h.name for h in search(views, ["garlic"])]
    assert names == sorted(names, key=str.casefold) and len(names) >= 5


def test_non_ascii_term(views):
    # Review Focus 1
    assert [h.dish_id for h in search(views, ["JALAPEÑO"])] == ["seed:guacamole"]


def test_searches_personal_version_not_original(cat):
    original = cat.get_view("seed:spaghetti-pomodoro").dish
    swapped = [{"name": "butter" if i.name == "olive oil" else i.name, "amount": i.amount} for i in original.ingredients]
    cat.save("seed:spaghetti-pomodoro", {"ingredients": swapped, "steps": list(original.steps)})
    views = cat.list_views()
    assert "seed:spaghetti-pomodoro" not in {h.dish_id for h in search(views, ["olive oil"])}
    assert "seed:spaghetti-pomodoro" in {h.dish_id for h in search(views, ["butter"])}


def test_hidden_excluded(cat):
    cat.set_hidden("seed:guacamole", True)
    assert search(cat.list_views(include_hidden=True), ["avocado"]) == []


def test_empty_terms_return_nothing(views):
    assert search(views, []) == []
