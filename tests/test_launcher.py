import json
import socket

import pytest

from recipe_butler import launcher
from recipe_butler.launcher import data_dir, find_running, pick_port, remove_lock, write_lock
from recipe_butler.seeds import SeedError


def free_unused_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_data_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RECIPE_BUTLER_DATA", str(tmp_path))
    assert data_dir() == tmp_path
    monkeypatch.delenv("RECIPE_BUTLER_DATA")
    assert data_dir().name == "data" and (data_dir().parent / "recipe_butler").is_dir()


def test_missing_lock_is_none(tmp_path):
    assert find_running(tmp_path / "server.lock") is None


def test_stale_lock_is_ignored(tmp_path):
    # Review Focus 4
    lock = tmp_path / "server.lock"
    lock.write_text(json.dumps({"port": free_unused_port(), "pid": 999999}), encoding="utf-8")
    assert find_running(lock) is None


@pytest.mark.parametrize("content", ["not json", "[]", '{"port": "x"}'])
def test_garbage_lock_is_ignored(tmp_path, content):
    lock = tmp_path / "server.lock"
    lock.write_text(content, encoding="utf-8")
    assert find_running(lock) is None


def test_detects_running_server(tmp_path, api_server):
    lock = tmp_path / "server.lock"
    port = api_server.server_address[1]
    write_lock(lock, port)
    assert find_running(lock) == port


def test_pick_port_skips_taken():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        taken = s.getsockname()[1]
        assert pick_port(taken, 3) != taken


def test_pick_port_gives_up(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        with pytest.raises(OSError, match="No free port"):
            pick_port(s.getsockname()[1], 1)


def test_remove_lock_only_if_ours(tmp_path):
    lock = tmp_path / "server.lock"
    write_lock(lock, 1)
    remove_lock(lock, 2)
    assert lock.exists()
    remove_lock(lock, 1)
    assert not lock.exists()
    remove_lock(lock, 1)  # already gone: no error


def test_main_reports_bad_seed(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RECIPE_BUTLER_DATA", str(tmp_path))

    def broken():
        raise SeedError("x.json: bad")

    monkeypatch.setattr(launcher, "load_seeds", broken)
    assert launcher.main(["--no-browser"]) == 1
    assert "x.json" in capsys.readouterr().err


def test_main_reuses_running_server(monkeypatch, tmp_path, api_server, capsys):
    monkeypatch.setenv("RECIPE_BUTLER_DATA", str(tmp_path))
    port = api_server.server_address[1]
    write_lock(tmp_path / "server.lock", port)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", opened.append)
    assert launcher.main([]) == 0
    assert opened == [f"http://127.0.0.1:{port}/"]
    assert "already running" in capsys.readouterr().out


def test_find_running_ignores_system_proxy(monkeypatch, tmp_path, api_server):
    # A proxy without a localhost bypass must not hide the running server.
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{free_unused_port()}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    lock = tmp_path / "server.lock"
    write_lock(lock, api_server.server_address[1])
    assert find_running(lock) == api_server.server_address[1]
