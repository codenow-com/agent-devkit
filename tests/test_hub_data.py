"""Tests of the hub's data views (lib/cn_hub_data.py and its modules) with a fake `docker` that answers like psql
and valkey-cli would: runs list, filters and paging, run detail with events, Valkey keys and streams, search,
read-only enforcement, masking, timeouts and an older run store without some columns.

    python3 -m unittest discover -s tests
"""
import json
import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import cn_hub_data  # noqa: E402
import cn_hub_exec  # noqa: E402
import cn_hub_runs  # noqa: E402

PROJECT = "sandbox-alpha"
JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJwZXRyIn0.c2lnbmF0dXJlLXNlY3JldA"
PG_PASSWORD = "pg-password-never-shown-77"
HEX = "ab" * 32
ALL_COLUMNS = ["run_id", "source", "subject", "pipeline", "status", "summary", "error", "trace_id",
               "per_stage_stats", "duration_seconds", "started_at", "facts", "agent_name", "output", "handoff",
               "env", "env_class", "developer", "claimed_by"]
OLD_COLUMNS = ["run_id", "source", "subject", "pipeline", "status", "summary", "error", "duration_seconds",
               "started_at"]


def run_row(i, status="completed", pipeline="advice"):
    return {"run_id": f"run{i:04d}", "started_at": f"2026-11-24T10:{i % 60:02d}:00+00:00", "pipeline": pipeline,
            "subject": f"subject-{i}", "status": status, "source": "chat", "duration_seconds": 12.5,
            "cost_usd": 0.0123, "tokens": 1000, "developer": "petr", "env_class": "local", "env": "sandbox",
            "summary": f"summary {i}", "error": ""}


def stream_entry(ms, seq, event):
    return [f"{ms}-{seq}", ["e", json.dumps(event)]]


EVENTS = [
    stream_entry(1000, 0, {"kind": "run_started", "event_id": "ev1", "run_id": "run0001", "ts": "t1"}),
    stream_entry(1100, 0, {"kind": "tool_started", "event_id": "ev2", "run_id": "run0001", "tool": "search",
                           "call_id": "c1", "ts": "t2"}),
    stream_entry(1600, 0, {"kind": "tool_ended", "event_id": "ev3", "run_id": "run0001", "tool": "search",
                           "call_id": "c1", "is_error": False, "summary": "1 KB", "ts": "t3"}),
    stream_entry(1700, 0, {"kind": "heartbeat", "event_id": "ev4", "note": f"Bearer {JWT}"}),
    stream_entry(1800, 0, {"kind": "run_finished", "event_id": "ev5", "run_id": "run0001", "status": "completed",
                           "summary": f"done token={JWT}", "ts": "t5"}),
    stream_entry(1900, 0, {"kind": "run_started", "event_id": "ev6", "run_id": "run0002", "ts": "t6"}),
]
CONTENT = [[f"{1100}-1", ["id", "ev2", "b", json.dumps({"args": json.dumps({"query": "trout",
                                                                             "api_key": "short-key-1"})})]],
           [f"{1600}-1", ["id", "ev3", "b", json.dumps({"result": f"found {JWT} {HEX}"})]]]


def unquote_cli(line):
    out = []
    for arg in line.split(" "):
        raw = re.sub(r"\\x([0-9a-f]{2})", lambda m: chr(int(m.group(1), 16)), arg[1:-1])
        out.append(raw.encode("latin-1").decode("utf-8"))
    return out


class FakeDocker:
    """`docker ps/inspect/exec` of one sandbox: psql answers canned JSON, valkey-cli answers from `self.keys`."""

    def __init__(self, columns=ALL_COLUMNS, runs=None):
        self.columns, self.calls, self.valkey_commands, self.sql = columns, [], [], []
        self.runs = runs if runs is not None else [run_row(i) for i in range(1, 121)]
        self.keys = {"swarm:events": ("stream", EVENTS), "swarm:content": ("stream", CONTENT),
                     "cfg:hash": ("hash", ["password", "hunter2", "mode", "shadow"]),
                     "note": ("string", f"Authorization: Bearer {JWT}")}

    def __call__(self, args, stdin=None, timeout=None):
        self.calls.append(list(args))
        if args[0] == "ps":
            service = args[-1].rsplit("=", 1)[1]
            return 0, f"cid-{service}\n", ""
        if args[0] == "inspect":
            env = ["POSTGRES_USER=sandbox", f"POSTGRES_PASSWORD={PG_PASSWORD}", "POSTGRES_DB=runs", "PATH=/bin"]
            return 0, json.dumps(env), ""
        if args[0] == "exec" and "psql" in args:
            self.sql.append((stdin, args))
            return 0, json.dumps(self.answer_sql(stdin, args)) + "\n", ""
        if args[0] == "exec" and "valkey-cli" in args:
            lines = [unquote_cli(line) for line in stdin.splitlines() if line]
            self.valkey_commands.extend(lines)
            return 0, "".join(json.dumps(self.answer_valkey(c)) + "\n" for c in lines), ""
        return 1, "", "unexpected"

    def var(self, args, name):
        for i, a in enumerate(args):
            if a == "-v" and args[i + 1].startswith(name + "="):
                return args[i + 1].split("=", 1)[1]
        return None

    def answer_sql(self, script, args):
        if "information_schema.columns" in script:
            return self.columns
        if "json_build_object('rows'" in script:
            rows = self.runs
            for name in ("status", "pipeline"):
                value = self.var(args, name)
                if value:
                    rows = [r for r in rows if r[name] == value]
            offset = int(re.search(r"OFFSET (\d+)", script).group(1))
            page = [{k: v for k, v in r.items() if k in self.columns or k in ("cost_usd", "tokens")}
                    for r in rows[offset: offset + 50]]
            return {"rows": page, "total": len(rows), "statuses": ["completed", "failed"], "pipelines": ["advice"]}
        if "WHERE run_id = :'run_id'" in script:
            rid = self.var(args, "run_id")
            if rid != "run0001":
                return None
            return {"run_id": rid, "status": "failed", "pipeline": "advice", "subject": "s", "source": "chat",
                    "summary": f"leaked {JWT}", "error": "", "started_at": "2026-11-24T10:00:00+00:00",
                    "output": {"answer": "ok", "api_token": "plain-secret-xyz"}, "mystery": {"x": 1},
                    "per_stage_stats": [{"stage_name": "advice", "status": "completed", "cost_usd": 0.5,
                                         "input_tokens": 10, "output_tokens": 5,
                                         "started_at": "2026-11-24T10:00:00Z", "ended_at": "2026-11-24T10:00:09Z"}]}
        if "ILIKE" in script:
            pat = self.var(args, "pat").strip("%").lower()
            return [r for r in self.runs if pat in r["subject"] or pat in r["summary"]][:50]
        return None

    def answer_valkey(self, cmd):
        name, key = cmd[0], (cmd[1] if len(cmd) > 1 else "")
        kind, value = self.keys.get(key, ("none", None))
        if name == "SCAN":
            pattern = re.escape(cmd[3]).replace(r"\*", ".*")
            return ["0", [k for k in self.keys if re.fullmatch(pattern, k)]]
        if name == "TYPE":
            return kind
        if name == "TTL":
            return -1 if value is not None else -2
        if name in ("XLEN", "HLEN"):
            return len(value) if name == "XLEN" else len(value) // 2
        if name == "STRLEN":
            return len(value)
        if name == "GETRANGE":
            return value[: int(cmd[3]) + 1]
        if name == "HGETALL":
            return value
        if name in ("XRANGE", "XREVRANGE"):
            if kind != "stream":
                return []
            count = int(cmd[cmd.index("COUNT") + 1])
            entries = list(value) if name == "XRANGE" else list(reversed(value))
            bound = cmd[2] if name == "XREVRANGE" else None

            def ms_seq(i):
                a, _, b = i.lstrip("(").partition("-")
                return int(a), int(b or 0)
            if bound and bound != "+":
                limit = ms_seq(bound)
                entries = [x for x in entries if ms_seq(x[0]) < limit or (not bound.startswith("(")
                                                                        and ms_seq(x[0]) == limit)]
            return entries[:count]
        return None


class Base(unittest.TestCase):
    def setUp(self):
        cn_hub_runs._columns_cache.clear()
        cn_hub_data._sandboxes.clear()
        self.docker = FakeDocker()

    def get(self, path, query="", docker=None):
        return cn_hub_data.handle(path, query, [PROJECT, "sandbox-beta"], docker or self.docker)

    def assert_clean(self, body):
        self.assertNotIn(JWT, body)
        self.assertNotIn(PG_PASSWORD, body)
        self.assertNotIn(HEX, body)


class RunsTest(Base):
    def test_runs_list_pages_of_fifty(self):
        code, body, kind = self.get(f"/api/s/{PROJECT}/runs")
        data = json.loads(body)
        self.assertEqual((code, kind), (200, "application/json"))
        self.assertEqual((len(data["runs"]), data["total"], data["pages"]), (50, 120, 3))
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs", "page=3")[1])
        self.assertEqual((len(data["runs"]), data["page"]), (20, 3))
        self.assertIn("OFFSET 100", self.docker.sql[-1][0])

    def test_filters_go_as_psql_variables_and_bad_values_are_dropped(self):
        self.docker.runs = [run_row(1), run_row(2, "failed"), run_row(3, "failed", "other")]
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs", "status=failed&pipeline=other&since=7d")[1])
        self.assertEqual([r["run_id"] for r in data["runs"]], ["run0003"])
        script, args = self.docker.sql[-1]
        self.assertIn("status = :'status'", script)
        self.assertIn("-v", args)
        self.assertIn("since=7 days", args)
        self.get(f"/api/s/{PROJECT}/runs", "status=x';DROP TABLE agent_runs;--&since=99y")
        script, args = self.docker.sql[-1]
        self.assertNotIn("DROP", script + " ".join(args))
        self.assertNotIn("status = ", script)

    def test_runs_page_html(self):
        code, body, kind = self.get(f"/s/{PROJECT}/runs")
        self.assertEqual((code, kind), (200, "text/html; charset=utf-8"))
        self.assertIn(f'href="/s/{PROJECT}/runs/run0001"', body)
        self.assertIn("developer: petr", body)
        self.assertIn("page 1 of 3", body)
        self.assertIn('class="chip ok"', body)

    def test_run_detail_with_events_and_tool_calls(self):
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs/run0001")[1])
        self.assertEqual([e["event"]["kind"] for e in data["events"]],
                         ["run_started", "tool_started", "tool_ended", "run_finished"])
        call = data["tool_calls"][0]
        self.assertEqual((call["tool"], call["duration_ms"], call["summary"]), ("search", 500, "1 KB"))
        self.assertIn("trout", call["args"])
        self.assertEqual(data["cost_usd"], 0.5)
        self.assertEqual(data["other_columns"], {"mystery": {"x": 1}})
        code, body, _ = self.get(f"/s/{PROJECT}/runs/run0001")
        self.assertEqual(code, 200)
        self.assertIn("Tool calls", body)
        self.assertIn(f"/s/{PROJECT}/valkey/swarm%3Aevents?before=1800-1", body)   # back to the stream entry
        self.assertIn("mystery", body)

    def test_unknown_run_and_unknown_sandbox(self):
        self.assertEqual(self.get(f"/api/s/{PROJECT}/runs/nope")[0], 404)
        self.assertEqual(self.get(f"/s/{PROJECT}/runs/bad id!")[0], 404)
        self.assertEqual(self.get("/api/s/sandbox-zeta/runs")[0], 404)
        self.assertEqual(self.get("/s/sandbox-zeta/runs")[0], 404)

    def test_missing_columns_are_tolerated(self):
        self.docker.columns = OLD_COLUMNS
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs")[1])
        self.assertEqual(data["total"], 120)
        self.assertIn("developer", data["missing"])
        self.assertNotIn("per_stage_stats", self.docker.sql[-1][0])
        self.assertNotIn("developer", self.docker.sql[-1][0])
        self.assertEqual(self.get(f"/s/{PROJECT}/runs")[0], 200)

    def test_no_table_yet(self):
        self.docker.columns = []
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs")[1])
        self.assertEqual(data["runs"], [])
        self.assertIn("no agent_runs table", data["note"])


class ValkeyTest(Base):
    def test_key_list_with_type_ttl_size(self):
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/keys")[1])
        rows = {k["key"]: k for k in data["keys"]}
        self.assertEqual(rows["swarm:events"]["type"], "stream")
        self.assertEqual(rows["swarm:events"]["size"], len(EVENTS))
        self.assertEqual(rows["cfg:hash"]["ttl"], -1)
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/keys", "pattern=swarm:*")[1])
        self.assertEqual(sorted(k["key"] for k in data["keys"]), ["swarm:content", "swarm:events"])
        self.assertIn("swarm:content", self.get(f"/s/{PROJECT}/valkey")[1])

    def test_stream_view_newest_first_with_kind_filter_and_paging(self):
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=swarm:events")[1])
        self.assertEqual(data["entries"][0]["id"], "1900-0")
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=swarm:events&kind=run_started")[1])
        self.assertEqual([e["id"] for e in data["entries"]], ["1900-0", "1000-0"])
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=swarm:events&before=1700-0")[1])
        self.assertEqual(data["entries"][0]["id"], "1600-0")
        code, body, _ = self.get(f"/s/{PROJECT}/valkey/swarm%3Aevents", "kind=run_finished")
        self.assertEqual(code, 200)
        self.assertIn(f'href="/s/{PROJECT}/runs/run0001"', body)

    def test_hash_and_string(self):
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=cfg:hash")[1])
        self.assertEqual(data["fields"], [["password", "<masked>"], ["mode", "shadow"]])
        body = self.get(f"/s/{PROJECT}/valkey/note")[1]
        self.assertIn("Bearer &lt;token&gt;", body)
        self.assertEqual(self.get(f"/api/s/{PROJECT}/valkey/key")[0], 400)


class SearchTest(Base):
    def test_search_across_runs_events_and_keys(self):
        data = json.loads(self.get(f"/api/s/{PROJECT}/search", "q=summary 7")[1])
        self.assertTrue(any(r["run_id"] == "run0007" for r in data["runs"]))
        data = json.loads(self.get(f"/api/s/{PROJECT}/search", "q=run_finished")[1])
        self.assertEqual([e["id"] for e in data["events"] if e["stream"] == "swarm:events"], ["1800-0"])
        self.assertEqual(data["errors"], {})
        data = json.loads(self.get(f"/api/s/{PROJECT}/search", "q=hash")[1])
        self.assertEqual(data["keys"], ["cfg:hash"])
        body = self.get(f"/s/{PROJECT}/search", "q=run_finished")[1]
        self.assertIn("Events (1)", body)

    def test_search_text_reaches_sql_only_as_a_variable(self):
        self.get(f"/api/s/{PROJECT}/search", "q=x' OR 1=1; DROP TABLE agent_runs;--")
        script, args = [s for s in self.docker.sql if "ILIKE" in s[0]][-1]
        self.assertNotIn("DROP", script)
        self.assertIn("pat=%x' OR 1=1; DROP TABLE agent\\_runs;--%", args)


class SafetyTest(Base):
    def test_disallowed_valkey_commands_are_never_built(self):
        sb = cn_hub_exec.Sandbox(PROJECT, self.docker)
        for command in (["DEL", "k"], ["FLUSHALL"], ["SET", "k", "v"], ["XADD", "s", "*", "a", "b"],
                        ["CONFIG", "GET", "*"], ["EVAL", "return 1", "0"], ["MEMORY", "DOCTOR"],
                        ["XINFO", "GROUPS", "s"], ["flushdb"]):
            with self.assertRaises(ValueError):
                sb.valkey(command)
        self.assertEqual(self.docker.calls, [])
        with self.assertRaises(ValueError):
            sb.sql("DELETE FROM agent_runs")
        self.assertEqual(self.docker.calls, [])

    def test_every_command_of_a_full_tour_is_a_read(self):
        for path, query in [(f"/s/{PROJECT}/runs", ""), (f"/s/{PROJECT}/runs/run0001", ""),
                            (f"/s/{PROJECT}/valkey", ""), (f"/s/{PROJECT}/valkey/swarm%3Aevents", "kind=x"),
                            (f"/s/{PROJECT}/valkey/cfg%3Ahash", ""), (f"/s/{PROJECT}/search", "q=a")]:
            self.get(path, query)
        self.assertTrue(self.docker.valkey_commands)
        for command in self.docker.valkey_commands:
            self.assertIn(command[0], cn_hub_exec.VALKEY_READ)
        for script, args in self.docker.sql:
            self.assertTrue(script.startswith("BEGIN READ ONLY;"))
            self.assertNotRegex(script.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|HARNESS_SECRETS)\b")
        self.assertNotIn(PG_PASSWORD, json.dumps(self.docker.calls))

    def test_masking_in_html_and_json(self):
        for path, query in [(f"/s/{PROJECT}/runs/run0001", ""), (f"/api/s/{PROJECT}/runs/run0001", ""),
                            (f"/s/{PROJECT}/valkey/swarm%3Aevents", ""),
                            (f"/api/s/{PROJECT}/valkey/key", "key=swarm:events"),
                            (f"/api/s/{PROJECT}/valkey/key", "key=note"), (f"/s/{PROJECT}/search", "q=token"),
                            (f"/api/s/{PROJECT}/search", "q=Bearer")]:
            code, body, _ = self.get(path, query)
            self.assertEqual(code, 200, path)
            self.assert_clean(body)
        detail = json.loads(self.get(f"/api/s/{PROJECT}/runs/run0001")[1])
        self.assertEqual(detail["run"]["output"]["api_token"], "<masked>")
        self.assertIn("<masked>", detail["tool_calls"][0]["args"])          # api_key inside JSON text
        self.assertNotIn("short-key-1", json.dumps(detail))

    def test_mask_helpers(self):
        self.assertEqual(cn_hub_exec.mask_log("x " + "A1b2" * 16 + " y"), "x <masked> y")
        self.assertEqual(cn_hub_exec.mask_deep({"secret": "s"}), {"secret": "<masked>"})
        self.assertEqual(cn_hub_exec.mask('{"password": "abc def"}'), '{"password": "<masked>"}')

    def test_a_docker_that_does_not_answer(self):
        def slow(args, stdin=None, timeout=None):
            raise cn_hub_exec.ExecError(f"docker did not answer in {timeout:g} s (docker exec)")
        code, body, kind = self.get(f"/api/s/{PROJECT}/runs", docker=slow)
        self.assertEqual(code, 502)
        self.assertIn("did not answer", json.loads(body)["error"])
        code, body, _ = self.get(f"/s/{PROJECT}/valkey", docker=slow)
        self.assertEqual(code, 502)
        self.assertIn("did not answer", body)

    def test_run_process_timeout(self):
        with mock.patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(["docker"], 8)):
            with self.assertRaises(cn_hub_exec.ExecError) as caught:
                cn_hub_exec.run_process(["exec", "x"], None, 8)
        self.assertIn("did not answer in 8 s", str(caught.exception))

    def test_psql_error_is_reported_masked(self):
        def failing(args, stdin=None, timeout=None):
            if args[0] == "exec":
                return 3, "", f"psql: FATAL: password={PG_PASSWORD} rejected"
            return FakeDocker()(args, stdin, timeout)
        code, body, _ = self.get(f"/api/s/{PROJECT}/runs", docker=failing)
        self.assertEqual(code, 502)
        self.assertNotIn(PG_PASSWORD, body)

    def test_events_error_keeps_the_run(self):
        def no_valkey(args, stdin=None, timeout=None):
            if "valkey-cli" in args or "redis-cli" in args:
                return 1, "", "connection refused"
            return self.docker(args, stdin, timeout)
        data = json.loads(self.get(f"/api/s/{PROJECT}/runs/run0001", docker=no_valkey)[1])
        self.assertEqual(data["run"]["run_id"], "run0001")
        self.assertIn("connection refused", data["events_error"])

    def test_body_cap(self):
        with mock.patch.object(cn_hub_data, "MAX_BODY", 100):
            self.assertEqual(self.get(f"/api/s/{PROJECT}/runs")[0], 413)


if __name__ == "__main__":
    unittest.main()
