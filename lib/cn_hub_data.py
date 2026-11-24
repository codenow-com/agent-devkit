"""The routes of the sandbox hub's data views (runs, Valkey, search), pages and JSON, for one sandbox each.

    /s/<project>/runs[?status=&pipeline=&since=&page=]   /api/s/<project>/runs
    /s/<project>/runs/<run_id>                            /api/s/<project>/runs/<run_id>
    /s/<project>/valkey[?pattern=]                        /api/s/<project>/valkey/keys[?pattern=]
    /s/<project>/valkey/<key>[?before=&kind=]             /api/s/<project>/valkey/key?key=[&before=&kind=]
    /s/<project>/search?q=                                /api/s/<project>/search?q=

`<project>` must be one of the sandboxes the hub found in Docker. Everything here only reads, and every answer is
masked and capped (MAX_BODY).
"""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import parse_qs, unquote

import cn_hub_render_runs as render_runs
import cn_hub_render_valkey as render_valkey
import cn_hub_runs as runs
import cn_hub_search as search
import cn_hub_valkey as valkey
from cn_hub_exec import ExecError, Sandbox, mask_log, run_process

MAX_BODY = 6 * 1024 * 1024
HTML = "text/html; charset=utf-8"
JSON = "application/json"
_sandboxes, _lock = {}, threading.Lock()


def sandbox_of(project: str, runner) -> Sandbox:
    """One Sandbox per project, kept 30 s (its container ids change when the sandbox restarts)."""
    with _lock:
        hit = _sandboxes.get((project, id(runner)))
        if hit and time.monotonic() - hit[0] < 30:
            return hit[1]
        sb = Sandbox(project, runner)
        _sandboxes[(project, id(runner))] = (time.monotonic(), sb)
        return sb


def query_of(raw: str) -> dict:
    return {k: v[0] for k, v in parse_qs(raw or "", keep_blank_values=False).items() if v}


def as_json(code: int, value) -> tuple:
    body = json.dumps(value, indent=1, ensure_ascii=False, default=str)
    if len(body.encode()) > MAX_BODY:
        return 413, json.dumps({"error": "the answer is larger than the hub sends; narrow it down"}), JSON
    return code, body, JSON


def as_html(code: int, body: str) -> tuple:
    if len(body.encode()) > MAX_BODY:
        body = render_runs.shell("Too large", "", "<p class=\"err\">The page is larger than the hub sends.</p>")
        code = 413
    return code, body, HTML


def handle(path: str, raw_query: str, projects: list, runner=run_process) -> tuple:
    """(status, body, content type) of one data route, or None when the path is not one of them."""
    api = path.startswith("/api/s/")
    rest = path[len("/api/s/" if api else "/s/"):]
    project, _, sub = rest.partition("/")
    project = unquote(project)
    query = query_of(raw_query)
    if project not in projects:
        return (as_json(404, {"error": "no such sandbox"}) if api
                else as_html(404, render_runs.shell("Not found", project, "<p class=\"err\">No such sandbox.</p>")))
    try:
        sb = sandbox_of(project, runner)
        return (api_route if api else page_route)(sb, sub, query)
    except ExecError as exc:
        message = mask_log(str(exc))
        if api:
            return as_json(502, {"error": message})
        return as_html(502, render_runs.shell("Not readable", project, f"<p class=\"err\">{render_runs.e(message)}"
                                              "</p>"))


def api_route(sb, sub: str, query: dict) -> tuple:
    if sub == "runs":
        return as_json(200, runs.list_runs(sb, query))
    if sub.startswith("runs/"):
        found = runs.run_detail(sb, unquote(sub[len("runs/"):]))
        return as_json(200, found) if found else as_json(404, {"error": "no such run"})
    if sub == "valkey/keys":
        return as_json(200, valkey.keys(sb, query.get("pattern") or "*"))
    if sub == "valkey/key":
        if not query.get("key"):
            return as_json(400, {"error": "key= is missing"})
        return as_json(200, valkey.key_view(sb, query["key"], query.get("before", ""), query.get("kind", "")))
    if sub == "search":
        return as_json(200, search.search(sb, query.get("q", "")))
    return as_json(404, {"error": "not found"})


def page_route(sb, sub: str, query: dict) -> tuple:
    project = sb.project
    if sub in ("", "runs"):
        return as_html(200, render_runs.runs_page(project, runs.list_runs(sb, query)))
    if sub.startswith("runs/"):
        found = runs.run_detail(sb, unquote(sub[len("runs/"):]))
        if not found:
            return as_html(404, render_runs.shell("Run not found", project, "<p class=\"err\">No such run.</p>"))
        return as_html(200, render_runs.run_page(project, found))
    if sub == "valkey":
        return as_html(200, render_valkey.keys_page(project, valkey.keys(sb, query.get("pattern") or "*")))
    if sub.startswith("valkey/"):
        key = unquote(sub[len("valkey/"):])
        return as_html(200, render_valkey.key_page(project, valkey.key_view(sb, key, query.get("before", ""),
                                                                              query.get("kind", ""))))
    if sub == "search":
        return as_html(200, render_valkey.search_page(project, search.search(sb, query.get("q", ""))))
    return as_html(404, render_runs.shell("Not found", project, "<p class=\"err\">No such page.</p>"))
