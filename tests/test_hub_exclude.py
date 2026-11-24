"""Tests of hiding event kinds in the hub (exclude=): parsing, server paging that fills a page and counts what it
skipped, include and exclude together, the stream page's (✕) buttons, Hidden line and localStorage code, and the
run detail's client-side filter.

    python3 -m unittest discover -s tests
"""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_hub_data import PROJECT, Base, stream_entry  # noqa: E402

import cn_hub_exec  # noqa: E402
import cn_hub_valkey  # noqa: E402


def busy_stream(beats_per_event=6, events=60):
    """Oldest first: each run event is followed by `beats_per_event` heartbeats (newest is a heartbeat)."""
    out, ms = [], 10_000
    for i in range(events):
        ms += 1
        out.append(stream_entry(ms, 0, {"kind": "tool_started" if i % 2 else "stage_stats", "run_id": "run0001"}))
        for _ in range(beats_per_event):
            ms += 1
            out.append(stream_entry(ms, 0, {"kind": "heartbeat"}))
    return out


class ParseTest(unittest.TestCase):
    def test_parse_validates_dedupes_and_caps(self):
        self.assertEqual(cn_hub_valkey.parse_exclude("heartbeat,stage_stats, heartbeat"),
                         ["heartbeat", "stage_stats"])
        self.assertEqual(cn_hub_valkey.parse_exclude("a.b:c-d_1,Bad,<script>,x y,,"), ["a.b:c-d_1"])
        self.assertEqual(cn_hub_valkey.parse_exclude(None), [])
        self.assertEqual(cn_hub_valkey.parse_exclude(["heartbeat", "UP"]), ["heartbeat"])
        many = ",".join(f"k{i}" for i in range(30))
        self.assertEqual(len(cn_hub_valkey.parse_exclude(many)), cn_hub_valkey.EXCLUDE_MAX)
        self.assertEqual(cn_hub_valkey.parse_exclude("x" * 65), [])


class StreamExcludeTest(Base):
    def setUp(self):
        super().setUp()
        self.docker.keys["busy"] = ("stream", busy_stream())

    def api(self, query):
        return json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=busy&" + query)[1])

    def test_paging_fills_fifty_and_counts_skipped(self):
        plain = self.api("")
        self.assertEqual(len(plain["entries"]), 50)
        self.assertGreater(sum(1 for e in plain["entries"] if e["event"]["kind"] == "heartbeat"), 40)
        data = self.api("exclude=heartbeat")
        self.assertEqual(len(data["entries"]), 50)
        self.assertNotIn("heartbeat", [e["event"]["kind"] for e in data["entries"]])
        self.assertEqual(data["exclude"], ["heartbeat"])
        self.assertEqual(data["skipped"], {"heartbeat": 50 * 6})   # six newer beats per event shown
        self.assertEqual(data["next"], data["entries"][-1]["id"])
        older = self.api(f"exclude=heartbeat&before={data['next']}")
        self.assertEqual(len(older["entries"]), 10)
        self.assertIsNone(older["next"])
        self.assertTrue(set(e["id"] for e in older["entries"]).isdisjoint(e["id"] for e in data["entries"]))

    def test_scan_cap_gives_a_more_cursor(self):
        self.docker.keys["beats"] = ("stream", [stream_entry(1000 + i, 0, {"kind": "heartbeat"}) for i in range(2600)])
        data = json.loads(self.get(f"/api/s/{PROJECT}/valkey/key", "key=beats&exclude=heartbeat")[1])
        self.assertEqual(data["entries"], [])
        self.assertEqual((data["scanned"], data["skipped"]), (2000, {"heartbeat": 2000}))
        self.assertEqual(data["next"], "1600-0")
        body = self.get(f"/s/{PROJECT}/valkey/beats", "exclude=heartbeat")[1]
        self.assertIn("the cap of 2000; older continues", body)
        self.assertIn("before=1600-0", body)

    def test_include_then_exclude(self):
        data = self.api("kind=tool_started&exclude=heartbeat,stage_stats")
        self.assertEqual({e["event"]["kind"] for e in data["entries"]}, {"tool_started"})
        self.assertEqual(len(data["entries"]), 30)
        self.assertEqual(data["skipped"], {})                     # include ran first: nothing left to exclude
        data = self.api("kind=tool_started&exclude=tool_started")
        self.assertEqual(data["entries"], [])
        self.assertEqual(data["skipped"], {"tool_started": 30})

    def test_invalid_exclude_is_ignored_and_commands_stay_reads(self):
        data = self.api("exclude=%3Cscript%3E,HEARTBEAT")
        self.assertEqual(data["exclude"], [])
        self.assertEqual(len(data["entries"]), 50)
        self.get(f"/s/{PROJECT}/valkey/busy", "exclude=heartbeat,stage_stats&kind=tool_started")
        for command in self.docker.valkey_commands:
            self.assertIn(command[0], cn_hub_exec.VALKEY_READ)

    def test_page_has_x_buttons_hidden_line_and_local_storage(self):
        body = self.get(f"/s/{PROJECT}/valkey/busy")[1]
        self.assertIn('aria-label="Hide all heartbeat entries"', body)
        self.assertIn(f'href="/s/{PROJECT}/valkey/busy?exclude=heartbeat"', body)
        self.assertIn('id="xk-restored" hidden', body)
        self.assertNotIn("Hidden: ", body)
        body = self.get(f"/s/{PROJECT}/valkey/busy", "exclude=heartbeat,stage_stats")[1]
        self.assertIn("Hidden: ", body)
        self.assertIn('aria-label="Show heartbeat entries again"', body)
        self.assertIn(f'href="/s/{PROJECT}/valkey/busy?exclude=stage_stats" data-exclude="stage_stats"', body)
        self.assertIn(f'href="/s/{PROJECT}/valkey/busy" data-exclude="">Show all</a>', body)
        self.assertIn('<span class="n">360</span>', body)          # every heartbeat: only 30 entries remain
        self.assertIn("390 hidden while filling this page (looked at 420 entries)", body)
        self.assertIn('name="exclude" value="heartbeat,stage_stats"', body)   # the kind form keeps the list
        self.assertIn("exclude=heartbeat%2Cstage_stats", body)               # newest/older keep it too
        self.assertIn("localStorage.setItem", body)
        self.assertIn('"cn-hub-exclude:sandbox-alpha:busy"', body)
        self.assertIn('searchParams.set("restored","1")', body)
        self.assertIn("catch(_)", body)

    def test_store_key_is_safe_inside_the_script(self):
        self.docker.keys['x</script><b>"'] = ("stream", busy_stream(1, 2))
        body = self.get(f"/s/{PROJECT}/valkey/x%3C%2Fscript%3E%3Cb%3E%22")[1]
        script = body[body.index("<script>"):]
        self.assertEqual(script.count("</script>"), 1)
        self.assertIn("\\u003c\\u002fscript\\u003e", script)


class RunExcludeTest(Base):
    def test_run_detail_has_client_side_filter(self):
        body = self.get(f"/s/{PROJECT}/runs/run0001")[1]
        self.assertIn('<tr data-kind="tool_started">', body)
        self.assertIn('data-hide="tool_started" aria-label="Hide all tool_started entries"', body)
        self.assertIn('id="xk-run" hidden', body)
        self.assertIn('id="run-events"', body)
        self.assertIn('get("exclude")', body)
        self.assertIn("history.pushState", body)
        self.assertIn("Show all", body)
        self.assertNotIn("innerHTML", body)


if __name__ == "__main__":
    unittest.main()
