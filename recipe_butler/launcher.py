"""`python -m recipe_butler`: start the server (or find the one already running) and open the browser."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path

from .catalog import Catalog
from .seeds import SeedError, load_seeds
from .server import make_server
from .store import Store

DEFAULT_PORT = 8765
PORT_TRIES = 20


def data_dir() -> Path:
    override = os.environ.get("RECIPE_BUTLER_DATA")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data"


def find_running(lock: Path, timeout: float = 1.0) -> int | None:
    """Port of a live recipe-butler server named by the lock file, or None if the lock is stale or junk."""
    try:
        port = json.loads(lock.read_text(encoding="utf-8"))["port"]
        if not isinstance(port, int):
            return None
        # No proxy: a system proxy without a localhost bypass would hide the running server.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as resp:
            if json.loads(resp.read().decode("utf-8")) == {"app": "recipe-butler"}:
                return port
    except Exception:
        return None
    return None


def pick_port(start: int = DEFAULT_PORT, tries: int = PORT_TRIES) -> int:
    for port in range(start, start + tries):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise OSError(f"No free port in {start}–{start + tries - 1}")


def write_lock(lock: Path, port: int) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")


def remove_lock(lock: Path, port: int) -> None:
    """Delete the lock only if it still names our port, so we never remove another server's lock."""
    try:
        if json.loads(lock.read_text(encoding="utf-8")).get("port") == port:
            lock.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recipe_butler", description="Offline recipe app.")
    parser.add_argument("--port", type=int, help=f"port to serve on (default: first free from {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args(argv)

    directory = data_dir()
    lock = directory / "server.lock"

    running = find_running(lock)
    if running is not None:
        url = f"http://127.0.0.1:{running}/"
        print(f"recipe-butler already running at {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    try:
        seeds = load_seeds()
    except SeedError as e:
        print(f"recipe-butler: bad seed recipe: {e}", file=sys.stderr)
        return 1

    store = Store(directory / "user.db")
    try:
        port = args.port if args.port is not None else pick_port()
        server = make_server(Catalog(seeds, store), port)
    except OSError as e:
        store.close()
        print(f"recipe-butler: cannot start server: {e}", file=sys.stderr)
        return 1

    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    write_lock(lock, port)
    print(f"recipe-butler running at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        remove_lock(lock, port)
        store.close()
    return 0
