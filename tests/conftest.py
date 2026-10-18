import json
import threading
import urllib.error
import urllib.request

import pytest

from recipe_butler.catalog import Catalog
from recipe_butler.seeds import load_seeds
from recipe_butler.server import make_server
from recipe_butler.store import Store


@pytest.fixture
def api_server(tmp_path):
    """A live server on a free port, serving the shipped seeds and a fresh store."""
    store = Store(tmp_path / "u.db")
    server = make_server(Catalog(load_seeds(), store), 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    store.close()


def request(port, method, path, body=None, raw=None):
    """Returns (status, headers, body bytes); HTTP errors are returned, not raised."""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if method != "GET":
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


@pytest.fixture
def api(api_server):
    port = api_server.server_address[1]

    def call(method, path, body=None, raw=None):
        status, _, payload = request(port, method, path, body, raw)
        return status, json.loads(payload.decode("utf-8"))

    return call
