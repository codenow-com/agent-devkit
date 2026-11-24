"""The HTML of the hub's data views, part 2: Valkey keys, one key (a stream newest first), and the search page.

Pure functions of the data that cn_hub_valkey and cn_hub_search returned (already masked); every value is escaped.
"""
from __future__ import annotations

from cn_hub_render import chip, cut, e
from cn_hub_render_exclude import stream_hidden_line, stream_script, stream_x
from cn_hub_render_runs import href, pretty, shell, status_chip, when

EVENT_KINDS = ("run_accepted", "run_started", "stage_started", "stage_ended", "stage_stats", "llm_started",
               "llm_ended", "tool_started", "tool_ended", "run_finished", "heartbeat", "agent_manifest",
               "agent_infra_profile", "debug")


def ttl_text(ttl) -> str:
    if ttl == -1:
        return "no expiry"
    if ttl == -2:
        return "gone"
    return f"{ttl} s" if isinstance(ttl, int) else ""


def keys_page(project: str, data: dict) -> str:
    form = (f'<form class="bar" method="get" action="{e(href(project, "valkey"))}"><label>key pattern (SCAN MATCH)'
            f'<input name="pattern" value="{e(data.get("pattern"))}" size="40"></label>'
            '<button type="submit">List</button></form>')
    rows = "".join(
        f'<tr><td class="mono"><a href="{e(href(project, "valkey", k["key"]))}">{e(k["key"])}</a></td>'
        f'<td>{e(k.get("type"))}</td><td class="num">{e(ttl_text(k.get("ttl")))}</td>'
        f'<td class="num">{e(k.get("size") if k.get("size") is not None else "")}</td></tr>'
        for k in data.get("keys") or [])
    note = (f'<p class="note">{len(data.get("keys") or [])} keys'
            + ("" if data.get("complete") else f', the first {data.get("cap")} only (narrow the pattern)') + "</p>")
    table = ('<div class="tw"><table class="data"><thead><tr><th>key</th><th>type</th><th>TTL</th><th>size</th>'
             '</tr></thead><tbody>' + (rows or '<tr><td colspan="4" class="note">No key matches.</td></tr>')
             + "</tbody></table></div>")
    return shell(f"Valkey of {project}", project, form + note + table, "valkey")


def key_page(project: str, data: dict) -> str:
    key, kind = data.get("key") or "", data.get("type") or "none"
    head = (f'<p><a href="{e(href(project, "valkey"))}">← all keys</a></p><div class="panel"><p>'
            f'<b class="mono">{e(key)}</b> {chip(kind, "muted")} TTL {e(ttl_text(data.get("ttl")))}'
            + (f' · size {e(data.get("size") if data.get("size") is not None else data.get("length"))}'
               if data.get("size") is not None or data.get("length") is not None else "") + "</p></div>")
    if kind == "none":
        body = '<p class="note">No such key (or it expired).</p>'
    elif kind == "stream":
        body = stream_body(project, key, data)
    elif kind == "hash":
        body = pairs_table(data.get("fields") or [], "field", "value")
    elif kind == "zset":
        body = pairs_table(data.get("items") or [], "member", "score")
    elif kind in ("list", "set"):
        body = pairs_table([[i, v] for i, v in enumerate(data.get("items") or [])], "#", "value")
    elif kind == "string":
        body = pretty(data.get("value") or "") + ('<p class="note">Cut at 4 KB.</p>' if data.get("truncated") else "")
    else:
        body = f'<p class="note">The hub does not show {e(kind)} keys.</p>'
    return shell(f"Valkey key {cut(key, 60)}", project, head + body, "valkey")


def pairs_table(pairs: list, left: str, right: str) -> str:
    rows = "".join(f'<tr><td class="mono">{e(a)}</td><td>{pretty(b) if len(str(b)) > 60 else e(b)}</td></tr>'
                   for a, b in pairs)
    return (f'<div class="tw"><table class="data"><thead><tr><th>{left}</th><th>{right}</th></tr></thead><tbody>'
            + (rows or '<tr><td colspan="2" class="note">Empty.</td></tr>') + "</tbody></table></div>")


def stream_body(project: str, key: str, data: dict) -> str:
    current, exclude = data.get("kind") or "", list(data.get("exclude") or [])

    def link_of(kinds, before=None):
        return href(project, "valkey", key, before=before, kind=current, exclude=",".join(kinds))
    options = '<option value="">all</option>' + "".join(
        f'<option value="{e(k)}"{" selected" if k == current else ""}>{e(k)}</option>' for k in EVENT_KINDS)
    form = (f'<form class="bar" method="get" action="{e(href(project, "valkey", key))}"><label>event kind'
            f'<select name="kind">{options}</select></label>'
            + (f'<input type="hidden" name="exclude" value="{e(",".join(exclude))}">' if exclude else "")
            + '<button type="submit">Show</button>'
            f'<span class="note">newest first, 50 per page</span></form>')
    rows = []
    for entry in data.get("entries") or []:
        event = entry.get("event") or {}
        run_id = event.get("run_id")
        run_link = (f'<a class="mono" href="{e(href(project, "runs", str(run_id)))}">{e(run_id)}</a>'
                    if run_id else "")
        brief = " ".join(str(event[k]) for k in ("pipeline", "stage", "tool", "status", "summary", "text")
                         if event.get(k) not in (None, ""))
        fields = event if event else entry.get("fields")
        kind = str(event.get("kind") or "")
        after = exclude + [kind] if kind and kind not in exclude else exclude
        rows.append(f'<tr><td class="mono">{e(entry["id"])}</td><td class="mono">{e(when(entry.get("ms")))}</td>'
                    f'<td>{e(kind)}{stream_x(kind, link_of(after), after)}</td><td>{run_link}</td>'
                    f'<td>{e(cut(brief, 120))}</td>'
                    f'<td><details><summary>fields</summary>{pretty(fields)}</details></td></tr>')
    table = ('<div class="tw"><table class="data"><thead><tr><th>entry id</th><th>time (UTC)</th><th>kind</th>'
             '<th>run</th><th>about</th><th></th></tr></thead><tbody>'
             + ("".join(rows) or '<tr><td colspan="6" class="note">No entry.</td></tr>') + "</tbody></table></div>")
    pager = [f'<a href="{e(link_of(exclude))}">newest</a>']
    if data.get("next"):
        pager.append(f'<a href="{e(link_of(exclude, data["next"]))}">older</a>')
    store = f"cn-hub-exclude:{project}:{key}"
    return (form + stream_hidden_line(data, link_of) + table + '<div class="pager">' + " ".join(pager) + "</div>"
            + stream_script(store))


def search_page(project: str, data: dict) -> str:
    q = data.get("q") or ""
    form = (f'<form class="bar" method="get" action="{e(href(project, "search"))}"><label>search runs, events and '
            f'keys<input name="q" value="{e(q)}" size="48" autofocus></label><button type="submit">Search</button>'
            '</form>')
    if not q:
        return shell(f"Search in {project}", project, form + '<p class="note">Run id prefix, subject, pipeline, '
                     'status, summary or output text; event fields of the newest 5000 entries of swarm:events and '
                     'swarm:debug; key names.</p>', "search")
    parts = [form]
    for name, message in (data.get("errors") or {}).items():
        parts.append(f'<p class="err">{e(name)}: {e(message)}</p>')
    runs = data.get("runs") or []
    rows = "".join(
        f'<tr><td class="mono"><a href="{e(href(project, "runs", str(r.get("run_id"))))}">{e(r.get("run_id"))}</a>'
        f'</td><td class="mono">{e(when(r.get("started_at")))}</td><td>{e(r.get("pipeline"))}</td>'
        f'<td>{status_chip(r.get("status"))}</td><td class="sum">{e(cut(str(r.get("summary") or ""), 140))}</td></tr>'
        for r in runs)
    parts.append(f'<div class="panel"><h2>Runs ({len(runs)})</h2>' + (
        '<div class="tw"><table class="data"><tbody>' + rows + "</tbody></table></div>" if runs
        else '<p class="note">No run.</p>') + "</div>")
    events = data.get("events") or []
    rows = "".join(
        f'<tr><td class="mono"><a href="{e(href(project, "valkey", ev["stream"], before=next_of(ev["id"])))}">'
        f'{e(ev["stream"])} {e(ev["id"])}</a></td><td class="mono">{e(when(ev.get("ms")))}</td>'
        f'<td>{e(ev.get("kind") or "")}</td><td>' + (
            f'<a class="mono" href="{e(href(project, "runs", str(ev["run_id"])))}">{e(ev["run_id"])}</a>'
            if ev.get("run_id") else "") + f'</td><td class="sum">{e(ev.get("text"))}</td></tr>' for ev in events)
    parts.append(f'<div class="panel"><h2>Events ({len(events)})</h2>' + (
        '<div class="tw"><table class="data"><tbody>' + rows + "</tbody></table></div>" if events
        else '<p class="note">No event.</p>') + "</div>")
    keys = data.get("keys") or []
    parts.append(f'<div class="panel"><h2>Keys ({len(keys)})</h2>' + (
        "<ul>" + "".join(f'<li><a class="mono" href="{e(href(project, "valkey", k))}">{e(k)}</a></li>' for k in keys)
        + "</ul>" if keys else '<p class="note">No key.</p>') + "</div>")
    return shell(f"Search in {project}", project, "".join(parts), "search")


def next_of(entry_id: str) -> str:
    ms, _, seq = str(entry_id).partition("-")
    return f"{ms}-{int(seq) + 1}" if seq.isdigit() else entry_id
