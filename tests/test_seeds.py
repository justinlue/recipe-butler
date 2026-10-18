import json

import pytest

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
