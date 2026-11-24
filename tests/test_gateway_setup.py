"""Tests of cn-setup's step "Developer identity (agent gateway)" (lib/gateway_setup.sh): fake oidc-agent commands on
PATH and a fake agent gateway, MCP server and metadata endpoint on 127.0.0.1.

    python3 -m unittest discover -s tests
"""
import http.server
import json
import pathlib
import stat
import subprocess
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CN_SETUP = ROOT / "bin" / "cn-setup"
ISSUER = "https://iam.example/auth/realms/codenow"
CLIENT = "demo-tenant-demo-environment-agent-gateway"
PASSWORD = "local-secret-pw"

FAKES = {
    "oidc-agent": 'echo "oidc-agent ${FAKE_VERSION:-5.3.6}"\n',
    "oidc-agent-service": 'case "$1" in use) echo "OIDC_SOCK=$FAKE_STATE/sock; export OIDC_SOCK;" ;; '
                          'restart) echo restart >> "$FAKE_STATE/service.log" ;; esac\n',
    "oidc-add": '[ "$1" = -l ] && { echo "The following account configurations are usable:"; '
                'cat "$FAKE_STATE/accounts" 2>/dev/null; }; exit 0\n',
    "oidc-gen": 'echo "$*" > "$FAKE_STATE/gen.args"\n'
                '[ -n "$OIDC_ENCRYPTION_PW" ] && echo "pw:$OIDC_ENCRYPTION_PW" > "$FAKE_STATE/gen.pw"\n'
                'echo "Using a browser on any device, visit: https://iam.example/device and enter the code: ABCD-EFGH"\n'
                'echo "$1" >> "$FAKE_STATE/accounts"\n',
    "oidc-token": 'acct="${@: -1}"; grep -qx "$acct" "$FAKE_STATE/accounts" 2>/dev/null || '
                  '{ echo "account not loaded" >&2; exit 1; }\n'
                  'python3 -c \'import base64, json, os\n'
                  'b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")\n'
                  'c = {"aud": os.environ["FAKE_AUD"], "azp": os.environ.get("FAKE_AZP", "' + CLIENT + '"),\n'
                  '     "iss": "' + ISSUER + '",\n'
                  '     "preferred_username": "demotenant"}\n'
                  'print(b({"alg": "RS256"}) + "." + b(c) + ".SECRETSIG")\'\n',
    "brew": 'echo "brew $*" >> "$FAKE_STATE/brew.log"\n',
}


class Fake(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        return self.headers.get("Authorization", "").endswith(".SECRETSIG")

    def do_GET(self):
        if self.path == "/.well-known/oauth-protected-resource":
            return self._send(200, {"authorization_servers": [ISSUER]})
        if self.path == "/v1/models":
            if not self._authorized():
                return self._send(401, {})
            return self._send(200, {"data": [{"id": "claude-x"}, {"id": "gpt-y"}]})
        return self._send(404, {})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/mcp":
            return self._send(200 if self._authorized() else 401, {"jsonrpc": "2.0", "id": 1, "result": {}})
        return self._send(404, {})


class GatewayStepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home, self.bin, self.state = self.tmp / "home", self.tmp / "bin", self.tmp / "state"
        for d in (self.home, self.bin, self.state):
            d.mkdir()
        for name, body in FAKES.items():
            (self.bin / name).write_text("#!/usr/bin/env bash\n" + body)
            (self.bin / name).chmod(0o755)
        (self.home / ".codenow").mkdir()
        (self.home / ".codenow" / "config").write_text(f"CODENOW_MCP_URL={self.base}/mcp\n")
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", "SHELL": "/bin/zsh",
                    "FAKE_STATE": str(self.state), "FAKE_AUD": self.base}

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def run_setup(self, *args, answers=None, **env):
        full = {**self.env, **env}
        if answers is not None:
            full["CN_SETUP_INTERACTIVE"] = "1"
        return subprocess.run(["bash", str(CN_SETUP), *args], input=answers or "", capture_output=True, text=True,
                              timeout=60, env=full)

    def config(self):
        return (self.home / ".codenow" / "config").read_text()

    def first_run(self):
        # issuer: Enter takes the one from the metadata; client id (no tenant in a 127.0.0.1 MCP URL); profile y;
        # PKCE y; account y; password. The gateway URL is never asked: it comes from the token's audience.
        return self.run_setup("--only-gateway", answers=f"\n{CLIENT}\ny\ny\ny\n{PASSWORD}\n")

    def test_the_first_run_sets_everything_up_and_checks_it(self):
        out = self.first_run()
        text = out.stdout + out.stderr
        self.assertEqual(out.returncode, 0, text)
        config = self.config()
        for line in (f"CODENOW_IAM_ISSUER={ISSUER}", f"CODENOW_AGW_CLIENT_ID={CLIENT}", f"CODENOW_AGW_URL={self.base}",
                     "CN_OIDC_ACCOUNT=cn-agw"):
            self.assertIn(line, config)
        self.assertEqual((self.home / ".zshrc").read_text().count("oidc-agent-service use"), 1)
        pkce = self.home / ".config" / "oidc-agent" / "custom_parameters.config"
        entries = json.loads(pkce.read_text())
        self.assertEqual({e["parameter"] for e in entries}, {"code_challenge", "code_challenge_method", "code_verifier"})
        self.assertTrue(all(e["for_account"] == ["cn-agw"] for e in entries))
        self.assertEqual(stat.S_IMODE(pkce.stat().st_mode), 0o600)
        args = (self.state / "gen.args").read_text()
        for part in ("cn-agw", f"--iss={ISSUER}", f"--client-id={CLIENT}", "--flow=device", "--pw-env"):
            self.assertIn(part, args)
        self.assertNotIn(PASSWORD, args)
        self.assertEqual((self.state / "gen.pw").read_text().strip(), f"pw:{PASSWORD}")
        self.assertIn("models claude-x, gpt-y", text)
        self.assertIn("initialize with your token: ok", text)
        self.assertIn("token of demotenant", text)
        self.assertIn("developer identity: all good", text)
        self.assertNotIn("SECRETSIG", text)
        self.assertNotIn(PASSWORD, text)

    def test_a_second_run_changes_nothing_and_asks_nothing(self):
        self.first_run()
        before = (self.home / ".config" / "oidc-agent" / "custom_parameters.config").read_text()
        out = self.run_setup("--only-gateway")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual((self.home / ".zshrc").read_text().count("oidc-agent-service use"), 1)
        self.assertEqual((self.home / ".config" / "oidc-agent" / "custom_parameters.config").read_text(), before)
        self.assertIn("oidc-agent account cn-agw: ok", out.stdout)

    def test_the_doctor_reports_the_values_and_the_check(self):
        self.first_run()
        out = self.run_setup("--check", "--only-gateway")
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn(f"client {CLIENT}", out.stdout)
        self.assertIn("models claude-x, gpt-y", out.stdout)
        bad = self.run_setup("--check", "--only-gateway", FAKE_AUD="https://other.example")
        self.assertEqual(bad.returncode, 1)
        self.assertIn("lacks the gateway", bad.stdout)

    def test_an_existing_account_gives_the_values_without_questions(self):
        # Petr's case: the account cn-agw was made by hand (README), cn-setup has no gateway values yet.
        (self.state / "accounts").write_text("cn-agw\n")
        pkce_dir = self.home / ".config" / "oidc-agent"
        pkce_dir.mkdir(parents=True)
        (pkce_dir / "custom_parameters.config").write_text(json.dumps([
            {"parameter": p, "value": "x", "for_account": ["cn-agw"], "request": ["device-init"]}
            for p in ("code_challenge", "code_challenge_method", "code_verifier")]))
        (self.home / ".zshrc").write_text('eval "$(oidc-agent-service use)" > /dev/null\n')
        out = self.run_setup("--only-gateway", answers="")
        text = out.stdout + out.stderr
        self.assertEqual(out.returncode, 0, text)
        self.assertIn("values from your oidc-agent account cn-agw", text)
        self.assertNotIn("environment of your agent gateway", text)
        config = self.config()
        for line in (f"CODENOW_IAM_ISSUER={ISSUER}", f"CODENOW_AGW_CLIENT_ID={CLIENT}", f"CODENOW_AGW_URL={self.base}"):
            self.assertIn(line, config)
        self.assertIn("developer identity: all good", text)
        self.assertNotIn("SECRETSIG", text)

    def test_without_a_terminal_and_without_values_it_says_what_is_missing(self):
        out = self.run_setup("--only-gateway")
        self.assertEqual(out.returncode, 1)
        self.assertIn("missing CODENOW_AGW_CLIENT_ID", out.stdout)

    def test_answering_no_changes_no_file(self):
        out = self.run_setup("--only-gateway", answers=f"\n{CLIENT}\nn\nn\n")
        self.assertEqual(out.returncode, 1)
        self.assertFalse((self.home / ".zshrc").exists())
        self.assertFalse((self.home / ".config" / "oidc-agent").exists())
        self.assertFalse((self.state / "gen.args").exists())

    def test_pkce_entries_of_other_accounts_stay(self):
        pkce = self.home / ".config" / "oidc-agent" / "custom_parameters.config"
        pkce.parent.mkdir(parents=True)
        pkce.write_text(json.dumps([{"parameter": "x", "value": "1", "for_account": ["other"], "request": ["refresh"]}]))
        self.first_run()
        entries = json.loads(pkce.read_text())
        self.assertIn({"parameter": "x", "value": "1", "for_account": ["other"], "request": ["refresh"]}, entries)
        self.assertEqual(len(entries), 4)

    def test_an_old_oidc_agent_stops_the_step(self):
        out = self.run_setup("--only-gateway", answers=f"\n{CLIENT}\n", FAKE_VERSION="5.1.0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("older than 5.2.0", out.stdout)

    def test_a_missing_oidc_agent_is_installed_only_with_consent_on_macos(self):
        (self.bin / "oidc-agent").unlink()
        out = self.run_setup("--only-gateway", answers=f"\n{CLIENT}\nn\n")
        self.assertIn("oidc-agent is missing", out.stdout)
        self.assertFalse((self.state / "brew.log").exists())

    def test_the_tenant_comes_from_the_mcp_url_and_options_are_checked(self):
        script = (f'. "{ROOT}/lib/common.sh"; . "{ROOT}/lib/sandbox_token.sh"; . "{ROOT}/lib/gateway_setup.sh"; '
                  'CODENOW_MCP_URL=https://mcp-server-demo-tenant.stxcn.codenow.com/mcp gw_tenant')
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout, "demo-tenant")
        self.assertNotEqual(self.run_setup("--bogus").returncode, 0)

    def test_the_environment_is_typed_once_and_gives_the_client(self):
        # Petr's report: environment, client and URL were three prompts with "demo-environment" typed three times.
        script = (f'. "{ROOT}/lib/common.sh"; . "{ROOT}/lib/sandbox_token.sh"; . "{ROOT}/lib/gateway_setup.sh"; '
                  'CODENOW_MCP_URL=https://mcp-server-demo-tenant.stxcn.codenow.com/mcp; '
                  f'CODENOW_IAM_ISSUER={ISSUER}; gw_values')
        out = subprocess.run(["bash", "-c", script], input="demo-environment\n", capture_output=True, text=True,
                             timeout=30, env={**self.env, "CN_SETUP_INTERACTIVE": "1"})
        text = out.stdout + out.stderr
        self.assertEqual(out.returncode, 0, text)
        # (read -p shows its prompt only on a terminal; one answer line was enough for the whole step)
        self.assertNotIn("Keycloak client of the agent gateway (e.g.", text)   # not asked: derived
        self.assertNotIn("agent gateway URL (", text)                          # not asked: from the token later
        self.assertIn("Keycloak client of the agent gateway: demo-tenant-demo-environment-agent-gateway", text)
        self.assertIn("CODENOW_AGW_CLIENT_ID=demo-tenant-demo-environment-agent-gateway", self.config())


if __name__ == "__main__":
    unittest.main()
