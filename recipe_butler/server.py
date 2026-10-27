"""Local HTTP server: a JSON API over the catalog plus the static front end."""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .catalog import Catalog, CatalogError, DishView, NotFound
from .model import ValidationError, dish_to_dict
from .search import parse_terms, search
from .store import Note

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Explicit, because Windows registry mappings can make mimetypes report .js as text/plain.
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


class BadRequest(Exception):
    pass


class Refused(Exception):
    """Request blocked to protect user data from other web pages; carries the HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _view_json(view: DishView, notes: list[Note]) -> dict:
    return {
        "dish": dish_to_dict(view.dish),
        "source": view.source,
        "customized": view.customized,
        "hidden": view.hidden,
        "rating": view.rating,
        "original": dish_to_dict(view.original) if view.original else None,
        "original_updated": view.original_updated,
        "changed_ingredients": list(view.changed_ingredients),
        "changed_steps": list(view.changed_steps),
        "notes": [_note_json(n) for n in notes],
    }


def _note_json(note: Note) -> dict:
    return {"id": note.id, "dish_id": note.dish_id, "body": note.body,
            "created_at": note.created_at, "edited_at": note.edited_at}


def _summary_json(view: DishView) -> dict:
    return {"id": view.dish.id, "name": view.dish.name, "category": view.dish.category,
            "source": view.source, "customized": view.customized, "hidden": view.hidden,
            "rating": view.rating, "total_minutes": view.dish.total_minutes}


def _note_id(segment: str) -> int:
    if not segment.isdigit():
        raise NotFound(segment)
    return int(segment)


class Handler(BaseHTTPRequestHandler):
    catalog: Catalog  # set on the subclass made by make_server
    timeout = 10  # drop idle connections (browsers open speculative ones) instead of holding a thread forever

    # -- plumbing ------------------------------------------------------------

    def log_message(self, format: str, *args) -> None:
        pass  # errors are reported via log_error / stderr below

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: object, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, code: str, messages: list[str]) -> None:
        self._json(status, {"error": code, "messages": messages})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            raise BadRequest("Request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise BadRequest("Request body must be a JSON object.")
        return data

    def _check_caller(self) -> None:
        """Only this app's own page may talk to the server.

        Host guards against DNS rebinding; requiring a JSON content type forces a CORS preflight (which this
        server never approves) on cross-site writes, and a foreign Origin is refused outright.
        """
        port = self.server.server_address[1]
        local = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host")
        if host is not None and host.strip().lower() not in local:
            raise Refused(403, "Unknown host.")
        if self.command in ("GET", "HEAD"):
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin.strip().lower() not in {f"http://{h}" for h in local}:
            raise Refused(403, "Requests from other sites are not allowed.")
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            raise Refused(415, "Requests must be sent as application/json.")

    def _dispatch(self) -> None:
        url = urlsplit(self.path)
        try:
            self._check_caller()
            if url.path.startswith("/api/"):
                segments = [unquote(s) for s in url.path[len("/api/"):].split("/")]
                self._api(segments, parse_qs(url.query))
            elif self.command in ("GET", "HEAD"):
                self._static(url.path)
            else:
                raise NotFound(url.path)
        except Refused as e:
            self._error(e.status, "refused", [str(e)])
        except BadRequest as e:
            self._error(400, "bad_request", [str(e)])
        except ValidationError as e:
            self._error(400, "invalid", e.messages)
        except CatalogError as e:
            self._error(400, "not_allowed", [str(e)])
        except NotFound:
            self._error(404, "not_found", ["Not found."])
        except Exception:
            traceback.print_exc(file=sys.stderr)
            self._error(500, "internal", ["Something went wrong; see the server console."])

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = _dispatch

    # -- routes --------------------------------------------------------------

    def _api(self, seg: list[str], query: dict[str, list[str]]) -> None:
        cat, method = self.catalog, self.command
        match (method, seg):
            case ("GET", ["ping"]):
                self._json(200, {"app": "recipe-butler"})
            case ("GET", ["dishes"]):
                include_hidden = query.get("hidden", ["0"])[0] == "1"
                sort = query.get("sort", ["category"])[0]
                self._json(200, [_summary_json(v) for v in cat.list_views(include_hidden, sort)])
            case ("POST", ["dishes"]):
                dish_id, warnings = cat.create(self._body())
                self._json(201, {"id": dish_id, "warnings": warnings})
            case ("GET", ["dishes", dish_id]):
                self._json(200, _view_json(cat.get_view(dish_id), cat.notes(dish_id)))
            case ("PUT", ["dishes", dish_id]):
                self._json(200, {"warnings": cat.save(dish_id, self._body())})
            case ("DELETE", ["dishes", dish_id]):
                cat.delete(dish_id)
                self._json(200, {})
            case ("POST", ["dishes", dish_id, "revert"]):
                cat.revert(dish_id)
                self._json(200, {})
            case ("POST", ["dishes", dish_id, ("hide" | "unhide") as action]):
                cat.set_hidden(dish_id, action == "hide")
                self._json(200, {})
            case ("PUT", ["dishes", dish_id, "rating"]):
                body = self._body()
                if "stars" not in body:
                    raise BadRequest('Send {"stars": 1-5}, or {"stars": null} to clear the rating.')
                cat.set_rating(dish_id, body["stars"])
                self._json(200, {})
            case ("POST", ["dishes", dish_id, "notes"]):
                self._json(201, _note_json(cat.add_note(dish_id, self._body().get("body"))))
            case ("PUT", ["notes", note_id]):
                self._json(200, _note_json(cat.update_note(_note_id(note_id), self._body().get("body"))))
            case ("DELETE", ["notes", note_id]):
                cat.delete_note(_note_id(note_id))
                self._json(200, {})
            case ("GET", ["search"]):
                terms = parse_terms(query.get("q", [""])[0])
                hits = search(cat.list_views(), terms)
                self._json(200, {"terms": terms, "hits": [
                    {"dish_id": h.dish_id, "name": h.name, "category": h.category, "matches": h.matches}
                    for h in hits]})
            case ("GET", ["export"]):
                filename = f"recipe-butler-export-{date.today().isoformat()}.json"
                self._json(200, cat.export(), {"Content-Disposition": f'attachment; filename="{filename}"'})
            case _:
                raise NotFound("/".join(seg))

    def _static(self, path: str) -> None:
        if path == "/":
            target = STATIC_DIR / "index.html"
        elif path.startswith("/static/"):
            target = (STATIC_DIR / unquote(path[len("/static/"):])).resolve()
        else:
            raise NotFound(path)
        if not target.is_file() or STATIC_DIR not in target.parents:
            raise NotFound(path)
        content_type = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), content_type)


def make_server(catalog: Catalog, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    # Threaded so one idle browser connection cannot stall every other request; Store serializes DB access.
    handler = type("RecipeHandler", (Handler,), {"catalog": catalog})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server
