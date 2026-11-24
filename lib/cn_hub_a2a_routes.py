"""The routes of the hub's A2A "Try it" (lib/cn_hub_a2a.py), called by lib/cn_hub.py before the read-only views:

    GET  /s/<project>/try            the page          GET /api/s/<project>/a2a/card   the parsed card
    POST /api/s/<project>/a2a/send   one send (any other method on it: 405)

The POST is refused (403/411/413/415) unless it comes from the hub's own origin, carries the per-process CSRF token in
X-CN-Hub-Token and a JSON body of at most MAX_BODY; one send per sandbox runs at a time (409).
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
from urllib.parse import unquote

import cn_hub_a2a as a2a
import cn_hub_render_a2a as render_a2a
from cn_hub_a2a_token import plan
from cn_hub_render_runs import shell

ROUTE = re.compile(r"^/(api/)?s/([^/]+)/(try|a2a/card|a2a/send)$")
HTML = "text/html; charset=utf-8"
JSON = "application/json"
CSRF = secrets.token_urlsafe(32)   # one per hub process; embedded in the page, required on every POST
_busy, _busy_lock = {}, threading.Lock()


def match(path: str):
    """(api, project, route) when the path is one of these routes, else None."""
    found = ROUTE.match(path)
    if not found or bool(found.group(1)) != (found.group(3) != "try"):
        return None
    return bool(found.group(1)), unquote(found.group(2)), found.group(3)


def sandbox_named(sandboxes: list, project: str):
    return next((sb for sb in sandboxes if sb.get("project") == project), None)


def agent_log(sb: dict, docker) -> str:
    container = next((s.get("container") for s in sb.get("services") or [] if s.get("name") == "agent"), "")
    return docker("logs", "--tail", "3000", container) if container else ""


def as_json(code: int, value) -> tuple:
    return code, json.dumps(value, indent=1, ensure_ascii=False, default=str), JSON


def get_route(path: str, sandboxes: list, docker, opener=a2a.no_proxy_open):
    """(status, body, content type) of a GET on these routes, or None when the path is not one of them."""
    found = match(path)
    if not found:
        return None
    api, project, route = found
    sb = sandbox_named(sandboxes, project)
    if sb is None:
        return as_json(404, {"error": "no such sandbox"}) if api else \
            (404, shell("Not found", project, '<p class="err">No such sandbox.</p>'), HTML)
    if route == "a2a/send":
        return as_json(405, {"error": "use POST"})
    port = (sb.get("console") or {}).get("port")
    card, endpoint, error = None, "", ""
    try:
        card = a2a.parse_card(a2a.fetch_card(port, opener)) if port else None
        endpoint = a2a.endpoint(card, port) if card else ""
        error = "" if card else "The sandbox has no console port: is it running?"
    except a2a.A2AFailure as exc:
        error = exc.message
    if api:
        return as_json(200, {"card": card, "endpoint": endpoint}) if card else as_json(502, {"error": error})
    page = render_a2a.try_page(project, CSRF, card, endpoint, plan(sb), a2a.audience_mode(agent_log(sb, docker)),
                               error)
    return 200, page, HTML


def refuse(headers, port: int, csrf: str):
    """None when a POST may go on, else (status, reason): same origin, the CSRF header, JSON, a size limit."""
    origins = (f"http://localhost:{port}", f"http://127.0.0.1:{port}")
    origin, referer = headers.get("Origin"), headers.get("Referer") or ""
    if origin is not None:
        if origin not in origins:
            return 403, "cross-origin request refused"
    elif not any(referer == o or referer.startswith(o + "/") for o in origins):
        return 403, "a request without the hub's origin is refused"
    if not hmac.compare_digest((headers.get("X-CN-Hub-Token") or "").encode(), csrf.encode()):
        return 403, "the X-CN-Hub-Token header is missing or wrong (reload the page)"
    if (headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
        return 415, "only application/json is accepted"
    try:
        length = int(headers.get("Content-Length") or "-1")
    except ValueError:
        length = -1
    if length < 0:
        return 411, "Content-Length is required"
    if length > a2a.MAX_BODY:
        return 413, "the request is larger than the hub accepts"
    return None


def busy(project: str) -> threading.Lock:
    with _busy_lock:
        return _busy.setdefault(project, threading.Lock())


def post_send(sb: dict, raw: bytes, log: str = "", **kw) -> tuple:
    """(status, value) of one send for one sandbox; one send per sandbox at a time."""
    lock = busy(sb.get("project") or "")
    if not lock.acquire(blocking=False):
        return 409, {"ok": False, "error": "a request to this sandbox is still running; wait for it"}
    try:
        return 200, {"ok": True, **a2a.send(sb, a2a.parse_request(raw), log, **kw)}
    except a2a.A2AFailure as exc:
        return (exc.status if exc.status >= 400 else 200), {"ok": False, "error": exc.message, **exc.extra}
    finally:
        lock.release()


def post_route(path: str, headers, rfile, sandboxes_fn, port: int, docker, csrf: str = None, **kw) -> tuple:
    """(status, body, content type) of a POST; only /api/s/<project>/a2a/send takes one."""
    found = match(path)
    if not found or found[2] != "a2a/send":
        return as_json(405 if found else 404, {"error": "method not allowed" if found else "not found"})
    refused = refuse(headers, port, CSRF if csrf is None else csrf)
    if refused:
        return as_json(refused[0], {"ok": False, "error": refused[1]})
    raw = rfile.read(int(headers.get("Content-Length")))
    sb = sandbox_named(sandboxes_fn(), found[1])
    if sb is None:
        return as_json(404, {"ok": False, "error": "no such sandbox"})
    code, value = post_send(sb, raw, agent_log(sb, docker), **kw)
    return as_json(code, value)
