import pytest

from recipe_butler.store import Store


def clock_from(*stamps):
    it = iter(stamps)
    return lambda: next(it)


def test_user_dish_crud_and_persistence(tmp_path):
    db = tmp_path / "sub" / "user.db"
    s = Store(db)
    n = s.create_user_dish({"name": "葱油饼"})
    assert s.user_dishes() == {n: {"name": "葱油饼"}}
    s.update_user_dish(n, {"name": "Scallion pancake"})
    s.close()
    s = Store(db)
    assert s.user_dishes() == {n: {"name": "Scallion pancake"}}
    s.close()


def test_deleting_user_dish_deletes_its_notes(tmp_path):
    s = Store(tmp_path / "u.db")
    n = s.create_user_dish({"name": "x"})
    s.add_note(f"user:{n}", "mine")
    s.add_note("seed:shakshuka", "keep")
    s.delete_user_dish(n)
    assert [x.body for x in s.all_notes()] == ["keep"]


def test_override_upsert_and_delete(tmp_path):
    s = Store(tmp_path / "u.db", clock=clock_from("t1", "t2"))
    s.set_override("seed:a", [{"name": "x", "amount": ""}], ["one"], "h1")
    s.set_override("seed:a", [{"name": "y", "amount": ""}], ["two"], "h1")
    o = s.overrides()["seed:a"]
    assert o.ingredients == [{"name": "y", "amount": ""}]
    assert o.steps == ["two"] and o.seed_hash == "h1" and o.updated_at == "t2"
    s.delete_override("seed:a")
    assert s.overrides() == {}


def test_hidden_toggle(tmp_path):
    s = Store(tmp_path / "u.db")
    s.set_hidden("seed:a", True)
    s.set_hidden("seed:a", True)
    assert s.hidden_ids() == {"seed:a"}
    s.set_hidden("seed:a", False)
    assert s.hidden_ids() == set()


def test_note_timestamps_and_order(tmp_path):
    s = Store(tmp_path / "u.db", clock=clock_from("t1", "t2", "t3"))
    note = s.add_note("seed:a", "too salty")
    assert (note.created_at, note.edited_at) == ("t1", None)
    second = s.add_note("seed:a", "kids liked it")
    edited = s.update_note(note.id, "less salt")
    assert (edited.body, edited.created_at, edited.edited_at) == ("less salt", "t1", "t3")
    assert [n.id for n in s.notes_for("seed:a")] == [note.id, second.id]
    assert s.notes_for("seed:b") == []


def test_unknown_ids_raise_key_error(tmp_path):
    s = Store(tmp_path / "u.db")
    for call in (lambda: s.update_user_dish(99, {}), lambda: s.delete_user_dish(99),
                 lambda: s.update_note(99, "x"), lambda: s.delete_note(99)):
        with pytest.raises(KeyError):
            call()


def test_default_clock_is_iso_utc(tmp_path):
    note = Store(tmp_path / "u.db").add_note("seed:a", "x")
    assert note.created_at.endswith("+00:00") and len(note.created_at) == 25
