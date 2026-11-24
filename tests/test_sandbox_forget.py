"""Tests of `cn-sandbox forget` and the offer in `cn-sandbox as-me off` (lib/sandbox_forget.sh), with a fake oidc-token
and a fake Workforce (a local HTTP server that records each request).

    python3 -m unittest discover -s tests
"""
import base64
import http.server
import json
import pathlib
import subprocess
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CN_SANDBOX = ROOT / "bin" / "cn-sandbox"
DEV_ID = "dev-demo.tenant-trip-planner"
PATH = f"/workforce/api/instances/{DEV_ID}/forget"


def _jwt(claims):
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{part}.SECRETSIG"


TOKEN = _jwt({"preferred_username": "Demo.Tenant", "sub": "sub-1", "azp": "cn-agent-gateway"})
FAKE_TOKEN = f"""#!/usr/bin/env bash
echo "oidc-token $*" >> "$FAKE_STATE/oidc.log"
printf '%s\\n' '{TOKEN}'
"""


class Workforce(http.server.BaseHTTPRequestHandler):
    """Answers every POST with the server's (status, body) and records path, headers and body."""

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        self.server.calls.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                  "body": json.loads(self.rfile.read(length) or b"null")})
        status, body = self.server.answer
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class ForgetTest(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Workforce)
        self.server.calls, self.server.answer = [], (200, {"instance_id": DEV_ID, "state": "offboarded",
                                                           "forgotten": True})
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home, self.bin, self.state = self.tmp / "home", self.tmp / "bin", self.tmp / "state"
        for d in (self.home, self.bin, self.state):
            d.mkdir()
        write_exe(self.bin / "oidc-token", FAKE_TOKEN)
        write_exe(self.bin / "docker", "#!/usr/bin/env bash\nexit 0\n")
        (self.home / ".codenow").mkdir()
        self.settings(f"CODENOW_AGW_CLIENT_ID=cn-agent-gateway\nCODENOW_WORKFORCE_URL={self.url}/\n")
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_STATE": str(self.state), "CN_SANDBOX_HUB": "off", "NO_PROXY": "*", "no_proxy": "*"}
        self.repo = self.tmp / "agent"
        (self.repo / "agent-config").mkdir(parents=True)
        (self.repo / "agent-config" / "config.yaml").write_text("harness:\n  agent_name: \"Trip Planner\"  # name\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=self.env)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def settings(self, text):
        (self.home / ".codenow" / "config").write_text(text)

    def run_cn(self, *args, answers=None):
        env = dict(self.env)
        if answers is not None:
            env["CN_SETUP_INTERACTIVE"] = "1"
        out = subprocess.run(["bash", str(CN_SANDBOX), *args], cwd=self.repo, env=env, input=answers or "",
                             capture_output=True, text=True, timeout=60)
        self.assertNotIn("SECRETSIG", out.stdout + out.stderr)          # never the token
        self.assertNotIn(TOKEN.split(".")[1], out.stdout + out.stderr)
        return out

    def test_yes_forgets_the_developer_s_instance_with_their_token(self):
        out = self.run_cn("forget", "--yes")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.server.calls, [{"path": PATH, "auth": f"Bearer {TOKEN}", "body": {}}])
        self.assertIn(f"your development instance: {DEV_ID} (--under-development-- Trip Planner, developer Demo.Tenant)",
                      out.stdout)
        self.assertIn(f"Workforce: {self.url}\n", out.stdout)                       # no trailing slash
        self.assertIn("is offboarded in Workforce", out.stdout)

    def test_the_reason_goes_into_the_body(self):
        out = self.run_cn("forget", "--yes", "--reason", "spike done")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.server.calls[0]["body"], {"reason": "spike done"})
        self.run_cn("forget", "-y", "--reason=again")
        self.assertEqual(self.server.calls[1]["body"], {"reason": "again"})

    def test_it_asks_first_and_no_keeps_the_instance(self):
        out = self.run_cn("forget", answers="n\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.server.calls, [])
        self.assertIn("nothing changed", out.stdout)
        out = self.run_cn("forget", answers="y\n")
        self.assertEqual((out.returncode, len(self.server.calls)), (0, 1), out.stderr)

    def test_without_a_terminal_it_needs_yes(self):
        out = self.run_cn("forget")
        self.assertEqual(out.returncode, 1)
        self.assertIn("--yes", out.stderr)
        self.assertEqual(self.server.calls, [])

    def test_a_refusal_shows_the_detail_and_an_unknown_instance_is_nothing_to_forget(self):
        self.server.answer = (403, {"detail": "a developer forgets only their own development instance"})
        out = self.run_cn("forget", "--yes")
        self.assertEqual(out.returncode, 1)
        self.assertIn("refused (403): a developer forgets only their own development instance", out.stderr)
        self.server.answer = (404, {"detail": f"not found: '{DEV_ID}'"})
        out = self.run_cn("forget", "--yes")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("nothing to forget", out.stdout)
        self.server.answer = (200, {"instance_id": DEV_ID, "state": "offboarded", "forgotten": False})
        self.assertIn("offboarded already", self.run_cn("forget", "--yes").stdout)

    def test_the_workforce_url_of_the_env_file_and_none_at_all(self):
        self.settings("CODENOW_AGW_CLIENT_ID=cn-agent-gateway\n")
        (self.repo / ".env").write_text(f"A=1\nWORKFORCE_URL={self.url}\n")
        self.assertEqual(self.run_cn("forget", "--yes").returncode, 0)
        self.assertEqual(self.server.calls[0]["path"], PATH)
        (self.repo / ".env").write_text("A=1\n")
        out = self.run_cn("forget", "--yes")
        self.assertEqual(out.returncode, 1)
        self.assertIn("no Workforce URL", out.stderr)

    def test_the_component_falls_back_to_the_folder_name(self):
        (self.repo / "agent-config" / "config.yaml").write_text("agent_name: {{ componentName }}\n")
        self.assertEqual(self.run_cn("forget", "--yes").returncode, 0)
        self.assertEqual(self.server.calls[0]["path"], "/workforce/api/instances/dev-demo.tenant-agent/forget")

    def test_a_wrong_option_is_a_usage_error(self):
        out = self.run_cn("forget", "--now")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.server.calls, [])

    def test_as_me_off_offers_to_forget(self):
        out = self.run_cn("as-me", "off")                                      # no terminal: no question, no call
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.server.calls, [])
        out = self.run_cn("as-me", "off", answers="n\n")                     # read -p shows the question on a tty
        self.assertEqual((out.returncode, self.server.calls), (0, []), out.stderr)
        out = self.run_cn("as-me", "off", answers="y\n")
        self.assertEqual((out.returncode, [c["path"] for c in self.server.calls]), (0, [PATH]), out.stderr)
        out = self.run_cn("as-me", "off", "--forget")
        self.assertEqual((out.returncode, len(self.server.calls)), (0, 2), out.stderr)
        self.server.answer = (403, {"detail": "no"})
        out = self.run_cn("as-me", "off", "--forget")                          # a refusal never fails as-me off
        self.assertEqual(out.returncode, 0)
        self.assertIn("stays in Workforce", out.stdout)


if __name__ == "__main__":
    unittest.main()
