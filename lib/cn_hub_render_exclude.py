"""Hide event kinds in the hub: the (✕) per kind cell and the "Hidden:" line, on a stream page and a run's events.

A stream page filters on the server (`exclude=a,b`, cn_hub_valkey.stream_view) and remembers the list per sandbox
and key in localStorage; a run page filters its own event rows in the browser, with the list in its URL too.
Scripts build their text with textContent only; every server value is escaped.
"""
from __future__ import annotations

from cn_hub_render import e

KIND_RE = r"^[a-z0-9_.:-]{1,64}$"   # the same rule as cn_hub_valkey.EXCLUDE_KIND
EXCLUDE_MAX = 20

EXCLUDE_STYLE = """
.xbtn{margin-left:6px;padding:0 5px;border:1px solid var(--line);border-radius:4px;background:var(--surface);
color:var(--muted);font-size:11px;line-height:16px;cursor:pointer;text-decoration:none;opacity:0}
tr:hover .xbtn,.xbtn:focus,.xbtn:focus-visible{opacity:1}.xbtn:hover{color:var(--bad);border-color:var(--bad)}
@media (hover:none){.xbtn{opacity:1}}
.hidden-kinds{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:13px;margin:0 0 10px;color:var(--muted)}
.chipx{display:inline-flex;gap:4px;align-items:center;padding:1px 9px;border:1px solid var(--line);border-radius:999px;
background:var(--mutedbg);color:var(--text);text-decoration:none;font:inherit;cursor:pointer}
.chipx:hover,.chipx:focus-visible{border-color:var(--accent)}.chipx .n{color:var(--muted);font-size:12px}
.linkish{color:var(--accent);background:none;border:none;cursor:pointer;font:inherit;padding:0;
text-decoration:underline}
"""


def joined(kinds) -> str:
    return ",".join(kinds)


def stream_x(kind: str, link: str, kinds_after: list) -> str:
    """The (✕) after a kind in a stream row: a link to the same page with that kind excluded."""
    if not kind:
        return ""
    return (f'<a class="xbtn" href="{e(link)}" data-exclude="{e(joined(kinds_after))}" role="button" '
            f'aria-label="Hide all {e(kind)} entries" title="Hide all {e(kind)} entries">✕</a>')


def stream_hidden_line(data: dict, link_of) -> str:
    """The line `Hidden: [kind N ✕] … · Show all` above a stream table; `link_of(kinds)` is the page URL with
    that exclude list."""
    exclude, skipped = data.get("exclude") or [], data.get("skipped") or {}
    restored = ('<span id="xk-restored" hidden>(restored from your last visit to this key)</span>')
    if not exclude:
        return f'<div class="hidden-kinds" id="xk" data-exclude="">{restored}</div>'
    chips = []
    for kind in exclude:
        rest = [k for k in exclude if k != kind]
        chips.append(f'<a class="chipx" href="{e(link_of(rest))}" data-exclude="{e(joined(rest))}" '
                     f'aria-label="Show {e(kind)} entries again">{e(kind)} <span class="n">{skipped.get(kind, 0)}'
                     '</span> ✕</a>')
    total = sum(skipped.values())
    scanned, cap = data.get("scanned") or 0, data.get("scan_cap") or 0
    note = f"{total} hidden while filling this page (looked at {scanned} entries"
    note += f", the cap of {cap}; older continues)" if cap and scanned >= cap else ")"
    return (f'<div class="hidden-kinds" id="xk" data-exclude="{e(joined(exclude))}">Hidden: {"".join(chips)} · '
            f'<a class="linkish" href="{e(link_of([]))}" data-exclude="">Show all</a>'
            f'<span class="note">{e(note)}</span>{restored}</div>')


def stream_script(store_key: str) -> str:
    """Remember the list per sandbox and key; with no `exclude=` in the URL, apply the remembered one and say so."""
    return ('<script>(function(){var box=document.getElementById("xk");if(!box)return;'
            f'var name={js_string(store_key)},re=/{KIND_RE}/;'
            'function save(v){try{localStorage.setItem(name,v)}catch(_){}}'
            'function load(){try{return localStorage.getItem(name)||""}catch(_){return ""}}'
            'var u=new URL(location.href);'
            'if(u.searchParams.has("exclude")){save(box.getAttribute("data-exclude")||"")}'
            'else{var kept=load().split(",").filter(function(k,i,a){return re.test(k)&&a.indexOf(k)===i})'
            f'.slice(0,{EXCLUDE_MAX});'
            'if(kept.length){u.searchParams.set("exclude",kept.join(","));u.searchParams.set("restored","1");'
            'location.replace(u.toString());return}}'
            'if(u.searchParams.get("restored")){var n=document.getElementById("xk-restored");if(n)n.hidden=false}'
            'document.addEventListener("click",function(ev){var a=ev.target.closest&&'
            'ev.target.closest("a[data-exclude]");if(a)save(a.getAttribute("data-exclude")||"")})})();</script>')


def run_x(kind: str) -> str:
    """The (✕) after a kind in a run's event row (the script below hides the rows)."""
    if not kind:
        return ""
    return (f'<button type="button" class="xbtn" data-hide="{e(kind)}" aria-label="Hide all {e(kind)} entries" '
            f'title="Hide all {e(kind)} entries">✕</button>')


RUN_HIDDEN_LINE = '<div class="hidden-kinds" id="xk-run" hidden></div>'

RUN_SCRIPT = ('<script>(function(){var t=document.getElementById("run-events"),line=document.getElementById("xk-run");'
              f'if(!t||!line)return;var re=/{KIND_RE}/;'
              'function read(){return (new URLSearchParams(location.search).get("exclude")||"").split(",")'
              f'.filter(function(k,i,a){{return re.test(k)&&a.indexOf(k)===i}}).slice(0,{EXCLUDE_MAX})}}'
              'var ex=read();'
              'function btn(cls,text,label,fn){var b=document.createElement("button");b.type="button";'
              'b.className=cls;b.textContent=text;if(label)b.setAttribute("aria-label",label);'
              'b.addEventListener("click",fn);return b}'
              'function go(next){ex=next;var u=new URL(location.href);if(ex.length)u.searchParams.set("exclude",'
              'ex.join(","));else u.searchParams.delete("exclude");history.pushState(null,"",u.toString());apply()}'
              'function apply(){var counts={},total=0;t.querySelectorAll("tr[data-kind]").forEach(function(r){'
              'var k=r.getAttribute("data-kind"),h=ex.indexOf(k)>=0;r.hidden=h;if(h){counts[k]=(counts[k]||0)+1;'
              'total++}});line.textContent="";line.hidden=!ex.length;if(!ex.length)return;'
              'line.appendChild(document.createTextNode("Hidden: "));ex.forEach(function(k){'
              'line.appendChild(btn("chipx",k+" "+(counts[k]||0)+" \\u2715","Show "+k+" entries again",'
              'function(){go(ex.filter(function(x){return x!==k}))}))});'
              'line.appendChild(document.createTextNode(" \\u00b7 "));'
              'line.appendChild(btn("linkish","Show all","",function(){go([])}));'
              'var n=document.createElement("span");n.className="note";n.textContent=total+" of "+'
              't.querySelectorAll("tr[data-kind]").length+" events of this run hidden";line.appendChild(n)}'
              't.addEventListener("click",function(ev){var b=ev.target.closest&&ev.target.closest("[data-hide]");'
              f'if(!b)return;var k=b.getAttribute("data-hide");if(re.test(k)&&ex.indexOf(k)<0&&ex.length<{EXCLUDE_MAX})'
              'go(ex.concat([k]))});'
              'window.addEventListener("popstate",function(){ex=read();apply()});apply()})();</script>')


def js_string(text: str) -> str:
    """A JS string literal that is safe inside <script> (no </, no quotes broken)."""
    out = []
    for ch in str(text):
        out.append(ch if ch.isalnum() or ch in " _-.:" else f"\\u{ord(ch):04x}" if ord(ch) < 0x10000 else ch)
    return '"' + "".join(out) + '"'
