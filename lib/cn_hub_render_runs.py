"""The HTML of the hub's data views, part 1: the page shell and tabs, the runs list and one run in detail.

Pure functions of the data that cn_hub_runs returned (already masked); every value is escaped here; the only
script hides event kinds on a run's event list (cn_hub_render_exclude).
"""
from __future__ import annotations

import datetime
import json
from urllib.parse import quote, urlencode

from cn_hub_render import STYLE, chip, cut, e
from cn_hub_render_exclude import EXCLUDE_STYLE, RUN_HIDDEN_LINE, RUN_SCRIPT, run_x

EXTRA_STYLE = """
main.wide{max-width:1400px}
nav.crumbs{font-size:13px;margin:0 0 6px}nav.crumbs a{color:var(--accent)}
nav.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:10px 0 16px;flex-wrap:wrap}
nav.tabs a{padding:6px 14px;border:1px solid transparent;border-bottom:none;border-radius:8px 8px 0 0;
color:var(--accent);text-decoration:none;font-weight:600}
nav.tabs a.on{background:var(--surface);border-color:var(--line);color:var(--text);margin-bottom:-1px}
form.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:end;margin:0 0 12px;font-size:13px}
form.bar label{display:flex;flex-direction:column;gap:2px;color:var(--muted)}
form.bar input,form.bar select,form.bar button{font:inherit;padding:4px 8px;border:1px solid var(--line);
border-radius:6px;background:var(--surface);color:var(--text)}
form.bar button{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}
.tw{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:10px}
table.data{border-collapse:collapse;width:100%;font-size:13px}
table.data th{text-align:left;color:var(--muted);font-weight:600;padding:7px 10px;border-bottom:1px solid var(--line);
white-space:nowrap}
table.data td{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}
table.data tr:last-child td{border-bottom:none}
td.mono,.mono{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
td.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
td.sum{max-width:420px;color:var(--muted)}
.pager{display:flex;gap:12px;align-items:center;margin:10px 0;font-size:13px}.pager a{color:var(--accent)}
pre.json{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--mutedbg);padding:10px;
border-radius:8px;overflow:auto;max-height:420px;white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:0 0 14px}
.panel h2{font-size:15px;margin:0 0 8px}
.err{background:var(--badbg);color:var(--bad);padding:10px 14px;border-radius:8px}
.note{color:var(--muted);font-size:13px}
.tl{display:grid;grid-template-columns:minmax(120px,220px) 1fr;gap:4px 10px;align-items:center;font-size:12px}
.tl .bar{height:14px;border-radius:4px;background:var(--accent);opacity:.75;min-width:3px}
.tl .bar.bad{background:var(--bad)}.tl .track{position:relative;height:14px;background:var(--mutedbg);border-radius:4px}
.tl .track .bar{position:absolute;top:0}
.kpis{display:flex;flex-wrap:wrap;gap:18px;font-size:13px}.kpis b{display:block;font-size:17px}
"""

TONES = {"completed": "ok", "succeeded": "ok", "ok": "ok", "running": "warn", "accepted": "warn", "queued": "warn",
         "failed": "bad", "error": "bad", "crashed": "bad", "blocked": "bad", "halted": "bad", "timeout": "bad"}


def status_chip(status) -> str:
    return chip(str(status or "?"), TONES.get(str(status or "").lower(), "muted"))


def href(project: str, *parts: str, **query) -> str:
    path = "/s/" + quote(project, safe="") + "".join("/" + quote(p, safe="") for p in parts)
    query = {k: v for k, v in query.items() if v not in (None, "")}
    return path + ("?" + urlencode(query) if query else "")


def when(value) -> str:
    """An ISO time or epoch milliseconds as `YYYY-MM-DD HH:MM:SS` (UTC), or the value itself."""
    if isinstance(value, (int, float)):
        return datetime.datetime.utcfromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value or "")
    return text[:19].replace("T", " ") if len(text) >= 19 and text[10] in "T " else text


def seconds(value) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{value:.1f} s" if value < 120 else f"{value / 60:.1f} min"


def money(value) -> str:
    return f"${value:.4f}" if isinstance(value, (int, float)) else ""


def unwrap(value, depth: int = 0):
    """JSON inside JSON strings (tool arguments and results are often JSON text), decoded for reading."""
    if isinstance(value, str) and depth < 4 and value[:1] in "{[":
        try:
            return unwrap(json.loads(value), depth + 1)
        except ValueError:
            return value
    if isinstance(value, dict):
        return {k: unwrap(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(v, depth + 1) for v in value]
    return value


def pretty(value) -> str:
    """A JSON value (or a string that holds JSON) as an escaped, indented block."""
    value = unwrap(value)
    if isinstance(value, str):
        return f'<pre class="json">{e(value)}</pre>'
    return f'<pre class="json">{e(json.dumps(value, indent=2, ensure_ascii=False, default=str))}</pre>'


def tabs(project: str, active: str) -> str:
    items = [("runs", "Runs", href(project, "runs")), ("valkey", "Valkey", href(project, "valkey")),
             ("search", "Search", href(project, "search")), ("try", "Try it", href(project, "try"))]
    return '<nav class="tabs">' + "".join(
        f'<a href="{e(link)}" class="{"on" if key == active else ""}">{label}</a>' for key, label, link in items) \
        + "</nav>"


def shell(title: str, project: str, body: str, active: str = "") -> str:
    name = project[len("sandbox-"):] if project.startswith("sandbox-") else project
    head = (f'<nav class="crumbs"><a href="/">All sandboxes</a> / <a href="/#sb-{e(name)}">{e(name)}</a></nav>'
            if project else '<nav class="crumbs"><a href="/">All sandboxes</a></nav>')
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>{e(title)}</title><style>{STYLE}{EXTRA_STYLE}{EXCLUDE_STYLE}</style></head>"
            "<body><main class=\"wide\">"
            f"{head}<h1>{e(title)}</h1>{tabs(project, active) if project else ''}{body}</main></body></html>")


def select(name: str, label: str, options: list, current: str) -> str:
    opts = '<option value="">all</option>' + "".join(
        f'<option value="{e(o)}"{" selected" if str(o) == current else ""}>{e(o)}</option>' for o in options)
    return f'<label>{label}<select name="{name}">{opts}</select></label>'


def runs_page(project: str, data: dict) -> str:
    f = data.get("filters") or {}
    since = select("since", "time", ["1h", "24h", "7d", "30d"], f.get("since", ""))
    form = (f'<form class="bar" method="get" action="{e(href(project, "runs"))}">'
            f'{select("status", "status", data.get("statuses") or [], f.get("status", ""))}'
            f'{select("pipeline", "pipeline", data.get("pipelines") or [], f.get("pipeline", ""))}{since}'
            '<button type="submit">Filter</button></form>')
    rows = []
    for run in data.get("runs") or []:
        rid = str(run.get("run_id") or "")
        labels = " ".join(chip(f"{k}: {run[k]}", "muted") for k in ("developer", "env_class") if run.get(k))
        rows.append(
            f'<tr><td class="mono">{e(when(run.get("started_at")))}</td>'
            f'<td class="mono"><a href="{e(href(project, "runs", rid))}">{e(rid)}</a></td>'
            f'<td>{e(run.get("pipeline"))}</td><td class="mono">{e(cut(str(run.get("subject") or ""), 60))}</td>'
            f'<td>{status_chip(run.get("status"))}</td><td class="num">{e(seconds(run.get("duration_seconds")))}</td>'
            f'<td class="num">{e(money(run.get("cost_usd")))}</td><td>{labels}</td>'
            f'<td class="sum">{e(cut(str(run.get("error") or run.get("summary") or ""), 140))}</td></tr>')
    note = f'<p class="note">{e(data["note"])}</p>' if data.get("note") else ""
    if data.get("missing"):
        note += f'<p class="note">This run store has no column {e(", ".join(data["missing"]))} (older SDK).</p>'
    table = ('<div class="tw"><table class="data"><thead><tr><th>started (UTC)</th><th>run</th><th>pipeline</th>'
             '<th>subject</th><th>status</th><th>duration</th><th>cost</th><th>identity</th><th>summary / error</th>'
             '</tr></thead><tbody>' + ("".join(rows) or '<tr><td colspan="9" class="note">No run matches.</td></tr>')
             + "</tbody></table></div>")
    page, pages = data.get("page") or 1, data.get("pages") or 0
    nav = [f'<span>{e(data.get("total", 0))} runs, page {page} of {max(pages, 1)}</span>']
    if page > 1:
        nav.append(f'<a href="{e(href(project, "runs", page=page - 1, **f))}">newer</a>')
    if page < pages:
        nav.append(f'<a href="{e(href(project, "runs", page=page + 1, **f))}">older</a>')
    return shell(f"Runs of {project}", project, form + note + table + '<div class="pager">' + " ".join(nav)
                 + "</div>", "runs")


def timeline(stages: list) -> str:
    """One bar per stage on a common time axis (start and end from per_stage_stats)."""
    spans = []
    for stage in stages:
        try:
            start = datetime.datetime.strptime(str(stage.get("started_at"))[:19], "%Y-%m-%dT%H:%M:%S")
            end = datetime.datetime.strptime(str(stage.get("ended_at"))[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            start = end = None
        spans.append((stage, start, end))
    known = [(s, a, b) for s, a, b in spans if a and b]
    if not known:
        return ""
    t0 = min(a for _, a, _ in known)
    total = max((b - t0).total_seconds() for _, _, b in known) or 1.0
    out = []
    for stage, start, end in spans:
        bad = " bad" if TONES.get(str(stage.get("status") or "").lower()) == "bad" else ""
        if start and end:
            left = (start - t0).total_seconds() / total * 100
            width = max(0.5, (end - start).total_seconds() / total * 100)
            bar = f'<div class="track"><div class="bar{bad}" style="left:{left:.1f}%;width:{width:.1f}%"></div></div>'
        else:
            bar = '<div class="track"></div>'
        out.append(f'<span>{e(stage.get("stage_name"))} {status_chip(stage.get("status"))}</span>{bar}')
    return '<div class="tl">' + "".join(out) + "</div>"


def run_page(project: str, data: dict) -> str:
    run = data.get("run") or {}
    rid = str(run.get("run_id") or "")
    head = (f'<div class="panel"><p>{status_chip(run.get("status"))} <b>{e(run.get("pipeline"))}</b> · '
            f'<span class="mono">{e(run.get("subject"))}</span> · source {e(run.get("source"))}</p>'
            '<div class="kpis">'
            f'<span>started<b>{e(when(run.get("started_at")))}</b></span>'
            f'<span>duration<b>{e(seconds(run.get("duration_seconds")) or "–")}</b></span>'
            f'<span>cost<b>{e(money(data.get("cost_usd")) or "–")}</b></span>'
            + "".join(f'<span>{e(k.replace("_", " "))}<b>{e(v)}</b></span>'
                      for k, v in (data.get("tokens") or {}).items())
            + "".join(f'<span>{k}<b>{e(run.get(k))}</b></span>' for k in ("developer", "env_class", "env")
                      if run.get(k)) + "</div></div>")
    stages = data.get("stages") or []
    stage_rows = "".join(
        f'<tr><td>{e(s.get("stage_name"))}</td><td>{status_chip(s.get("status"))}</td>'
        f'<td class="mono">{e(when(s.get("started_at")))}</td><td class="mono">{e(when(s.get("ended_at")))}</td>'
        f'<td class="num">{e(seconds(s.get("duration_seconds")))}</td><td>{e(s.get("model"))}</td>'
        f'<td class="num">{e(s.get("input_tokens"))} / {e(s.get("output_tokens"))}</td>'
        f'<td class="num">{e(money(s.get("cost_usd")))}</td><td class="num">{e(s.get("tool_calls_total"))}</td></tr>'
        for s in stages)
    parts = [head]
    parts.append('<div class="panel"><h2>Stages</h2>' + timeline(stages)
                 + ('<div class="tw" style="margin-top:10px"><table class="data"><thead><tr><th>stage</th>'
                    '<th>status</th><th>start</th><th>end</th><th>duration</th><th>model</th><th>tokens in/out</th>'
                    '<th>cost</th><th>tools</th></tr></thead><tbody>' + stage_rows + "</tbody></table></div>"
                    if stages else '<p class="note">No stage statistics in this run.</p>') + "</div>")
    parts.append(tool_panel(data))
    for title, key in (("Summary", "summary"), ("Error", "error")):
        if run.get(key):
            parts.append(f'<div class="panel"><h2>{title}</h2><p>{e(run[key])}</p></div>')
    for title, key in (("Output", "output"), ("Halt handoff", "handoff"), ("Facts", "facts")):
        if run.get(key) not in (None, {}, [], ""):
            parts.append(f'<div class="panel"><h2>{title}</h2>{pretty(run[key])}</div>')
    if data.get("other_columns"):
        parts.append('<div class="panel"><h2>Other columns</h2>' + pretty(data["other_columns"]) + "</div>")
    parts.append(events_panel(project, data))
    parts.append(f'<details class="panel"><summary>The whole row (JSON)</summary>{pretty(run)}</details>')
    back = f'<p><a href="{e(href(project, "runs"))}">← all runs</a></p>'
    return shell(f"Run {rid}", project, back + "".join(parts), "runs")


def compact(value) -> str:
    """A tool's arguments in one line: the decoded JSON without its {"args": ...} wrapper."""
    value = unwrap(value)
    if isinstance(value, dict) and list(value) in (["args"], ["result"]):
        value = value[next(iter(value))]
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def tool_panel(data: dict) -> str:
    calls = data.get("tool_calls") or []
    if not calls:
        breakdown = {}
        for stage in data.get("stages") or []:
            for name, count in (stage.get("tool_call_breakdown") or {}).items():
                breakdown[name] = breakdown.get(name, 0) + (count if isinstance(count, int) else 0)
        text = ", ".join(f"{k} × {v}" for k, v in breakdown.items()) or "none"
        return (f'<div class="panel"><h2>Tool calls</h2><p class="note">No tool events in the newest stream '
                f'entries; counts from the stage statistics: {e(text)}</p></div>')
    rows = []
    for call in calls:
        state = chip("error", "bad") if call.get("is_error") else (chip("ok", "ok") if call.get("ended")
                                                                     else chip("open", "warn"))
        args = (f'<details><summary>{e(cut(compact(call.get("args")), 80))}</summary>{pretty(call["args"])}'
                '</details>') if call.get("args") else ""
        result = (f'<details><summary>{e(cut(str(call.get("summary") or call.get("result") or ""), 80))}</summary>'
                  f'{pretty(call["result"])}</details>') if call.get("result") else e(call.get("summary") or "")
        duration = f'{call["duration_ms"] / 1000:.2f} s' if isinstance(call.get("duration_ms"), int) else ""
        rows.append(f'<tr><td class="mono">{e(when(call.get("started")))}</td><td><b>{e(call.get("tool"))}</b></td>'
                    f'<td>{state}</td><td class="num">{e(duration)}</td><td>{args}</td><td>{result}</td></tr>')
    return ('<div class="panel"><h2>Tool calls</h2><div class="tw"><table class="data"><thead><tr><th>time</th>'
            '<th>tool</th><th>result</th><th>duration</th><th>arguments</th><th>result summary</th></tr></thead>'
            '<tbody>' + "".join(rows) + "</tbody></table></div></div>")


def events_panel(project: str, data: dict) -> str:
    if data.get("events_error"):
        return f'<div class="panel"><h2>Events</h2><p class="err">{e(data["events_error"])}</p></div>'
    events = data.get("events") or []
    if not events:
        return ('<div class="panel"><h2>Events</h2><p class="note">No event of this run in the newest entries of '
                'swarm:events.</p></div>')
    rows = []
    for entry in events:
        event = entry.get("event") or {}
        brief = " ".join(str(event[k]) for k in ("stage", "tool", "status", "summary") if event.get(k) not in
                         (None, ""))
        link = href(project, "valkey", "swarm:events", before=next_id(entry["id"]))
        kind = str(event.get("kind") or "")
        rows.append(f'<tr data-kind="{e(kind)}"><td class="mono"><a href="{e(link)}">{e(entry["id"])}</a></td>'
                    f'<td class="mono">{e(when(entry.get("ms")))}</td><td>{e(kind)}{run_x(kind)}</td>'
                    f'<td>{e(cut(brief, 120))}</td><td><details><summary>fields</summary>{pretty(event)}'
                    + (f'<b>content</b>{pretty(entry["content"])}' if entry.get("content") else "")
                    + "</details></td></tr>")
    return (f'<div class="panel"><h2>Events ({len(events)}, from swarm:events)</h2>{RUN_HIDDEN_LINE}<div class="tw">'
            '<table class="data" id="run-events"><thead><tr><th>entry id</th><th>time (UTC)</th><th>kind</th>'
            '<th>about</th>'
            '<th></th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div></div>" + RUN_SCRIPT)


def next_id(entry_id: str) -> str:
    """The stream id just after `entry_id`, so a page `before` it starts with that entry."""
    ms, _, seq = str(entry_id).partition("-")
    try:
        return f"{ms}-{int(seq or 0) + 1}"
    except ValueError:
        return entry_id
