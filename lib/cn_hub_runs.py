"""The run-store browser of the sandbox hub: the runs of a sandbox (filters, pages of 50) and one run in detail.

The table is the SDK's `agent_runs` (codenow_agent_sdk/agent/run_store/postgres.py). Its columns grew over the SDK
versions, so the hub first reads which exist (information_schema) and selects only those; a run's detail is the whole
row as JSON, so a column the hub does not know is still shown raw. Only agent_runs is read (never harness_secrets).
Every outside value reaches SQL as a psql variable; the filters are checked against strict patterns first.
"""
from __future__ import annotations

import re
import time

import cn_hub_valkey as valkey
from cn_hub_exec import ExecError, mask_deep

PAGE = 50
TEXT_CUT = 240
SINCE = {"1h": "1 hour", "24h": "24 hours", "7d": "7 days", "30d": "30 days"}
TOKEN = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
COST = ("(SELECT sum((s->>'cost_usd')::float) FROM jsonb_array_elements(CASE WHEN jsonb_typeof(per_stage_stats) = "
        "'array' THEN per_stage_stats ELSE '[]'::jsonb END) s WHERE jsonb_typeof(s->'cost_usd') = 'number')")
TOKENS = ("(SELECT sum(coalesce((s->>'input_tokens')::bigint, 0) + coalesce((s->>'output_tokens')::bigint, 0)) "
          "FROM jsonb_array_elements(CASE WHEN jsonb_typeof(per_stage_stats) = 'array' THEN per_stage_stats "
          "ELSE '[]'::jsonb END) s WHERE jsonb_typeof(s->'input_tokens') = 'number')")
# list column: (needed column, SQL expression)
LIST_COLUMNS = {
    "run_id": ("run_id", "run_id"), "started_at": ("started_at", "started_at"),
    "pipeline": ("pipeline", "pipeline"), "subject": ("subject", "left(subject, 200)"),
    "status": ("status", "status"), "source": ("source", "source"),
    "duration_seconds": ("duration_seconds", "duration_seconds"),
    "cost_usd": ("per_stage_stats", COST), "tokens": ("per_stage_stats", TOKENS),
    "developer": ("developer", "developer"), "env_class": ("env_class", "env_class"), "env": ("env", "env"),
    "summary": ("summary", f"left(summary, {TEXT_CUT})"), "error": ("error", f"left(error, {TEXT_CUT})"),
}
SEARCH_TEXT = ("subject", "pipeline", "status", "summary", "error")
_columns_cache = {}


def columns(sb) -> set:
    """The columns of agent_runs in this sandbox's run store (kept 30 s); empty when the table does not exist."""
    hit = _columns_cache.get(sb.project)
    if hit and time.monotonic() - hit[0] < 30:
        return hit[1]
    found = sb.sql("SELECT coalesce(json_agg(column_name), '[]'::json) FROM information_schema.columns "
                   "WHERE table_schema = current_schema() AND table_name = 'agent_runs'") or []
    names = {str(n) for n in found}
    _columns_cache[sb.project] = (time.monotonic(), names)
    return names


def filters_of(query: dict) -> dict:
    """status, pipeline, since (1h/24h/7d/30d) and page from the query string; anything else is dropped."""
    out = {}
    for name in ("status", "pipeline"):
        value = (query.get(name) or "").strip()
        if value and TOKEN.match(value):
            out[name] = value
    since = (query.get("since") or "").strip()
    if since in SINCE:
        out["since"] = since
    try:
        out["page"] = min(max(1, int(query.get("page") or 1)), 10000)
    except ValueError:
        out["page"] = 1
    return out


def list_runs(sb, query: dict) -> dict:
    """One page of runs, newest first, the total and the filter choices."""
    have = columns(sb)
    if not have:
        return {"runs": [], "total": 0, "page": 1, "pages": 0, "filters": {}, "statuses": [], "pipelines": [],
                "note": "this run store has no agent_runs table yet"}
    f = filters_of(query)
    select = ", ".join(f"{expr} AS {name}" for name, (need, expr) in LIST_COLUMNS.items() if need in have)
    where, params = [], {}
    for name in ("status", "pipeline"):
        if name in f and name in have:
            where.append(f"{name} = :'{name}'")
            params[name] = f[name]
    if "since" in f and "started_at" in have:
        where.append("started_at >= now() - :'since'::interval")
        params["since"] = SINCE[f["since"]]
    cond = ("WHERE " + " AND ".join(where)) if where else ""
    order = "ORDER BY started_at DESC" if "started_at" in have else ""
    choices = {n: (f"(SELECT coalesce(json_agg(v ORDER BY v), '[]'::json) FROM (SELECT DISTINCT {n} AS v FROM "
                   f"agent_runs LIMIT 50) d)" if n in have else "'[]'::json") for n in ("status", "pipeline")}
    data = sb.sql(
        f"SELECT json_build_object('rows', (SELECT coalesce(json_agg(r), '[]'::json) FROM (SELECT {select} FROM "
        f"agent_runs {cond} {order} LIMIT {PAGE} OFFSET {(f['page'] - 1) * PAGE}) r), "
        f"'total', (SELECT count(*) FROM agent_runs {cond}), "
        f"'statuses', {choices['status']}, 'pipelines', {choices['pipeline']})", params) or {}
    total = int(data.get("total") or 0)
    return mask_deep({"runs": data.get("rows") or [], "total": total, "page": f["page"],
                      "pages": (total + PAGE - 1) // PAGE, "filters": {k: v for k, v in f.items() if k != "page"},
                      "statuses": data.get("statuses") or [], "pipelines": data.get("pipelines") or [],
                      "missing": sorted({need for need, _ in LIST_COLUMNS.values()} - have)})


def stages_of(row: dict) -> list:
    stages, stats = [], row.get("per_stage_stats")
    for stat in stats if isinstance(stats, list) else []:
        if not isinstance(stat, dict):
            continue
        stages.append({k: stat.get(k) for k in ("stage_name", "status", "started_at", "ended_at", "duration_seconds",
                                                "model", "model_turns", "input_tokens", "output_tokens",
                                                "cache_read", "cost_usd", "tool_calls_total", "tool_call_breakdown")})
    return stages


def run_detail(sb, run_id: str) -> dict | None:
    """The whole row of one run, its stages, cost and tokens, and its events and tool calls from Valkey."""
    if not TOKEN.match(run_id or ""):
        return None
    have = columns(sb)
    if "run_id" not in have:
        return None
    row = sb.sql("SELECT row_to_json(r) FROM agent_runs r WHERE run_id = :'run_id' LIMIT 1", {"run_id": run_id})
    if not isinstance(row, dict):
        return None
    stages = stages_of(row)
    cost = sum(s["cost_usd"] for s in stages if isinstance(s.get("cost_usd"), (int, float)))
    tokens = {k: sum(s[k] for s in stages if isinstance(s.get(k), int))
              for k in ("input_tokens", "output_tokens", "cache_read")}
    try:
        streams = valkey.run_events(sb, run_id)
        streams_error = None
    except ExecError as exc:
        streams, streams_error = {"events": [], "tool_calls": []}, str(exc)
    known = {"run_id", "source", "subject", "pipeline", "status", "summary", "error", "trace_id", "per_stage_stats",
             "duration_seconds", "started_at", "output", "handoff", "facts", "developer", "env_class", "env",
             "agent_name", "instance_id", "cancel_requested_at", "cancel_reason", "cancelled_by", "resurrections",
             "claimed_by", "claimed_at"}
    return mask_deep({"run": row, "stages": stages, "cost_usd": round(cost, 6) if stages else None,
                      "tokens": tokens if stages else None, "events": streams["events"],
                      "tool_calls": streams["tool_calls"], "events_error": streams_error,
                      "other_columns": {k: v for k, v in row.items() if k not in known}})


def like(text: str) -> str:
    return re.sub(r"([%_\\])", r"\\\1", text)


def search_runs(sb, q: str, cap: int = 50) -> list:
    """Runs whose id starts with q, or whose subject, pipeline, status, summary, error or output contain q."""
    have = columns(sb)
    if "run_id" not in have:
        return []
    parts = ["run_id ILIKE :'prefix' ESCAPE '\\'"]
    parts += [f"{c} ILIKE :'pat' ESCAPE '\\'" for c in SEARCH_TEXT if c in have]
    if "output" in have:
        parts.append("output::text ILIKE :'pat' ESCAPE '\\'")
    select = ", ".join(f"{expr} AS {name}" for name, (need, expr) in LIST_COLUMNS.items()
                       if need in have and name in ("run_id", "started_at", "pipeline", "subject", "status",
                                                    "summary"))
    order = "ORDER BY started_at DESC" if "started_at" in have else ""
    rows = sb.sql(f"SELECT coalesce(json_agg(r), '[]'::json) FROM (SELECT {select} FROM agent_runs WHERE "
                  f"{' OR '.join(parts)} {order} LIMIT {int(cap)}) r",
                  {"prefix": like(q) + "%", "pat": "%" + like(q) + "%"}) or []
    return mask_deep(rows)
