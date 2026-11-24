"""Tests of the hub's A2A "Try it" (lib/cn_hub_a2a*.py, lib/cn_hub_render_a2a.py) against a fake agent HTTP server
(card, message/send, tasks/get) and fake token helpers: card parsing (SDK and ADK shapes), the send flow with polling
and the run link, origin and CSRF refusals, wrong method, oversize, timeout, the token never in HTML or JSON, and
the guidance when no token can be made.

    python3 -m unittest discover -s tests
"""
import http.client
import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import cn_hub  # noqa: E402
import cn_hub_a2a as a2a  # noqa: E402
import cn_hub_a2a_routes as routes  # noqa: E402
import cn_hub_a2a_token as tokens  # noqa: E402

TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjYWxsZXItc2VjcmV0In0.c2lnbmF0dXJlLW9mLXRoZS1jYWxsZXI"
SDK_CARD = {"name": "tariff", "description": "2 pipelines", "url": "https://agw.example.com/agents/s/e/tariff/a2a",
            "version": "1.0", "protocolVersion": "0.3.0", "capabilities": {"streaming": False},
            "defaultInputModes": ["application/json", "text/plain"], "defaultOutputModes": ["application/json"],
            "skills": [{"id": "consult", "name": "consult", "description": "chat", "tags": ["consult"]},
                       {"id": "tariff-advice", "name": "tariff-advice", "description": "Classifies goods", "tags": []}]}
ADK_CARD = {"name": "scorer", "description": "An AI agent", "url": "http://localhost:9999", "protocolVersion": "0.3.0",
            "capabilities": {"streaming": True}, "defaultInputModes": ["text/plain"],
            "skills": [{"id": "ask", "name": "ask", "description": "Scores", "tags": ["adk"],
                        "examples": ["Score this sentence"]}]}


class FakeAgent:
    """An agent on 127.0.0.1:<free port>: GET the card, POST JSON-RPC at the card's path (or /)."""

    def __init__(self, card, mode="sdk"):
        self.card, self.mode, self.calls, self.polls, self.delay, self.big = card, mode, [], 0, 0, False
        agent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, code, value):
                data = value if isinstance(value, bytes) else json.dumps(value).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                if self.path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
                    self.reply(200, agent.card)
                else:
                    self.reply(404, {})

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                auth = self.headers.get("Authorization", "")
                agent.calls.append((self.path, auth, body))
                time.sleep(agent.delay)
                if agent.mode == "401":
                    self.reply(401, {"detail": f"bad token {auth}"})
                    return
                if agent.big:
                    self.reply(200, b'{"x":"' + b"a" * 3000 + b'"}')
                    return
                rid = body.get("id")
                if body["method"] == "message/send" and agent.mode == "sdk":
                    self.reply(200, {"jsonrpc": "2.0", "id": rid, "result": {"id": "run-42", "kind": "task",
                                                                             "status": {"state": "submitted"}}})
                elif body["method"] == "tasks/get":
                    agent.polls += 1
                    if agent.polls < 2:
                        self.reply(200, {"jsonrpc": "2.0", "id": rid, "result": {"id": "run-42",
                                                                                 "status": {"state": "working"}}})
                        return
                    self.reply(200, {"jsonrpc": "2.0", "id": rid, "result": {
                        "id": "run-42", "status": {"state": "completed"},
                        "result": {"run_id": "run-42", "summary": f"HS 0302 for trout {auth}", "token": auth},
                        "artifacts": [{"name": "output", "parts": [{"kind": "data", "data": {"code": "0302"}}]}]}})
                elif body["method"] == "message/send" and agent.mode == "adk":
                    self.reply(200, {"jsonrpc": "2.0", "id": rid, "result": {
                        "id": "t-1", "contextId": "c-1", "kind": "task", "status": {"state": "completed"},
                        "artifacts": [{"parts": [{"kind": "text", "text": "Score: 4/5"}]}]}})
                elif agent.mode == "rpcerror":
                    self.reply(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32001, "message": "Unknown skill"}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def sandbox(port, repo="", sdk="2.24.0", adapter="legacy-refresh-token"):
    return {"project": "sandbox-alpha", "name": "alpha", "repo": repo, "status": "running", "sdk_version": sdk,
            "console": {"port": port}, "identity": {"adapter": adapter}, "services": []}


def fake_token(sb):
    return TOKEN, "a test token"


class CardTest(unittest.TestCase):
    def test_sdk_card(self):
        card = a2a.parse_card(SDK_CARD)
        self.assertEqual(card["flavor"], "sdk")
        self.assertEqual([s["id"] for s in card["skills"]], ["consult", "tariff-advice"])
        self.assertTrue(card["skills"][0]["special"])
        self.assertEqual(a2a.endpoint(card, 8080), "http://127.0.0.1:8080/agents/s/e/tariff/a2a")

    def test_adk_card(self):
        card = a2a.parse_card(ADK_CARD)
        self.assertEqual(card["flavor"], "a2a")
        self.assertEqual(card["skills"][0]["examples"], ["Score this sentence"])
        self.assertTrue(card["streaming"])
        self.assertEqual(a2a.endpoint(card, 8081), "http://127.0.0.1:8081/")

    def test_endpoint_never_leaves_the_local_port(self):
        for url in ("http://evil.example.com:80/a2a", "/a2a", "https://x/../../etc", "javascript:alert(1)"):
            self.assertTrue(a2a.endpoint({"url": url}, 8080).startswith("http://127.0.0.1:8080/"))

    def test_message_shape_as_sandbox_run_builds_it(self):
        msg = a2a.build_message("tariff-advice", "fresh trout?", "trout", {"origin_country": "NO"}, sdk=True)
        self.assertEqual(msg["metadata"], {"skillId": "tariff-advice"})
        self.assertEqual(msg["parts"][0], {"kind": "text", "type": "text", "text": "fresh trout?"})
        self.assertEqual(msg["parts"][1]["data"], {"origin_country": "NO", "subject": "trout"})
        self.assertNotIn("type", a2a.build_message("ask", "hi", "", {}, sdk=False)["parts"][0])

    def test_audience_mode_from_the_log(self):
        log = ("A2A_EXPECTED_AUDIENCE before A2A_AUDIENCE_MODE=enforce\n"
               "No inbound audience: A2A_AUDIENCE_MODE=shadow accepts every token\n")
        self.assertEqual(a2a.audience_mode(log), "shadow")
        self.assertEqual(a2a.audience_mode(""), "unknown")


class SendTest(unittest.TestCase):
    def setUp(self):
        self.agent = FakeAgent(SDK_CARD)
        self.patches = [mock.patch.object(a2a, "POLL_S", 0.01)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.agent.close()

    def post(self, sb, body, **kw):
        return routes.post_send(sb, json.dumps(body).encode(), "", token_fn=fake_token, **kw)

    def test_sdk_send_polls_until_completed_and_links_the_run(self):
        code, out = self.post(sandbox(self.agent.port), {"skill": "tariff-advice", "text": "HS code for fresh trout?"})
        self.assertEqual(code, 200, out)
        self.assertEqual((out["state"], out["run_id"], out["task_id"]), ("completed", "run-42", "run-42"))
        self.assertEqual(out["data"], [{"code": "0302"}])
        self.assertIn("HS 0302", out["text"])
        path, auth, body = self.agent.calls[0]
        self.assertEqual(path, "/agents/s/e/tariff/a2a")
        self.assertEqual(auth, "Bearer " + TOKEN)
        self.assertEqual(body["params"]["message"]["metadata"]["skillId"], "tariff-advice")
        self.assertEqual([c[2]["method"] for c in self.agent.calls], ["message/send", "tasks/get", "tasks/get"])
        self.assertNotIn(TOKEN, json.dumps(out))
        self.assertIn("duration_s", out)

    def test_adk_answer_in_one_call(self):
        self.agent.card, self.agent.mode = ADK_CARD, "adk"
        code, out = self.post(sandbox(self.agent.port, sdk=None), {"skill": "ask", "text": "Score this"})
        self.assertEqual((code, out["state"], out["text"], out["run_id"]), (200, "completed", "Score: 4/5", None))
        self.assertEqual(self.agent.calls[0][0], "/")

    def test_401_is_explained_and_the_token_is_not_echoed(self):
        self.agent.mode = "401"
        code, out = self.post(sandbox(self.agent.port), {"skill": "tariff-advice", "text": "x"})
        self.assertEqual(code, 401)
        self.assertIn("audience mode", out["guidance"])
        self.assertNotIn(TOKEN, json.dumps(out))

    def test_rpc_error(self):
        self.agent.mode = "rpcerror"
        self.agent.card = dict(SDK_CARD, url="/a2a")
        code, out = self.post(sandbox(self.agent.port), {"skill": "nope", "text": "x"})
        self.assertEqual((code, out["ok"]), (200, False))
        self.assertIn("Unknown skill", out["error"])

    def test_timeout(self):
        self.agent.delay = 1.5
        with mock.patch.object(a2a, "TIMEOUT_S", 0.5):
            code, out = self.post(sandbox(self.agent.port), {"skill": "tariff-advice", "text": "x"})
        self.assertEqual(code, 504, out)

    def test_oversize_answer_and_request(self):
        self.agent.big = True
        with mock.patch.object(a2a, "MAX_RESPONSE", 1000):
            code, out = self.post(sandbox(self.agent.port), {"skill": "tariff-advice", "text": "x"})
        self.assertEqual(code, 502)
        self.assertIn("larger than 4 MB", out["error"])
        code, out = self.post(sandbox(self.agent.port), {"skill": "s", "text": "x" * (33 * 1024)})
        self.assertEqual(code, 413)

    def test_one_send_per_sandbox(self):
        lock = routes.busy("sandbox-alpha")
        lock.acquire()
        try:
            code, _ = self.post(sandbox(self.agent.port), {"skill": "s", "text": "x"})
        finally:
            lock.release()
        self.assertEqual(code, 409)

    def test_no_token_gives_guidance(self):
        tmp = tempfile.mkdtemp()
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SANDBOX_CALLER_TOKEN", None)
                code, out = routes.post_send(sandbox(self.agent.port, repo=tmp), json.dumps(
                    {"skill": "s", "text": "x"}).encode(), "")
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(code, 424)
        self.assertIn("cn-sandbox run", out["guidance"])
        self.assertEqual(self.agent.calls, [])


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.repo = pathlib.Path(tempfile.mkdtemp())
        (self.repo / "sandbox" / ".run").mkdir(parents=True)
        (self.repo / "sandbox" / "sandbox.sh").write_text("exit 1\n")
        self.argv = []

    def tearDown(self):
        shutil.rmtree(self.repo)

    def runner(self, answers):
        def run(argv, cwd):
            self.argv.append(argv)
            return answers.get(argv[0], "")
        return run

    def sb(self, adapter="legacy-refresh-token"):
        return {"repo": str(self.repo), "identity": {"adapter": adapter}}

    def test_env_token_first(self):
        token, label = tokens.caller_token(self.sb(), {"SANDBOX_CALLER_TOKEN": TOKEN}, self.runner({}))
        self.assertEqual((token, self.argv), (TOKEN, []))
        self.assertIn("SANDBOX_CALLER_TOKEN", label)

    def test_dev_idp_uses_the_sandbox_helper_with_the_audience(self):
        (self.repo / ".env").write_text("SANDBOX_IDP=dev\nA2A_EXPECTED_AUDIENCE=agent-x\nAI_GATEWAY_REFRESH_TOKEN=r\n")
        token, _ = tokens.caller_token(self.sb(), {}, self.runner({"bash": TOKEN}))
        self.assertEqual(token, TOKEN)
        self.assertEqual(self.argv[0][2:5], ["token", "person", self.argv[0][4]])
        self.assertEqual(self.argv[0][-2:], ["--aud", "agent-x"])

    def test_predeploy_falls_back_to_oidc_agent(self):
        (self.repo / "sandbox" / ".run" / "predeploy").write_text("")
        token, _ = tokens.caller_token(self.sb("developer"), {"CN_OIDC_ACCOUNT": "mine"},
                                       self.runner({"oidc-token": TOKEN}))
        self.assertEqual(token, TOKEN)
        self.assertEqual(self.argv[-1], ["oidc-token", "--time=60", "mine"])

    def test_developer_identity_uses_oidc_token(self):
        token, label = tokens.caller_token(self.sb("developer"), {}, self.runner({"oidc-token": TOKEN + "\n"}))
        self.assertEqual(token, TOKEN)
        self.assertIn("cn-agw", label)
        with self.assertRaises(tokens.NoToken) as caught:
            tokens.caller_token(self.sb("developer"), {}, self.runner({"oidc-token": "not a jwt"}))
        self.assertIn("oidc-add", str(caught.exception))

    def test_refresh_grant_at_the_tenant_iam(self):
        (self.repo / ".env").write_text("OIDC_ISSUER_URL=https://iam.example.com/realms/t\nOIDC_CLIENT_ID=agent\n"
                                        "AI_GATEWAY_REFRESH_TOKEN=refresh-secret\n")
        seen = []

        class Answer:
            def __init__(self, value):
                self.value = value

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                return json.dumps(self.value).encode()

        def opener(request, timeout):
            seen.append(request)
            if isinstance(request, str):
                return Answer({"token_endpoint": "https://iam.example.com/token"})
            return Answer({"access_token": TOKEN})

        token, _ = tokens.caller_token(self.sb(), {}, self.runner({}), opener)
        self.assertEqual(token, TOKEN)
        self.assertIn(b"grant_type=refresh_token", seen[1].data)
        self.assertIn(b"client_id=agent", seen[1].data)


class HubRouteTest(unittest.TestCase):
    """The real hub handler on a free port: the page, the card JSON and the POST guard."""

    def setUp(self):
        self.agent = FakeAgent(SDK_CARD)
        self.sandboxes = [sandbox(self.agent.port)]
        probe = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.port = probe.server_address[1]
        probe.server_close()
        cache = cn_hub.Cache(lambda: self.sandboxes)
        self.hub = ThreadingHTTPServer(("127.0.0.1", self.port), cn_hub.make_handler(cache, self.port))
        threading.Thread(target=self.hub.serve_forever, daemon=True).start()
        self.env = mock.patch.dict(os.environ, {"SANDBOX_CALLER_TOKEN": TOKEN})
        self.env.start()
        mock.patch.object(a2a, "POLL_S", 0.01).start()

    def tearDown(self):
        mock.patch.stopall()
        self.hub.shutdown()
        self.hub.server_close()
        self.agent.close()

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers={"Host": f"localhost:{self.port}", **(headers or {})})
        answer = conn.getresponse()
        return answer.status, answer.read().decode()

    def good(self, **extra):
        return {"Origin": f"http://localhost:{self.port}", "X-CN-Hub-Token": routes.CSRF,
                "Content-Type": "application/json", **extra}

    def test_page_and_card(self):
        code, page = self.call("GET", "/s/sandbox-alpha/try")
        self.assertEqual(code, 200)
        self.assertIn("model calls are billed", page)
        self.assertIn(routes.CSRF, page)
        self.assertIn("tariff-advice", page)
        self.assertNotIn(TOKEN, page)
        code, card = self.call("GET", "/api/s/sandbox-alpha/a2a/card")
        self.assertEqual((code, json.loads(card)["card"]["name"]), (200, "tariff"))
        code, _ = self.call("GET", "/")
        self.assertIn("/try", self.call("GET", "/cards")[1])

    def test_send_through_the_hub(self):
        code, text = self.call("POST", "/api/s/sandbox-alpha/a2a/send",
                               json.dumps({"skill": "tariff-advice", "text": "trout"}), self.good())
        self.assertEqual(code, 200, text)
        self.assertEqual(json.loads(text)["run_id"], "run-42")
        self.assertNotIn(TOKEN, text)

    def test_refusals(self):
        body = json.dumps({"skill": "tariff-advice", "text": "trout"})
        cases = [(self.good(Origin="http://evil.example.com"), 403), ({**self.good(), "X-CN-Hub-Token": "x"}, 403),
                 ({k: v for k, v in self.good().items() if k != "Origin"}, 403),
                 (self.good(**{"Content-Type": "text/plain"}), 415)]
        for headers, want in cases:
            self.assertEqual(self.call("POST", "/api/s/sandbox-alpha/a2a/send", body, headers)[0], want, headers)
        ok_referer = {k: v for k, v in self.good().items() if k != "Origin"}
        ok_referer["Referer"] = f"http://127.0.0.1:{self.port}/s/sandbox-alpha/try"
        self.assertEqual(self.call("POST", "/api/s/sandbox-alpha/a2a/send", body, ok_referer)[0], 200)
        self.assertEqual(self.call("POST", "/api/s/sandbox-alpha/a2a/send", "x" * 50000, self.good())[0], 413)
        self.assertEqual(self.call("GET", "/api/s/sandbox-alpha/a2a/send")[0], 405)
        self.assertEqual(self.call("PUT", "/api/s/sandbox-alpha/a2a/send", body, self.good())[0], 405)
        self.assertEqual(self.call("POST", "/api/s/sandbox-alpha/runs", body, self.good())[0], 404)
        self.assertEqual(self.call("POST", "/api/s/sandbox-nope/a2a/send", body, self.good())[0], 404)
        sends = [c for c in self.agent.calls if c[2]["method"] == "message/send"]
        self.assertEqual(len(sends), 1)   # only the Referer case reached the agent


if __name__ == "__main__":
    unittest.main()
