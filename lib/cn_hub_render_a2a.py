"""The HTML of the hub's A2A "Try it" page (/s/<project>/try): the agent card, a form and the outcome of one send.

Pure functions; every server value is escaped here, and the script writes the answer only with textContent. The page
carries the hub's per-process CSRF token (a <meta>), never a caller token.
"""
from __future__ import annotations

import json

from cn_hub_render import chip, e
from cn_hub_render_runs import href, shell

TRY_STYLE = """
.warnbox{background:var(--warnbg);color:var(--warn);padding:10px 14px;border-radius:8px;margin:0 0 14px;font-weight:600}
form.try{display:grid;gap:10px;max-width:900px}
form.try label{display:flex;flex-direction:column;gap:3px;font-size:13px;color:var(--muted)}
form.try textarea,form.try input,form.try select{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;padding:6px 8px;
border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--text)}
form.try button{justify-self:start;font:inherit;padding:6px 16px;border-radius:6px;border:1px solid var(--accent);
background:var(--accent);color:#fff;cursor:pointer;font-weight:600}
form.try button:disabled{opacity:.5;cursor:wait}
.ex{font:12px ui-monospace,Menlo,monospace;color:var(--accent);background:none;border:none;padding:0;cursor:pointer;
text-align:left;text-decoration:underline}
pre.answer{font:13px/1.5 ui-sans-serif,system-ui,sans-serif;white-space:pre-wrap;background:var(--mutedbg);
padding:10px 12px;border-radius:8px;margin:6px 0}
#out .kpis{margin:0 0 8px}
"""

SCRIPT = """
(function(){
var f=document.getElementById('try'),out=document.getElementById('out'),btn=f.querySelector('button');
var csrf=document.querySelector('meta[name=cn-hub-token]').content,api=f.getAttribute('data-api');
function el(tag,cls,text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}
function kv(box,k,v,link){if(v==null||v==='')return;var d=el('div');d.appendChild(el('span','note',k+' '));
 var b=el(link?'a':'b');b.textContent=String(v);if(link)b.href=link;d.appendChild(b);box.appendChild(d);}
function pre(v){return el('pre','json',typeof v==='string'?v:JSON.stringify(v,null,2));}
document.querySelectorAll('button.ex').forEach(function(b){b.addEventListener('click',function(){
 f.skill.value=b.getAttribute('data-skill');f.text.value=b.textContent;});});
f.addEventListener('submit',function(ev){
 ev.preventDefault();var data=f.data.value.trim();
 if(data){try{var o=JSON.parse(data);if(!o||typeof o!=='object'||Array.isArray(o))throw 0;}
  catch(x){out.textContent='';out.appendChild(el('p','err','data must be a JSON object'));return;}}
 btn.disabled=true;var t0=Date.now();out.textContent='';var wait=el('p','note','Sending… 0 s');out.appendChild(wait);
 var tick=setInterval(function(){wait.textContent='Waiting for the agent… '+Math.round((Date.now()-t0)/1000)+' s';},1000);
 fetch(api,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CN-Hub-Token':csrf},
  body:JSON.stringify({skill:f.skill.value,text:f.text.value,subject:f.subject.value,data:data})})
 .then(function(r){return r.json().then(function(j){return [r.status,j];},function(){return [r.status,{error:'HTTP '+r.status}];});})
 .then(function(res){show(res[0],res[1]);},function(err){out.textContent='';out.appendChild(el('p','err','The hub did not answer: '+err));})
 .then(function(){clearInterval(tick);btn.disabled=false;});
});
function show(code,j){
 out.textContent='';var p=el('section','panel');out.appendChild(p);p.appendChild(el('h2',null,'Answer'));
 if(!j.ok){p.appendChild(el('p','err',j.error||('HTTP '+code)));if(j.detail)p.appendChild(pre(j.detail));
  if(j.rpc_error)p.appendChild(pre(j.rpc_error));if(j.guidance)p.appendChild(el('p','note',j.guidance));}
 var k=el('div','kpis');p.appendChild(k);kv(k,'state',j.state);kv(k,'duration',j.duration_s!=null?j.duration_s+' s':null);
 kv(k,'task',j.task_id);if(j.run_id)kv(k,'run',j.run_id,f.getAttribute('data-runs')+'/'+encodeURIComponent(j.run_id));
 kv(k,'token',j.token_from);kv(k,'endpoint',j.endpoint);
 if(j.note)p.appendChild(el('p','note',j.note));if(j.error&&j.ok)p.appendChild(el('p','err',String(j.error)));
 if(j.text){p.appendChild(el('h3',null,'Text'));p.appendChild(el('pre','answer',j.text));}
 (j.data||[]).forEach(function(d){p.appendChild(el('h3',null,'Data'));p.appendChild(pre(d));});
 if(j.raw&&j.raw.length){var det=el('details');det.appendChild(el('summary',null,'Raw JSON-RPC (masked)'));
  det.appendChild(pre(j.raw));p.appendChild(det);}
}
})();
"""


def skills_table(card: dict) -> str:
    rows = []
    for s in card.get("skills") or []:
        examples = "".join(f'<div><button type="button" class="ex" data-skill="{e(s["id"])}">{e(x)}</button></div>'
                           for x in s.get("examples") or [])
        tags = " ".join(chip(t, "muted") for t in s.get("tags") or [])
        rows.append(f'<tr><td class="mono">{e(s["id"])}</td><td>{e(s.get("description"))}'
                    f'{" " + tags if tags else ""}{examples}</td>'
                    f'<td class="mono">{e(", ".join(s.get("input_modes") or []))}</td></tr>')
    if not rows:
        return '<p class="note">The card lists no skill; the agent may still take a message without a skill id.</p>'
    return ('<div class="tw"><table class="data"><tr><th>skill id</th><th>description, examples</th>'
            f'<th>input modes</th></tr>{"".join(rows)}</table></div>')


def card_panel(card: dict, endpoint: str) -> str:
    facts = [("name", card.get("name")), ("description", card.get("description")),
             ("card url", card.get("url")), ("local endpoint", endpoint), ("version", card.get("version")),
             ("protocol", card.get("protocol")), ("input", ", ".join(card.get("input_modes") or [])),
             ("output", ", ".join(card.get("output_modes") or [])),
             ("streaming", "yes" if card.get("streaming") else "no")]
    dl = "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in facts if v not in (None, ""))
    return f'<section class="panel"><h2>Agent card</h2><dl>{dl}</dl>{skills_table(card)}</section>'


def form(project: str, card: dict) -> str:
    skills = card.get("skills") or []
    first = next((s["id"] for s in skills if not s.get("special")), skills[0]["id"] if skills else "")
    options = "".join(f'<option value="{e(s["id"])}"{" selected" if s["id"] == first else ""}>{e(s["id"])}'
                      f'{" (" + e(", ".join(s["tags"])) + ")" if s.get("special") else ""}</option>' for s in skills)
    options += '<option value="">(no skill id: the agent\'s default)</option>'
    sdk = card.get("flavor") == "sdk"
    data_hint = ("facts of the pipeline as a JSON object, e.g. {\"goods_description\": \"fresh trout\"}" if sdk
                 else "optional JSON object, sent as a data part")
    return (f'<form id="try" class="try" data-api="{e("/api" + href(project, "a2a", "send"))}" '
            f'data-runs="{e(href(project, "runs"))}">'
            f'<label>skill<select name="skill">{options}</select></label>'
            '<label>message (a text part)<textarea name="text" rows="4" maxlength="32768"></textarea></label>'
            '<label>subject (optional; the run\'s subject in the SDK)<input name="subject" maxlength="500"></label>'
            f'<label>data (optional): {e(data_hint)}<textarea name="data" rows="4" maxlength="32768"></textarea>'
            '</label><button type="submit">Send</button></form>')


def token_panel(how: dict, mode: str) -> str:
    return ('<section class="panel"><h2>Caller</h2><dl>'
            f'<dt>token</dt><dd>{e(how.get("label"))} <span class="muted">(made at each send; never shown)</span>'
            f'</dd><dt>audience mode</dt><dd>{e(mode)} <span class="muted">(shadow accepts any token of the '
            'trusted issuer)</span></dd></dl></section>')


def try_page(project: str, csrf: str, card: dict | None, endpoint: str, how: dict, mode: str,
             error: str = "") -> str:
    warning = ('<p class="warnbox">Sends a real request: the agent runs and model calls are billed. One request '
               'per sandbox at a time, at most 120 s.</p>')
    if card is None:
        body = (warning + f'<p class="err">{e(error or "The agent card is not readable.")}</p>'
                '<p class="note">Is the sandbox running? In the agent repository: <code>cn-sandbox up</code></p>')
    else:
        body = (warning + card_panel(card, endpoint) + token_panel(how, mode)
                + f'<section class="panel"><h2>Send</h2>{form(project, card)}</section><div id="out"></div>'
                + f"<script>{SCRIPT}</script>")
    page = shell("Try it: A2A", project, body, "try")
    meta = f'<meta name="cn-hub-token" content="{e(csrf)}"><style>{TRY_STYLE}</style>'
    return page.replace("</head>", meta + "</head>", 1)


def card_json(card: dict, endpoint: str) -> str:
    return json.dumps({"card": card, "endpoint": endpoint}, indent=1, ensure_ascii=False)
