"""The HTML of the sandbox hub (lib/cn_hub.py): the page, the cards and one inline SVG diagram per sandbox.

Pure functions of the collected data; the page has no external resource and escapes every value.
"""
from __future__ import annotations

from html import escape

REFRESH_MS = 5000
LOCAL_PEERS = ("observer", "devidp")
EMPTY = "No sandbox runs. In an agent repository: <code>cn-sandbox up --as-me</code>"


def e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def cut(text: str, size: int) -> str:
    text = text or ""
    return text if len(text) <= size else text[: size - 1] + "…"


# ---------------------------------------------------------------- diagram

def box(x, y, w, h, title, sub="", cls="box"):
    out = f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>'
    out += f'<text class="t1" x="{x + w / 2}" y="{y + (18 if sub else h / 2 + 4)}">{e(title)}</text>'
    if sub:
        out += f'<text class="t2" x="{x + w / 2}" y="{y + 34}">{e(sub)}</text>'
    return out


def arrow(x1, y1, x2, y2, label="", both=False, cls="ln", lx=None, ly=None):
    start = ' marker-start="url(#a0)"' if both else ""
    out = f'<line class="{cls}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" marker-end="url(#a1)"{start}/>'
    if label:
        lx = (x1 + x2) / 2 if lx is None else lx
        ly = (y1 + y2) / 2 - 6 if ly is None else ly
        out += f'<text class="lb" x="{lx}" y="{ly}">{e(label)}</text>'
    return out


def diagram(sb: dict) -> str:
    port = (sb.get("console") or {}).get("port") or "?"
    services = {s["name"] for s in sb.get("services") or []}
    wf_host = ((sb.get("workforce") or {}).get("url_host") or "").lower()
    local_observer = wf_host in LOCAL_PEERS or bool(services & set(LOCAL_PEERS))
    # The local observer and devidp are on the shared network (NO_PROXY), not behind egress.
    hosts = [h for h in sb.get("egress") or [] if not (local_observer and h.get("host") in LOCAL_PEERS)]
    hosts = hosts or [{"host": "none yet: run cn-sandbox up", "kind": "egress allowlist"}]
    width, top = 1000, 84
    height = max(340, top + 22 + len(hosts) * 50 + 20)
    developer = (sb.get("identity") or {}).get("mode") == "developer"
    parts = [
        '<defs>',
        '<marker id="a1" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>',
        '<marker id="a0" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M10,0 L0,5 L10,10 z" fill="currentColor"/></marker>',
        '</defs>',
        # the two compose networks
        f'<rect class="zone" x="140" y="{top}" width="420" height="{height - top - 12}" rx="10"/>',
        f'<text class="zl" x="152" y="{top + 18}">inner network: no internet</text>',
        f'<rect class="zone" x="580" y="{top}" width="410" height="{height - top - 12}" rx="10"/>',
        f'<text class="zl" x="592" y="{top + 18}">outer network: egress only</text>',
        box(8, 150, 106, 46, "your browser", f"localhost:{port}"),
        box(162, 150, 112, 46, "edge", f"127.0.0.1:{port}"),
        box(318, 150, 154, 46, "agent", cut(sb.get("name") or "", 24), "box accent"),
        box(520, 150, 120, 46, "egress", "allowlist proxy"),
        box(290, 252, 130, 46, "runstore", "Postgres: run history"),
        box(435, 252, 110, 46, "valkey", "run events"),
        arrow(114, 173, 162, 173, "HTTP", lx=127, ly=166),
        arrow(274, 173, 318, 173, "proxy"),
        arrow(472, 173, 520, 173, "HTTPS", lx=496, ly=166),
        arrow(375, 196, 355, 252, "runs", both=True, lx=345, ly=228),
        arrow(420, 196, 490, 252, "events", both=True, lx=475, ly=222),
    ]
    if developer:
        parts.append(box(300, 12, 190, 46, "token file (read-only)", "cn-sandbox token --watch", "box accent"))
        parts.append(arrow(395, 58, 395, 150, "mount :ro", lx=430, ly=112))
    else:
        parts.append(box(300, 12, 190, 46, "deployment token", "AI_GATEWAY_* in .env"))
        parts.append(arrow(395, 58, 395, 150, "env", lx=412, ly=112))
    if local_observer:
        parts.append(box(155, 252, 120, 46, "observer", "local, shared network"))
        parts.append(arrow(340, 196, 260, 252, "Workforce", lx=270, ly=220))
    for i, item in enumerate(hosts):
        y = top + 26 + i * 50
        parts.append(box(720, y, 262, 42, cut(item.get("kind") or "", 38), cut(item.get("host") or "", 44)))
        parts.append(arrow(640, 173, 720, y + 21, "allowed" if i == 0 else "", lx=672, ly=min(173, y + 21) - 6))
    label = (f"How the sandbox {sb.get('name')} is connected: browser to edge on 127.0.0.1:{port}, edge to agent, "
             f"agent to runstore and valkey on the inner network, agent to the internet only through egress to "
             f"{len(sb.get('egress') or [])} allowed hosts.")
    return (f'<svg class="dia" viewBox="0 0 {width} {height}" role="img" aria-label="{e(label)}" '
            f'xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>")


# ---------------------------------------------------------------- cards

def chip(text: str, tone: str) -> str:
    return f'<span class="chip {tone}">{e(text)}</span>'


def identity_chip(identity: dict) -> str:
    mode = (identity or {}).get("mode")
    if mode == "developer":
        return chip("as you (developer)", "ok")
    if mode == "legacy-refresh-token":
        return chip("deployment token", "warn")
    return chip((identity or {}).get("label") or "identity unknown", "muted")


def workforce_chip(workforce: dict) -> str:
    state = (workforce or {}).get("state") or "unknown"
    tone = {"approved": "ok", "pending": "warn", "rejected": "bad", "offboarded": "bad"}.get(state, "muted")
    return chip(f"Workforce: {state}", tone)


def status_chip(status: str) -> str:
    return chip(status, {"running": "ok", "partial": "warn"}.get(status, "muted"))


def token_text(sb: dict) -> str:
    refresh = sb.get("token_refresh") or {}
    mode = (sb.get("identity") or {}).get("mode")
    if mode == "legacy-refresh-token":
        return "not used (deployment token)"
    if mode != "developer":
        return "not used"
    text = f"running (pid {refresh['watch_pid']})" if refresh.get("watch_running") else "not running"
    if refresh.get("token_age_s") is not None:
        text += f", token written {refresh['token_age_s']} s ago"
    if refresh.get("registry") is not None:
        text += f", {refresh['registry']} sandbox(es) use it"
    return text


def card(sb: dict, open_diagram: bool) -> str:
    name, status = sb.get("name") or "?", sb.get("status") or "unknown"
    console = (sb.get("console") or {}).get("url")
    edge_up = any(s["name"] == "edge" and s["state"] == "running" for s in sb.get("services") or [])
    if console and edge_up:
        reach = (f'<p class="console"><a href="{e(console)}" target="_blank" rel="noopener noreferrer">'
                 f'Open the agent\'s console</a> <span class="url">{e(console)}</span></p>')
    else:
        reach = f'<p class="hint">Not running. In <code>{e(sb.get("repo") or "the agent repository")}</code>: ' \
                f'<code>cn-sandbox up</code></p>'
    services = " ".join(f'<span class="svc {"on" if s["state"] == "running" else "off"}" title="{e(s["state"])}">'
                        f'{e(s["name"])}</span>' for s in sb.get("services") or [])
    workforce = sb.get("workforce") or {}
    rows = [("services", services),
            ("Workforce", e(workforce.get("line") or "no onboarding line in the agent log")
             + (f' <span class="muted">(mode {e(workforce["mode"])})</span>'
                if workforce.get("mode") and "mode " not in (workforce.get("line") or "") else "")),
            ("token refresh", e(token_text(sb))),
            ("egress", e(", ".join(h["host"] for h in sb.get("egress") or []) or "no allowlist yet")),
            ("SDK", e(sb.get("sdk_version") or "not readable"))]
    facts = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return (f'<article class="card {e(status)}" id="sb-{e(name)}">'
            f'<header><h2>{e(name)}</h2>{status_chip(status)}{identity_chip(sb.get("identity"))}'
            f'{workforce_chip(workforce)}</header>'
            f'<p class="repo">{e(sb.get("repo") or "")}</p>{reach}<dl>{facts}</dl>'
            f'<details data-key="{e(name)}"{" open" if open_diagram else ""}>'
            f'<summary>How this sandbox is connected</summary>{diagram(sb)}</details></article>')


def cards(sandboxes: list) -> str:
    if not sandboxes:
        return f'<p class="empty">{EMPTY}</p>'
    return "".join(card(sb, len(sandboxes) == 1) for sb in sandboxes)


LEGEND = """<section class="legend" aria-label="Legend">
<h2>Legend</h2>
<ul>
<li><span class="chip ok">as you (developer)</span> the agent calls with your own token
(<code>cn-sandbox up --as-me</code>); <span class="chip warn">deployment token</span> it uses the agent's own
refresh token from <code>.env</code>.</li>
<li><span class="chip ok">Workforce: approved</span> the observer approved this instance; other states show as
the agent logged them.</li>
<li>Dashed areas are the sandbox's Docker networks: <b>inner</b> has no route out; <b>outer</b> is reached only
through <b>egress</b>, which lets through only the allowlisted hosts (<code>sandbox/egress-allow</code>,
<code>.env</code>, <code>SANDBOX_EGRESS_ALLOW</code>).</li>
<li>An arrow points the way a call goes; two heads: both ways. The accent marks the agent and your token.</li>
<li>The console link opens the agent's own page; log in on <code>localhost</code>, not on 127.0.0.1.</li>
</ul></section>"""

STYLE = """
:root{--bg:#f6f7f9;--surface:#fff;--text:#1c2330;--muted:#5d6878;--line:#d5dae2;--accent:#2f6fde;
--ok:#1d7a46;--okbg:#e3f4ea;--warn:#8a5a00;--warnbg:#fdf1d8;--bad:#a8302a;--badbg:#fbe5e3;--mutedbg:#eceff3}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--surface:#1b2029;--text:#e4e8ef;--muted:#9aa5b5;
--line:#2f3644;--accent:#79a7ff;--ok:#7fd3a0;--okbg:#173626;--warn:#f0c46c;--warnbg:#3a2e12;--bad:#f09a93;
--badbg:#3d1d1b;--mutedbg:#262c37}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,Helvetica,Arial,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 20px;font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:0 0 16px}
.card header{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.card h2{font-size:18px;margin:0 8px 0 0}
.card.stopped{opacity:.55;filter:grayscale(1)}
.chip{display:inline-block;border-radius:999px;padding:1px 10px;font-size:12px;font-weight:600;
background:var(--mutedbg);color:var(--muted)}
.chip.ok{background:var(--okbg);color:var(--ok)}.chip.warn{background:var(--warnbg);color:var(--warn)}
.chip.bad{background:var(--badbg);color:var(--bad)}
.repo{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);margin:6px 0;overflow-wrap:anywhere}
.console a{color:var(--accent);font-weight:600}.url{color:var(--muted);font-size:13px}
.hint{color:var(--muted)}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--mutedbg);padding:1px 5px;border-radius:4px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:8px 0;font-size:13px}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.svc{display:inline-block;margin:0 6px 2px 0}.svc:before{content:"";display:inline-block;width:8px;height:8px;
border-radius:50%;margin-right:4px;background:var(--muted)}.svc.on:before{background:var(--ok)}
.muted{color:var(--muted)}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent);font-weight:600}
.dia{display:block;width:100%;height:auto;margin-top:10px;color:var(--text)}
.dia .box{fill:var(--surface);stroke:currentColor;stroke-width:1.2}
.dia .accent{stroke:var(--accent);stroke-width:2}
.dia .zone{fill:none;stroke:var(--muted);stroke-dasharray:6 5}
.dia .ln{stroke:currentColor;stroke-width:1.3}
.dia text{fill:currentColor;text-anchor:middle}.dia .t1{font-size:13px;font-weight:600}
.dia .t2{font-size:10.5px;fill:var(--muted)}.dia .lb{font-size:10.5px;fill:var(--muted)}
.dia .zl{text-anchor:start;font-size:11px;fill:var(--muted);font-style:italic}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:10px;padding:28px;text-align:center}
.legend{font-size:13px;color:var(--muted);margin-top:24px}.legend h2{font-size:14px;color:var(--text)}
.legend li{margin-bottom:6px}
@media (max-width:640px){dl{grid-template-columns:1fr}dt{margin-top:6px}}
"""

SCRIPT = """
(function(){
  var box=document.getElementById('cards'), stamp=document.getElementById('stamp');
  function openKeys(){var k={};box.querySelectorAll('details[data-key]').forEach(function(d){k[d.dataset.key]=d.open;});return k;}
  function tick(){
    fetch('/cards',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error(r.status);return r.text();})
    .then(function(html){var k=openKeys();box.innerHTML=html;
      box.querySelectorAll('details[data-key]').forEach(function(d){if(d.dataset.key in k)d.open=k[d.dataset.key];});
      stamp.textContent='updated '+new Date().toLocaleTimeString();})
    .catch(function(){stamp.textContent='hub not answering: run cn-sandbox hub';});
  }
  setInterval(tick, %d);
})();
""" % REFRESH_MS


def page(sandboxes: list) -> str:
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"color-scheme\" content=\"light dark\">"
            f"<title>Agent sandboxes</title><style>{STYLE}</style></head><body><main>"
            "<h1>CodeNOW agent sandboxes</h1>"
            "<p class=\"sub\">Every local agent sandbox on this computer, from Docker. Refreshes every 5 s; "
            "<span id=\"stamp\">live</span>. Stop this page: <code>cn-sandbox hub --stop</code></p>"
            f"<div id=\"cards\">{cards(sandboxes)}</div>{LEGEND}</main>"
            f"<script>{SCRIPT}</script></body></html>")
