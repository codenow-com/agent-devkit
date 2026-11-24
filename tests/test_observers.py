"""Tests of the Workforce (observer) URL of cn-setup's gateway step (lib/cn_observers.py, gw_workforce_url in
lib/gateway_setup.sh): a fake CodeNOW MCP server on 127.0.0.1 that also answers the observers' /health.

    python3 -m unittest discover -s tests
"""
import http.server
import json
import pathlib
import subprocess
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJuIjoxfQ.SECRETSIG"
DASHBOARD = "https://cn.demo-environment.demo-tenant.example/cd/applications/x"
OBS_A = "https://observer-nov18-observer-test.demo-environment.demo-tenant.example"
OBS_B = "https://watch-team-b.demo-environment.demo-tenant.example"


def agent(agent_id, template):
    return {"id": agent_id, "runtimeId": agent_id, "template": {"id": template}}


class State:
    swarms, agents, deployments, healthy, auth, refuse = [], {}, {}, set(), [], False


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            host = self.headers.get("Host", "")
            if self.headers.get("Authorization"):
                return self._send(400, {})   # the probe never sends credentials
            return self._send(200 if f"https://{host}" in State.healthy else 404, {})
        return self._send(404, {})

    def do_DELETE(self):
        self._send(200, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        State.auth.append(self.headers.get("Authorization", ""))
        if State.refuse:
            return self._send(403, {})
        if body.get("method") != "tools/call":
            return self._send(200, {"jsonrpc": "2.0", "id": body.get("id"), "result": {}})
        name, args = body["params"]["name"], body["params"]["arguments"]
        value = {"agent_swarms_list": lambda: State.swarms,
                 "agents_list": lambda: State.agents.get(args.get("agentSwarmId"), []),
                 "agent_swarm_deployments_list": lambda: State.deployments.get(args.get("agentSwarmId"), [])}[name]()
        self._send(200, {"jsonrpc": "2.0", "id": body["id"],
                         "result": {"content": [{"type": "text", "text": json.dumps(value)}]}})


class ObserverDiscoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.addr = f"127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        State.swarms = [{"id": "observer-test", "runtimeName": "observer-test"}, {"id": "other"}]
        State.agents = {"observer-test": [agent("observer-nov18", "ai-swarm-observer"),
                                          agent("swarm-observer", "ai-swarm-observer"),
                                          agent("helper", "codenow-agent-sdk")],
                        "other": [agent("helper", "codenow-agent-sdk")]}
        State.deployments = {"observer-test": [{"deployment": {"status": "HEALTHY", "dashboardUrl": DASHBOARD}}]}
        State.healthy, State.auth, State.refuse = {OBS_A}, [], False
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home, self.bin = self.tmp / "home", self.tmp / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        (self.bin / "oidc-token").write_text(f"#!/usr/bin/env bash\necho '{TOKEN}'\n")
        (self.bin / "oidc-token").chmod(0o755)
        (self.home / ".codenow").mkdir()
        (self.home / ".codenow" / "config").write_text(f"CODENOW_MCP_URL=http://{self.addr}/mcp\n")
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "CN_PROBE_ADDR": self.addr, "CN_SETUP_INTERACTIVE": "1"}

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def step(self, answers=""):
        script = (f'set -euo pipefail; CN_CMD=cn-setup; . "{ROOT}/lib/common.sh"; . "{ROOT}/lib/sandbox_token.sh"; '
                  f'. "{ROOT}/lib/gateway_setup.sh"; problems=0; note() {{ say "$*"; problems=$((problems+1)); }}; '
                  'load_config; gw_workforce_url')
        out = subprocess.run(["bash", "-c", script], input=answers, capture_output=True, text=True, timeout=60,
                             env=self.env)
        self.assertNotIn("SECRETSIG", out.stdout + out.stderr)
        return out

    def config(self):
        return (self.home / ".codenow" / "config").read_text()

    def test_one_observer_is_offered_as_the_default(self):
        out = self.step("\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(f"found the swarm observer observer-test/observer-nov18: {OBS_A}", out.stdout)
        self.assertIn(f"CODENOW_WORKFORCE_URL={OBS_A}", self.config())
        self.assertTrue(all(a == f"Bearer {TOKEN}" for a in State.auth), "the developer token is sent")

    def test_several_observers_are_listed_and_one_is_picked(self):
        State.swarms.append({"id": "team-b", "runtimeName": "team-b"})
        State.agents["team-b"] = [agent("watch", "ai-swarm-observer")]
        State.deployments["team-b"] = [{"deployment": {"dashboardUrl": DASHBOARD}}]
        State.healthy = {OBS_A, OBS_B}
        out = self.step("2\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("found 2 swarm observers", out.stdout)
        self.assertIn(f"1) {OBS_A}", out.stdout)
        self.assertIn(f"CODENOW_WORKFORCE_URL={OBS_B}", self.config())

    def test_none_found_asks_once_and_enter_skips(self):
        State.healthy = set()      # swarm-observer and observer-nov18 do not answer
        out = self.step("\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("no swarm observer found", out.stdout)
        self.assertIn("does not appear in Workforce", out.stdout)
        self.assertNotIn("CODENOW_WORKFORCE_URL", self.config())

    def test_a_refused_token_falls_back_to_asking(self):
        State.refuse = True
        out = self.step(f"{OBS_A}/\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("lookup with your token failed", out.stderr)
        self.assertIn(f"CODENOW_WORKFORCE_URL={OBS_A}\n", self.config())   # trailing / removed

    def test_a_stored_url_is_kept_without_a_lookup(self):
        (self.home / ".codenow" / "config").write_text(
            f"CODENOW_MCP_URL=http://{self.addr}/mcp\nCODENOW_WORKFORCE_URL={OBS_B}\n")
        out = self.step()
        self.assertIn(OBS_B, out.stdout)
        self.assertEqual(State.auth, [])

    def test_the_url_is_derived_from_the_dashboard_host(self):
        import sys
        sys.path.insert(0, str(ROOT / "lib"))
        import cn_observers
        self.assertEqual(cn_observers.observer_url("observer-nov18", "observer-test",
                                                   "https://cn.demo-environment.demo-tenant.codenow-test.com/cd/x"),
                         "https://observer-nov18-observer-test.demo-environment.demo-tenant.codenow-test.com")
        self.assertEqual(cn_observers.observer_url("a", "b", "not a url"), "")


if __name__ == "__main__":
    unittest.main()
