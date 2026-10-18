import pytest

from recipe_butler.model import Ingredient, ValidationError, dish_from_dict, dish_to_dict, seed_hash

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


@pytest.mark.parametrize("data", [[], "x", None, {**VALID, "ingredients": "bread"}, {**VALID, "steps": {"a": 1}},
                                  {**VALID, "ingredients": ["bread"]}, {**VALID, "name": 5}])
def test_wrong_shapes_raise_validation_error(data):
    with pytest.raises(ValidationError):
        dish_from_dict(data, "user:1")


def test_round_trip_and_hash_is_stable_and_sensitive():
    d = dish_from_dict(VALID, "user:1")
    assert dish_from_dict(dish_to_dict(d), "user:1") == d
    assert seed_hash(d) == seed_hash(dish_from_dict(VALID, "user:1"))
    assert seed_hash(d) != seed_hash(dish_from_dict({**VALID, "steps": ["Toast it well."]}, "user:1"))
