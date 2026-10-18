import json

import pytest

from conftest import request


def test_ping(api):
    assert api("GET", "/api/ping") == (200, {"app": "recipe-butler"})


def test_list_and_get(api):
    status, dishes = api("GET", "/api/dishes")
    assert status == 200 and len(dishes) == 13
    assert set(dishes[0]) == {"id", "name", "category", "source", "customized", "hidden"}
    status, view = api("GET", "/api/dishes/seed%3Ashakshuka")
    assert status == 200
    assert view["dish"]["name"] == "Shakshuka" and view["customized"] is False and view["notes"] == []
    assert view["original"] is None and view["changed_ingredients"] == [False] * len(view["dish"]["ingredients"])


def test_create_customize_note_search_flow(api):
    status, created = api("POST", "/api/dishes", {"name": "Toast", "ingredients": [{"name": "bread", "amount": "2"}],
                                                  "steps": ["Toast."]})
    assert status == 201 and created["id"].startswith("user:") and created["warnings"] == []
    _, guac = api("GET", "/api/dishes/seed%3Aguacamole")
    ingredients = guac["dish"]["ingredients"] + [{"name": "tomato", "amount": "1"}]
    assert api("PUT", "/api/dishes/seed%3Aguacamole", {"ingredients": ingredients, "steps": guac["dish"]["steps"]}) \
        == (200, {"warnings": []})
    _, guac = api("GET", "/api/dishes/seed%3Aguacamole")
    assert guac["customized"] and guac["changed_ingredients"][-1] is True and guac["original"]["name"] == "Guacamole"
    status, note = api("POST", "/api/dishes/seed%3Aguacamole/notes", {"body": "more lime"})
    assert status == 201 and note["body"] == "more lime"
    status, result = api("GET", "/api/search?q=avocado%2C+tomato")
    assert status == 200 and result["terms"] == ["avocado", "tomato"]
    assert [h["dish_id"] for h in result["hits"]] == ["seed:guacamole"]
    assert result["hits"][0]["matches"]["tomato"] == ["tomato"]
    assert api("POST", "/api/dishes/seed%3Aguacamole/revert") == (200, {})
    _, guac = api("GET", "/api/dishes/seed%3Aguacamole")
    assert not guac["customized"] and [n["body"] for n in guac["notes"]] == ["more lime"]


def test_hide_unhide_and_hidden_listing(api):
    assert api("POST", "/api/dishes/seed%3Aguacamole/hide") == (200, {})
    assert len(api("GET", "/api/dishes")[1]) == 12
    assert len(api("GET", "/api/dishes?hidden=1")[1]) == 13
    api("POST", "/api/dishes/seed%3Aguacamole/unhide")
    assert len(api("GET", "/api/dishes")[1]) == 13


def test_note_edit_and_delete(api):
    _, note = api("POST", "/api/dishes/seed%3Ashakshuka/notes", {"body": "a"})
    status, edited = api("PUT", f"/api/notes/{note['id']}", {"body": "b"})
    assert status == 200 and edited["body"] == "b" and edited["edited_at"]
    assert api("DELETE", f"/api/notes/{note['id']}") == (200, {})
    assert api("DELETE", f"/api/notes/{note['id']}")[0] == 404


def test_user_dish_edit_and_delete(api):
    _, created = api("POST", "/api/dishes", {"name": "Toast", "ingredients": [{"name": "bread"}], "steps": ["Toast."]})
    path = "/api/dishes/" + created["id"].replace(":", "%3A")
    status, result = api("PUT", path, {"name": "shakshuka", "ingredients": [{"name": "bread"}], "steps": ["Toast."]})
    assert status == 200 and result["warnings"] == ['Another dish is already named "shakshuka".']
    assert api("DELETE", path) == (200, {})
    assert api("GET", path)[0] == 404


def test_unicode_and_html_round_trip(api):
    # Review Focus 1 + 5 (server half)
    body = "多放葱 <script>alert(1)</script>"
    api("POST", "/api/dishes/seed%3Aguacamole/notes", {"body": body})
    _, view = api("GET", "/api/dishes/seed%3Aguacamole")
    assert view["notes"][0]["body"] == body


@pytest.mark.parametrize("raw", [
    b"{not json",
    b"[1,2]",
    b"\xff\xfe",
    json.dumps({"name": "x", "servings": "four", "ingredients": [], "steps": []}).encode(),
])
def test_malformed_input_is_400_and_server_survives(api, raw):
    # Review Focus 3
    status, err = api("POST", "/api/dishes", raw=raw)
    assert status == 400 and err["error"] in {"bad_request", "invalid"} and err["messages"]
    assert api("GET", "/api/ping")[0] == 200


def test_validation_messages_are_returned(api):
    status, err = api("POST", "/api/dishes", {"name": "", "ingredients": [], "steps": []})
    assert status == 400 and err == {"error": "invalid", "messages": [
        "Name is required.", "Add at least one ingredient.", "Add at least one step."]}


def test_blank_note_is_400(api):
    assert api("POST", "/api/dishes/seed%3Ashakshuka/notes", {"body": " "})[0] == 400


def test_delete_seed_not_allowed(api):
    status, err = api("DELETE", "/api/dishes/seed%3Ashakshuka")
    assert status == 400 and err["error"] == "not_allowed"


@pytest.mark.parametrize("method,path", [("GET", "/api/dishes/seed%3Anope"), ("GET", "/api/nothing"),
                                         ("PUT", "/api/notes/abc"), ("POST", "/api/dishes/seed%3Anope/notes")])
def test_unknown_targets_404(api, method, path):
    status, err = api(method, path, {"body": "x"} if method != "GET" else None)
    assert status == 404 and err["error"] == "not_found"


def test_export_is_attachment(api_server):
    status, headers, payload = request(api_server.server_address[1], "GET", "/api/export")
    assert status == 200 and "recipe-butler-export-" in headers["Content-Disposition"]
    assert json.loads(payload)["app"] == "recipe-butler"


def test_static_traversal_blocked(api_server):
    port = api_server.server_address[1]
    for path in ("/static/..%2F..%2Fpyproject.toml", "/static/../server.py", "/static/%2e%2e/catalog.py"):
        assert request(port, "GET", path)[0] == 404


def test_index_served(api_server):
    status, headers, _ = request(api_server.server_address[1], "GET", "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")


def test_idle_connection_does_not_block_other_requests(api_server):
    # Browsers open speculative connections that never send a request.
    import socket
    port = api_server.server_address[1]
    with socket.create_connection(("127.0.0.1", port)):
        status, _, _ = request(port, "GET", "/api/ping")
    assert status == 200


def _raw(port, method, path, headers):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=b"" if method != "GET" else None, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    resp.read()
    conn.close()
    return status


def test_cross_site_simple_post_is_rejected(api_server, api):
    # A page on another site can send text/plain POSTs without a CORS preflight.
    port = api_server.server_address[1]
    status = _raw(port, "POST", "/api/dishes/seed%3Apancakes/hide",
                  {"Content-Type": "text/plain", "Origin": "http://evil.example"})
    assert status in (403, 415)
    assert _raw(port, "POST", "/api/dishes/seed%3Apancakes/hide", {}) == 415
    assert not api("GET", "/api/dishes/seed%3Apancakes")[1]["hidden"]


def test_foreign_origin_rejected_even_with_json(api_server, api):
    port = api_server.server_address[1]
    status = _raw(port, "POST", "/api/dishes/seed%3Apancakes/hide",
                  {"Content-Type": "application/json", "Origin": "http://evil.example"})
    assert status == 403
    assert not api("GET", "/api/dishes/seed%3Apancakes")[1]["hidden"]


def test_same_origin_post_allowed(api_server):
    port = api_server.server_address[1]
    assert _raw(port, "POST", "/api/dishes/seed%3Apancakes/hide",
                {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}) == 200


def test_foreign_host_header_rejected(api_server):
    # DNS rebinding: a hostile name resolving to 127.0.0.1 must not read user data.
    port = api_server.server_address[1]
    assert _raw(port, "GET", "/api/export", {"Host": f"evil.example:{port}"}) == 403
    assert _raw(port, "GET", "/api/ping", {"Host": f"localhost:{port}"}) == 200
