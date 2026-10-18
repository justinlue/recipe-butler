from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "recipe_butler" / "static"


def test_frontend_files_exist():
    assert {"index.html", "app.js", "style.css"} <= {f.name for f in STATIC.iterdir()}


def test_frontend_never_injects_html():
    # Review Focus 5: user text must be rendered with textContent only.
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js


def test_frontend_has_no_external_urls():
    for f in STATIC.iterdir():
        text = f.read_text(encoding="utf-8")
        assert "http://" not in text and "https://" not in text, f.name
