"""The search of the sandbox hub: one text, matched in the run store, in the event streams and in the key names.

Runs: id prefix, subject, pipeline, status, summary, error, output (ILIKE, capped). Events: the newest SCAN_ENTRIES
entries of swarm:events and swarm:debug, matched in their field text. Keys: SCAN MATCH *text*. Each part has its
own error, so one service that does not answer leaves the others' results.
"""
from __future__ import annotations

import re

import cn_hub_runs as runs
import cn_hub_valkey as valkey
from cn_hub_exec import ExecError, mask_deep

EVENT_CAP = 100
KEY_CAP = 100
Q_MAX = 100


def clean_query(q: str) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", q or "").strip()[:Q_MAX]


def summary_of(entry: dict) -> str:
    event = entry.get("event")
    if isinstance(event, dict):
        parts = [str(event.get(k)) for k in ("kind", "run_id", "pipeline", "tool", "stage", "status", "summary",
                                             "text", "message") if event.get(k) not in (None, "")]
        return " · ".join(parts)[:300]
    return " ".join(f"{k}={v}" for k, v in entry["fields"].items())[:300]


def search(sb, q: str) -> dict:
    q = clean_query(q)
    out = {"q": q, "runs": [], "events": [], "keys": [], "errors": {}}
    if not q:
        return out
    try:
        out["runs"] = runs.search_runs(sb, q)
    except ExecError as exc:
        out["errors"]["runs"] = str(exc)
    needle = q.lower()
    for stream in valkey.EVENT_STREAMS:
        try:
            entries = valkey.newest(sb, stream, valkey.SCAN_ENTRIES)
        except ExecError as exc:
            out["errors"][stream] = str(exc)
            continue
        for entry in entries:
            text = " ".join(f"{k} {v}" for k, v in entry["fields"].items()).lower()
            if needle in text or needle in entry["id"]:
                event = entry.get("event") or {}
                out["events"].append({"stream": stream, "id": entry["id"], "ms": entry["ms"],
                                      "kind": event.get("kind"), "run_id": event.get("run_id"),
                                      "text": summary_of(entry)})
                if len(out["events"]) >= EVENT_CAP:
                    break
        if len(out["events"]) >= EVENT_CAP:
            break
    try:
        names, _ = valkey.scan_keys(sb, "*" + valkey.glob_escape(q) + "*", cap=KEY_CAP, deadline_s=3.0)
        out["keys"] = names
    except ExecError as exc:
        out["errors"]["keys"] = str(exc)
    return mask_deep(out)
