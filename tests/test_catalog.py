import pytest

from recipe_butler.catalog import Catalog, CatalogError, NotFound
from recipe_butler.model import ValidationError, dish_from_dict, dish_to_dict
from recipe_butler.store import Store

A_INGREDIENTS = [{"name": "garlic", "amount": "2 cloves"}, {"name": "onion", "amount": "1"}]
A_STEPS = ["Chop.", "Fry."]


def make_seeds(a_steps=A_STEPS):
    return {
        "seed:a": dish_from_dict({"name": "Alpha", "category": "Mains", "ingredients": A_INGREDIENTS,
                                  "steps": a_steps}, "seed:a"),
        "seed:b": dish_from_dict({"name": "Beta", "category": "Breakfast",
                                  "ingredients": [{"name": "egg", "amount": "2"}], "steps": ["Boil."]}, "seed:b"),
    }


USER_DISH = {"name": "Gamma", "category": "Mains", "ingredients": [{"name": "rice", "amount": "1 cup"}],
             "steps": ["Cook."]}


@pytest.fixture
def seeds():
    return make_seeds()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "u.db")
    yield s
    s.close()


@pytest.fixture
def cat(seeds, store):
    return Catalog(seeds, store)


def test_uncustomized_seed_view(cat):
    v = cat.get_view("seed:a")
    assert v.source == "seed" and not v.customized and not v.hidden and v.original is None
    assert v.changed_ingredients == (False, False) and v.changed_steps == (False, False)


def test_list_is_sorted_by_category_then_name(cat):
    cat.create(USER_DISH)
    assert [v.dish.name for v in cat.list_views()] == ["Beta", "Alpha", "Gamma"]


def test_customize_shows_personal_version_and_marks_changes(cat):
    cat.save("seed:a", {"ingredients": [{"name": "garlic", "amount": "2 cloves"},
                                        {"name": "olive oil", "amount": "1 tbsp"}],
                        "steps": A_STEPS})
    v = cat.get_view("seed:a")
    assert v.customized and v.original.ingredients != v.dish.ingredients
    assert v.dish.name == "Alpha" and v.original == cat.seeds["seed:a"]
    assert v.changed_ingredients == (False, True) and not any(v.changed_steps)
    assert not v.original_updated


def test_customize_ignores_other_fields(cat):
    cat.save("seed:a", {"name": "Renamed", "ingredients": A_INGREDIENTS, "steps": ["Chop.", "Fry well."]})
    assert cat.get_view("seed:a").dish.name == "Alpha"


def test_customize_validates(cat):
    with pytest.raises(ValidationError):
        cat.save("seed:a", {"ingredients": [], "steps": A_STEPS})
    assert not cat.get_view("seed:a").customized


def test_saving_identical_to_original_removes_override(cat):
    cat.save("seed:a", {"ingredients": A_INGREDIENTS, "steps": ["Chop.", "Fry well."]})
    cat.save("seed:a", {"ingredients": A_INGREDIENTS, "steps": A_STEPS})
    assert not cat.get_view("seed:a").customized


def test_revert_keeps_notes(cat):
    cat.save("seed:a", {"ingredients": A_INGREDIENTS, "steps": ["Chop.", "Fry well."]})
    cat.add_note("seed:a", "great with rice")
    cat.revert("seed:a")
    assert not cat.get_view("seed:a").customized
    assert [n.body for n in cat.notes("seed:a")] == ["great with rice"]


def test_original_updated_when_seed_changes(cat, store):
    cat.save("seed:a", {"ingredients": A_INGREDIENTS, "steps": ["Chop.", "Fry well."]})
    later = Catalog(make_seeds(a_steps=["Chop finely.", "Fry."]), store)
    v = later.get_view("seed:a")
    assert v.customized and v.original_updated
    assert v.original.steps == ("Chop finely.", "Fry.")


def test_hidden_seed_excluded_unless_requested(cat):
    cat.set_hidden("seed:b", True)
    assert "seed:b" not in {v.dish.id for v in cat.list_views()}
    assert "seed:b" in {v.dish.id for v in cat.list_views(include_hidden=True)}
    assert cat.get_view("seed:b").hidden
    cat.set_hidden("seed:b", False)
    assert "seed:b" in {v.dish.id for v in cat.list_views()}


def test_user_dish_create_edit_delete(cat):
    dish_id, warnings = cat.create(USER_DISH)
    assert dish_id.startswith("user:") and warnings == []
    v = cat.get_view(dish_id)
    assert v.source == "user" and v.dish.name == "Gamma"
    cat.save(dish_id, {**USER_DISH, "name": "Gamma rice"})
    assert cat.get_view(dish_id).dish.name == "Gamma rice"
    cat.add_note(dish_id, "mine")
    cat.delete(dish_id)
    with pytest.raises(NotFound):
        cat.get_view(dish_id)


def test_create_rejects_invalid_and_stores_nothing(cat):
    with pytest.raises(ValidationError):
        cat.create({"name": "x", "ingredients": [], "steps": []})
    assert len(cat.list_views()) == 2


def test_seed_cannot_be_deleted(cat):
    with pytest.raises(CatalogError, match="hidden, not deleted"):
        cat.delete("seed:a")


def test_user_dish_rejects_revert_and_hide(cat):
    dish_id, _ = cat.create(USER_DISH)
    with pytest.raises(CatalogError):
        cat.revert(dish_id)
    with pytest.raises(CatalogError):
        cat.set_hidden(dish_id, True)


@pytest.mark.parametrize("dish_id", ["seed:nope", "user:999", "user:abc", "garbage"])
def test_unknown_ids_not_found(cat, dish_id):
    with pytest.raises(NotFound):
        cat.get_view(dish_id)


def test_duplicate_name_warns_case_insensitively(cat):
    _, warnings = cat.create({**USER_DISH, "name": " alpha "})
    assert warnings == ['Another dish is already named "alpha".']


def test_duplicate_check_includes_hidden_dishes(cat):
    cat.set_hidden("seed:b", True)
    _, warnings = cat.create({**USER_DISH, "name": "BETA"})
    assert warnings == ['Another dish is already named "BETA".']


def test_saving_user_dish_does_not_warn_about_itself(cat):
    dish_id, _ = cat.create(USER_DISH)
    assert cat.save(dish_id, {**USER_DISH, "description": "edited"}) == []


def test_notes_lifecycle(cat):
    note = cat.add_note("seed:a", "  too salty  ")
    assert note.body == "too salty"
    assert cat.update_note(note.id, "less salt").edited_at is not None
    cat.delete_note(note.id)
    assert cat.notes("seed:a") == []


def test_blank_note_rejected_and_unknown_targets_not_found(cat):
    with pytest.raises(ValidationError):
        cat.add_note("seed:a", "   ")
    with pytest.raises(NotFound):
        cat.add_note("seed:nope", "x")
    with pytest.raises(NotFound):
        cat.notes("seed:nope")
    with pytest.raises(NotFound):
        cat.update_note(999, "x")
    with pytest.raises(NotFound):
        cat.delete_note(999)


def test_export_contains_all_user_data(cat):
    dish_id, _ = cat.create(USER_DISH)
    cat.save("seed:a", {"ingredients": A_INGREDIENTS, "steps": ["Chop.", "Fry well."]})
    cat.set_hidden("seed:b", True)
    cat.add_note("seed:a", "n1")
    exported = cat.export()
    assert exported["app"] == "recipe-butler" and exported["exported_at"]
    assert exported["user_dishes"] == [dish_to_dict(cat.get_view(dish_id).dish)]
    assert exported["personal_versions"][0]["seed_id"] == "seed:a"
    assert exported["personal_versions"][0]["steps"] == ["Chop.", "Fry well."]
    assert exported["hidden"] == ["seed:b"]
    assert exported["notes"][0]["dish_id"] == "seed:a" and exported["notes"][0]["body"] == "n1"


def test_orphaned_seed_rows_do_not_break_listing_and_are_exported(store, seeds):
    # Review Focus 2: a seed file removed while user data still points at it.
    store.set_override("seed:gone", [{"name": "x", "amount": ""}], ["y"], "h")
    store.set_hidden("seed:gone", True)
    store.add_note("seed:gone", "remember this")
    cat = Catalog(seeds, store)
    assert {v.dish.id for v in cat.list_views(include_hidden=True)} == set(seeds)
    exported = cat.export()
    assert exported["personal_versions"][0]["seed_id"] == "seed:gone"
    assert exported["hidden"] == ["seed:gone"]
    assert exported["notes"][0]["body"] == "remember this"
