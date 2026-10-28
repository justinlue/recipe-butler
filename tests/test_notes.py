from recipe_butler.notes import image_refs, parse_note

DISHES = {"greek salad": "seed:greek-salad", "toast": "user:3"}


def test_dish_reference_becomes_link_between_text():
    assert parse_note("Serve with [[Greek Salad]].", DISHES, set()) == [
        {"type": "text", "text": "Serve with "},
        {"type": "link", "text": "Greek Salad", "dish_id": "seed:greek-salad"},
        {"type": "text", "text": "."},
    ]


def test_links_match_names_case_insensitively_and_unknown_names_have_no_target():
    assert parse_note("[[ toast ]] and [[Waffles]]", DISHES, set()) == [
        {"type": "link", "text": "toast", "dish_id": "user:3"},
        {"type": "text", "text": " and "},
        {"type": "link", "text": "Waffles", "dish_id": None},
    ]


def test_image_embed_becomes_image_part_and_reports_whether_it_exists():
    assert parse_note("Look:\n![[image:12]]\n![[image:99]]", DISHES, {12}) == [
        {"type": "text", "text": "Look:\n"},
        {"type": "image", "image_id": 12, "found": True},
        {"type": "text", "text": "\n"},
        {"type": "image", "image_id": 99, "found": False},
    ]


def test_exclamation_mark_before_a_dish_link_is_just_punctuation():
    assert parse_note("Try this![[Greek Salad]]", DISHES, set()) == [
        {"type": "text", "text": "Try this!"},
        {"type": "link", "text": "Greek Salad", "dish_id": "seed:greek-salad"},
    ]


def test_blank_brackets_stay_as_typed():
    assert parse_note("[[ ]] and [[]]", DISHES, set()) == [{"type": "text", "text": "[[ ]] and [[]]"}]


def test_image_refs_lists_embedded_images_only():
    assert image_refs("![[image:3]] [[image:4]] ![[ image:5 ]] ![[image:3]]") == {3, 5}
