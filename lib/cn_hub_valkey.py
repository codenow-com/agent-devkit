"""The Valkey browser of the sandbox hub: keys by pattern, one key by type, and a sandbox's stream entries.

Every read goes through cn_hub_exec.Sandbox.valkey (read commands only); every value leaves masked (mask_deep).
"""
from __future__ import annotations

import json
import re
import time

from cn_hub_exec import ExecError, mask_deep

KEY_CAP = 1000          # keys listed per pattern
SCAN_COUNT = 500
PAGE = 50               # stream entries, list items, zset members per view
FIELD_CAP = 200         # hash fields, set members
STRING_CAP = 4096       # bytes of a string shown
SCAN_ENTRIES = 5000     # stream entries a search or a run detail looks at
CHUNK = 1000
EVENT_STREAMS = ("swarm:events", "swarm:debug")
CONTENT_CAP = 16000     # characters of one content body in a run detail
RUN_EVENTS_CAP = 1000
STREAM_ID = re.compile(r"^\d{1,20}(-\d{1,20})?$")
EXCLUDE_KIND = re.compile(r"^[a-z0-9_.:-]{1,64}$")
EXCLUDE_MAX = 20        # kinds in one exclude list
SIZE_OF = {"stream": "XLEN", "list": "LLEN", "hash": "HLEN", "set": "SCARD", "zset": "ZCARD", "string": "STRLEN"}


def clean_pattern(pattern: str) -> str:
    pattern = re.sub(r"[\x00-\x1f\x7f]", "", pattern or "*")[:200]
    return pattern or "*"


def glob_escape(text: str) -> str:
    return re.sub(r"([*?\[\]\\])", r"\\\1", text)


def scan_keys(sb, pattern: str = "*", cap: int = KEY_CAP, deadline_s: float = 5.0) -> tuple:
    """Key names matching `pattern` by SCAN, at most `cap`; (names, complete)."""
    pattern, cursor, names, until = clean_pattern(pattern), "0", [], time.monotonic() + deadline_s
    while True:
        reply = sb.valkey(["SCAN", cursor, "MATCH", pattern, "COUNT", str(SCAN_COUNT)])[0]
        if not isinstance(reply, list) or len(reply) != 2:
            raise ExecError("valkey: SCAN gave no answer")
        cursor = str(reply[0])
        for name in reply[1] or []:
            if name not in names:
                names.append(name)
        if cursor == "0":
            return sorted(names[:cap]), len(names) <= cap
        if len(names) >= cap or time.monotonic() > until:
            return sorted(names[:cap]), False


def keys(sb, pattern: str = "*") -> dict:
    """The keys of a pattern with type, TTL and size (one valkey-cli for all of them)."""
    names, complete = scan_keys(sb, pattern)
    rows = []
    if names:
        replies = sb.valkey(*[c for n in names for c in (["TYPE", n], ["TTL", n])])
        types = [replies[i * 2] for i in range(len(names))]
        ttls = [replies[i * 2 + 1] for i in range(len(names))]
        sizes = sb.valkey(*[[SIZE_OF.get(t, "TYPE"), n] for n, t in zip(names, types)])
        for name, kind, ttl, size in zip(names, types, ttls, sizes):
            rows.append({"key": name, "type": kind or "?", "ttl": ttl,
                         "size": size if isinstance(size, int) and kind in SIZE_OF else None})
    return mask_deep({"pattern": clean_pattern(pattern), "keys": rows, "complete": complete, "cap": KEY_CAP})


def parse_entries(reply) -> list:
    """XRANGE/XREVRANGE reply → [{id, ms, fields, event}]; `event` is the JSON of the field e or data, when there."""
    out = []
    for item in reply if isinstance(reply, list) else []:
        if not (isinstance(item, list) and len(item) == 2):
            continue
        entry_id, flat = str(item[0]), item[1] or []
        fields = {str(flat[i]): flat[i + 1] for i in range(0, len(flat) - 1, 2)}
        event = None
        for name in ("e", "data"):
            if isinstance(fields.get(name), str):
                try:
                    parsed = json.loads(fields[name])
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    event = parsed
                    break
        out.append({"id": entry_id, "ms": int(entry_id.split("-")[0] or 0), "fields": fields, "event": event})
    return out


def newest(sb, stream: str, total: int = SCAN_ENTRIES, deadline_s: float = 6.0) -> list:
    """The newest `total` entries of a stream, newest first, in chunks of CHUNK (bounded by a deadline)."""
    out, end, until = [], "+", time.monotonic() + deadline_s
    while len(out) < total and time.monotonic() < until:
        chunk = parse_entries(sb.valkey(["XREVRANGE", stream, end, "-", "COUNT", str(min(CHUNK, total - len(out)))])[0])
        out.extend(chunk)
        if len(chunk) < CHUNK:
            break
        end = "(" + chunk[-1]["id"]
    return out


def kind_of(entry: dict) -> str:
    event = entry.get("event") or {}
    return str(event.get("kind") or "")


def parse_exclude(raw) -> list:
    """`exclude=a,b` (text or list) → the valid kinds ([a-z0-9_.:-]), at most EXCLUDE_MAX, in order, no repeats."""
    parts = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    out = []
    for part in parts:
        part = str(part).strip()
        if EXCLUDE_KIND.match(part) and part not in out:
            out.append(part)
    return out[:EXCLUDE_MAX]


def stream_view(sb, key: str, before: str = "", kind: str = "", scan: int = 2000, exclude=()) -> dict:
    """One page (PAGE entries) of a stream, newest first, before the id `before`; `kind` keeps one event kind,
    then `exclude` drops kinds. Reads in batches until the page is full or `scan` entries were looked at; `skipped`
    counts the excluded entries per kind and `next` continues after the last entry looked at."""
    end = "(" + before if before and STREAM_ID.match(before) else "+"
    exclude = parse_exclude(exclude)
    rows, looked, cursor, exhausted, skipped = [], 0, None, False, {}
    while len(rows) < PAGE and looked < scan and not exhausted:
        count = PAGE - len(rows) if not (kind or exclude) else min(500, scan - looked)
        chunk = parse_entries(sb.valkey(["XREVRANGE", key, end, "-", "COUNT", str(count)])[0])
        looked += len(chunk)
        seen = 0
        for entry in chunk:
            cursor, seen = entry["id"], seen + 1
            this = kind_of(entry)
            if kind and this != kind:
                continue
            if this in exclude:
                skipped[this] = skipped.get(this, 0) + 1
                continue
            rows.append(entry)
            if len(rows) == PAGE:
                break
        exhausted = len(chunk) < count and seen == len(chunk)
        end = "(" + str(cursor)
    length = sb.valkey(["XLEN", key])[0]
    return {"entries": rows, "next": None if exhausted or cursor is None else cursor, "length": length,
            "kind": kind, "exclude": exclude, "skipped": skipped, "scanned": looked, "scan_cap": scan}


def key_view(sb, key: str, before: str = "", kind: str = "", exclude=()) -> dict:
    """One key by its type: stream page, hash fields, list items, set members, zset members, or a string's start."""
    key = key[:1000]
    kind_reply, ttl = sb.valkey(["TYPE", key], ["TTL", key])
    out = {"key": key, "type": kind_reply or "none", "ttl": ttl}
    if kind_reply == "stream":
        out.update(stream_view(sb, key, before, kind, exclude=exclude))
    elif kind_reply == "hash":
        size = sb.valkey(["HLEN", key])[0] or 0
        if size <= FIELD_CAP:
            flat = sb.valkey(["HGETALL", key])[0] or []
        else:
            flat = (sb.valkey(["HSCAN", key, "0", "COUNT", str(FIELD_CAP)])[0] or ["0", []])[1]
        # a field named like a secret (password, token, ...) has its whole value masked, as a JSON key would
        out.update(size=size, fields=[[flat[i], mask_deep(flat[i + 1], str(flat[i]))]
                                      for i in range(0, len(flat) - 1, 2)][:FIELD_CAP])
    elif kind_reply == "list":
        size, items = sb.valkey(["LLEN", key], ["LRANGE", key, "0", str(PAGE - 1)])
        out.update(size=size, items=items or [])
    elif kind_reply == "set":
        size, scanned = sb.valkey(["SCARD", key], ["SSCAN", key, "0", "COUNT", str(FIELD_CAP)])
        out.update(size=size, items=((scanned or ["0", []])[1] or [])[:FIELD_CAP])
    elif kind_reply == "zset":
        size, flat = sb.valkey(["ZCARD", key], ["ZRANGE", key, "0", str(PAGE - 1), "WITHSCORES"])
        flat = flat or []
        out.update(size=size, items=[[flat[i], flat[i + 1]] for i in range(0, len(flat) - 1, 2)])
    elif kind_reply == "string":
        size, text = sb.valkey(["STRLEN", key], ["GETRANGE", key, "0", str(STRING_CAP - 1)])
        out.update(size=size, value=text or "", truncated=bool(size and size > STRING_CAP))
    return mask_deep(out)


def run_events(sb, run_id: str) -> dict:
    """The events of one run from the newest SCAN_ENTRIES entries of swarm:events, with the content bodies
    (swarm:content) of their time range; tool calls paired by call_id."""
    events = [e for e in newest(sb, "swarm:events") if (e.get("event") or {}).get("run_id") == run_id]
    events = events[:RUN_EVENTS_CAP]
    events.reverse()
    bodies = {}
    if events:
        start, end = events[0]["ms"] - 2000, events[-1]["ms"] + 2000
        for entry in parse_entries(sb.valkey(["XRANGE", "swarm:content", str(max(0, start)), str(end),
                                              "COUNT", str(CHUNK)])[0]):
            ident = entry["fields"].get("id")
            body = entry["fields"].get("b")
            if ident and isinstance(body, str):
                bodies[str(ident)] = body if len(body) <= CONTENT_CAP else body[:CONTENT_CAP] + " …(cut)"
    tools, order = {}, []
    for entry in events:
        event = entry["event"]
        body = bodies.get(str(event.get("event_id") or ""))
        entry["content"] = body
        call = event.get("call_id")
        if event.get("kind") in ("tool_started", "tool_ended") and call:
            if call not in tools:
                tools[call] = {"call_id": call, "tool": event.get("tool"), "stage": event.get("stage")}
                order.append(call)
            row = tools[call]
            if event["kind"] == "tool_started":
                row.update(started=event.get("ts"), started_ms=entry["ms"], args=body)
            else:
                row.update(ended=event.get("ts"), is_error=event.get("is_error"), summary=event.get("summary"),
                           result=body, duration_ms=(entry["ms"] - row["started_ms"]) if row.get("started_ms")
                           else None)
    return mask_deep({"events": events, "tool_calls": [tools[c] for c in order], "scanned": SCAN_ENTRIES})
