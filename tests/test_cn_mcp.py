"""Tests of lib/cn_mcp.py (cn-call, cn-wait, cn-setup save-key) against a local MCP server on 127.0.0.1.

    python3 -m unittest discover -s tests
"""
import http.server
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "lib" / "cn_mcp.py"
sys.path.insert(0, str(ROOT / "lib"))
import cn_mcp  # noqa: E402

KEY = "cnk_test-Key.123"


def tool_answer(value):
    return {"content": [{"type": "text", "text": json.dumps(value)}]}


class Server:
    """A fake MCP server. tools maps a tool name to a function(arguments) -> result; raw overrides the answer."""

    def __init__(self):
        self.tools, self.raw, self.requests, self.deletes, self.keys = {}, None, [], [], []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_DELETE(self):
                owner.deletes.append(self.headers.get("Mcp-Session-Id"))
                self.send_response(204)
                self.end_headers()

            def do_POST(self):
                owner.keys.append(self.headers.get("X-Codenow-Api-Key"))
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                owner.requests.append(body)
                if owner.raw and body.get("method") == "tools/call":
                    return owner.raw(self, body)
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                if body["method"] == "initialize":
                    result = {"protocolVersion": "2025-06-18", "capabilities": {}}
                else:
                    tool = owner.tools[body["params"]["name"]]
                    result = tool(body["params"]["arguments"])
                self.reply(json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}))

            def reply(self, text, status=200, content_type="application/json", headers=()):
                data = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Mcp-Session-Id", "session-1")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.addCleanup(self.server.stop)
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)

    def run_cn(self, *args, key=KEY, url=None, timeout=20):
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
        env.update({"CODENOW_HOME": self.home.name, "CODENOW_MCP_URL": url or self.server.url, "no_proxy": "*",
                    "CODENOW_API_KEY": key})
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env=env, capture_output=True, text=True,
                              timeout=timeout)
        self.assertNotIn("Traceback", done.stderr)
        self.assertNotIn(key.strip() or "\0", done.stdout + done.stderr)
        return done


class CallTest(Base):
    def test_call_prints_json_and_closes_the_session(self):
        self.server.tools["agent_swarms_list"] = lambda args: tool_answer([{"id": "s1"}])
        done = self.run_cn("call", "agent_swarms_list")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [{"id": "s1"}])
        self.assertEqual(self.server.deletes, ["session-1"])

    def test_key_is_stripped(self):
        self.server.tools["t"] = lambda args: tool_answer({})
        self.assertEqual(self.run_cn("call", "t", key=f"  {KEY}\r\n").returncode, 0)
        self.assertEqual(set(self.server.keys), {KEY})

    def test_key_with_a_space_is_refused(self):
        done = self.run_cn("call", "t", key="abc def")
        self.assertEqual(done.returncode, 2)
        self.assertIn("API key", done.stderr)
        self.assertEqual(self.server.requests, [])

    def test_sse_with_several_events_takes_the_matching_id(self):
        def sse(handler, body):
            other = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
            wrong = {"jsonrpc": "2.0", "id": 999, "result": tool_answer("wrong")}
            right = {"jsonrpc": "2.0", "id": body["id"], "result": tool_answer({"ok": True})}
            text = "".join(f"event: message\r\ndata: {json.dumps(m)}\r\n\r\n" for m in (other, wrong, right))
            handler.reply(text, content_type="text/event-stream")
        self.server.raw = sse
        done = self.run_cn("call", "t")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), {"ok": True})

    def test_bad_answers_are_one_line_errors(self):
        cases = {
            "not json": lambda h, b: h.reply("<html>proxy error</html>", content_type="text/html"),
            "empty": lambda h, b: h.reply(""),
            "result null": lambda h, b: h.reply(json.dumps({"jsonrpc": "2.0", "id": b["id"], "result": None})),
            "http 500": lambda h, b: h.reply("{}", status=500),
            "disconnect": lambda h, b: h.connection.close(),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.server.raw = raw
                done = self.run_cn("call", "t")
                self.assertEqual(done.returncode, 2, done.stdout)
                self.assertEqual(len(done.stderr.strip().splitlines()), 1, done.stderr)

    def test_redirect_is_refused_and_the_key_stays(self):
        other = Server()
        self.addCleanup(other.stop)
        other.tools["t"] = lambda args: tool_answer({})
        self.server.raw = lambda h, b: h.reply("", status=302, headers=[("Location", other.url)])
        done = self.run_cn("call", "t")
        self.assertEqual(done.returncode, 2)
        self.assertIn("redirect", done.stderr)
        self.assertEqual(other.keys, [])

    def test_bad_arguments(self):
        for args in (["call"], ["call", "t", "{not json"], ["call", "t", "[1, 2]"], ["wait"], ["wait", "build", "s"],
                     ["wait", "deploy", "s", "e", "--max"], ["wait", "deploy", "s", "e", "--max", "x"],
                     ["wait", "deploy", "s", "e", "--max", "0"], ["nothing"]):
            with self.subTest(args):
                done = self.run_cn(*args)
                self.assertEqual(done.returncode, 2)
                self.assertTrue(done.stderr.startswith("cn: "), done.stderr)
        self.assertEqual(self.server.requests, [])

    def test_url_schemes(self):
        for url in ("ftp://127.0.0.1/mcp", "http://example.com/mcp", "file:///etc/passwd", "mcp.example.com"):
            with self.subTest(url):
                done = self.run_cn("call", "t", url=url)
                self.assertEqual(done.returncode, 2)
                self.assertIn("https://", done.stderr)
        for url in ("https://mcp.example.com/mcp", "http://localhost:8080/mcp", "http://[::1]:8080/mcp"):
            self.assertEqual(cn_mcp.check_url(url), url)

    def test_no_url_says_so(self):
        done = self.run_cn("call", "t", url=" ")
        self.assertEqual(done.returncode, 2)
        self.assertIn("CODENOW_MCP_URL is not set", done.stderr)


class WaitTest(Base):
    def build(self, *statuses):
        statuses = list(statuses)
        self.server.tools["agents_builds_list"] = lambda args: tool_answer({"content": [{"id": "b1"}]})
        self.server.tools["agents_builds_detail"] = lambda args: tool_answer(
            {"status": statuses.pop(0) if len(statuses) > 1 else statuses[0], "url": "u"})

    def test_build_done(self):
        self.build("BUILD_FINISHED")
        done = self.run_cn("wait", "build", "s", "a")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.server.deletes, ["session-1"])

    def test_failed_and_unknown_status_end_with_1(self):
        for status in ("FAILED", "SOMETHING_NEW"):
            with self.subTest(status):
                self.build(status)
                done = self.run_cn("wait", "build", "s", "a", "b1")
                self.assertEqual(done.returncode, 1)
                self.assertIn(status, done.stdout)

    def test_still_running_ends_with_3(self):
        self.build("RUNNING")
        started = time.monotonic()
        done = self.run_cn("wait", "build", "s", "a", "--max", "5")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertLess(time.monotonic() - started, 5)

    def test_no_build_id(self):
        self.server.tools["agents_builds_list"] = lambda args: tool_answer({"content": [{"version": "1"}]})
        done = self.run_cn("wait", "build", "s", "a")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no id", done.stderr)

    def test_slow_server_stays_within_max(self):
        def slow(handler, body):
            time.sleep(6)
            handler.reply("{}")
        self.server.raw = slow
        started = time.monotonic()
        done = self.run_cn("wait", "deploy", "s", "e", "--max", "3")
        self.assertEqual(done.returncode, 3, done.stderr)
        self.assertLess(time.monotonic() - started, 5.5)

    def test_deploy_healthy(self):
        self.server.tools["agent_swarm_deployment_detail"] = lambda args: tool_answer(
            {"deployment": {"status": "HEALTHY", "version": "1"}})
        self.assertEqual(self.run_cn("wait", "deploy", "s", "e").returncode, 0)


class SaveKeyTest(Base):
    def credentials(self):
        return pathlib.Path(self.home.name) / "credentials"

    def test_working_key_replaces_an_open_file_with_mode_600(self):
        self.credentials().write_text("CODENOW_API_KEY=old\n")
        self.credentials().chmod(0o644)
        self.server.tools["agent_swarms_list"] = lambda args: tool_answer([])
        done = self.run_cn("save-key", key=f"{KEY}\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(stat.S_IMODE(self.credentials().stat().st_mode), 0o600)
        self.assertEqual(cn_mcp.read_settings(self.credentials())["CODENOW_API_KEY"], KEY)

    def test_key_that_does_not_work_keeps_the_stored_key(self):
        self.credentials().write_text("CODENOW_API_KEY=old\n")
        self.server.raw = lambda h, b: h.reply("{}", status=401)
        done = self.run_cn("save-key")
        self.assertEqual(done.returncode, 2)
        self.assertIn("stored key stays", done.stderr)
        self.assertEqual(self.credentials().read_text(), "CODENOW_API_KEY=old\n")


class HomeTest(unittest.TestCase):
    def test_empty_codenow_home_means_the_default(self):
        old = os.environ.get("CODENOW_HOME")
        os.environ["CODENOW_HOME"] = ""
        try:
            self.assertEqual(cn_mcp.home(), pathlib.Path.home() / ".codenow")
        finally:
            if old is None:
                del os.environ["CODENOW_HOME"]
            else:
                os.environ["CODENOW_HOME"] = old


class ForgetKeyTest(unittest.TestCase):
    def test_forget_key_removes_the_file(self):
        with tempfile.TemporaryDirectory() as home:
            credentials = pathlib.Path(home) / "credentials"
            credentials.write_text("CODENOW_API_KEY=old\n")
            env = dict(os.environ, CODENOW_HOME=home)
            done = subprocess.run(["bash", str(ROOT / "bin" / "cn-setup"), "--forget-key"], env=env,
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse(credentials.exists())


if __name__ == "__main__":
    unittest.main()
