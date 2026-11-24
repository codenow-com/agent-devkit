"""Tests of `cn-sandbox up --as-me` and `cn-sandbox as-me off|status` (lib/as_me.sh), with a fake oidc-token,
a fake pip and a stub sandbox.sh.

    python3 -m unittest discover -s tests
"""
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CN_SANDBOX = ROOT / "bin" / "cn-sandbox"
BEGIN = "# >>> cn-devkit: developer identity (cn-sandbox as-me off removes it)"
END = "# <<< cn-devkit"
CLIENT = "demo-tenant-demo-environment-agent-gateway"
OBSERVER = "https://observer-nov18-observer-test.example"

FAKE_TOKEN = """#!/usr/bin/env bash
[ -z "${FAKE_OIDC_FAIL:-}" ] || exit 1
printf 'eyJhbGciOiJSUzI1NiJ9.eyJuIjoxfQ.SECRETSIG\\n'
"""
# python3 -m pip index versions ...: the fake pip is a python3 wrapper that answers only `-m pip`.
FAKE_PYTHON = """#!/usr/bin/env bash
if [ "$1" = -m ] && [ "$2" = pip ]; then
  echo "pip $*" >> "$FAKE_STATE/pip.log"
  [ "$3" = index ] && { echo "codenow-agent-sdk (2.25.1)"; echo "Available versions: 2.25.1, 2.24.0, 2.23.3"; }
  exit 0
fi
exec "$REAL_PYTHON" "$@"
"""
SANDBOX_STUB = """#!/usr/bin/env bash
echo "sandbox.sh $* file=${CN_IDENTITY_TOKEN_FILE:-} agw=${CODENOW_AGW_URL:-} iam=${CODENOW_IAM_ISSUER:-}" \\
  >> "$FAKE_STATE/sandbox.log"
"""
# docker ps -q --filter label=...project=<p> --filter label=...service=agent: the id when $FAKE_STATE/agent.log exists
# and the project is the one of the repository "agent"; docker logs <id>: that log.
FAKE_DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_STATE/docker.log"
case "$1" in
  ps) [ -f "$FAKE_STATE/agent.log" ] && case "$*" in
        *com.docker.compose.project=sandbox-agent\\ *com.docker.compose.service=agent*) echo c0ffee ;; esac
      exit 0 ;;
  logs) [ "$2" = c0ffee ] && cat "$FAKE_STATE/agent.log"; exit 0 ;;
esac
exit 0
"""
DEV_LOG = """INFO codenow_agent_sdk.agent.identity_provider: identity: adapter developer
INFO codenow_agent_sdk.workforce.onboarding: Workforce: onboarding pending (instance -, mode shadow)
INFO codenow_agent_sdk.workforce.onboarding: Workforce: onboarding approved (instance dev-a1b2, mode shadow)
INFO token eyJhbGciOiJSUzI1NiJ9.eyJuIjoxfQ.SECRETSIG
"""
OFF = "# cn-devkit: identity=deployment (cn-sandbox as-me on runs the agent as you again)"
LEGACY_LOG = "INFO codenow_agent_sdk.agent.identity_provider: identity: adapter legacy-refresh-token\n"


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class AsMeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home, self.bin, self.state = self.tmp / "home", self.tmp / "bin", self.tmp / "state"
        for d in (self.home, self.bin, self.state):
            d.mkdir()
        write_exe(self.bin / "oidc-token", FAKE_TOKEN)
        real = subprocess.run(["bash", "-c", "command -v python3"], capture_output=True, text=True).stdout.strip()
        write_exe(self.bin / "python3", FAKE_PYTHON)
        write_exe(self.bin / "docker", FAKE_DOCKER)
        (self.home / ".codenow").mkdir()
        self.settings(f"CODENOW_AGW_CLIENT_ID={CLIENT}\nCODENOW_WORKFORCE_URL={OBSERVER}\n"
                      "CODENOW_MCP_URL=https://mcp-server-demotenant.example.com/mcp\n")
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_STATE": str(self.state), "REAL_PYTHON": real, "CN_SANDBOX_TOKEN_INTERVAL": "30",
                    "CN_SANDBOX_HUB": "off"}
        self.repo = self.tmp / "agent"
        (self.repo / "sandbox").mkdir(parents=True)
        write_exe(self.repo / "sandbox" / "sandbox.sh", SANDBOX_STUB)
        (self.repo / "requirements.txt").write_text("langchain==1.0\ncodenow-agent-sdk==2.24.0\nhttpx==0.28\n")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=self.env)

    def tearDown(self):
        self.run_cn("token", "--stop")
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def settings(self, text):
        (self.home / ".codenow" / "config").write_text(text)

    def env_file(self, text=None):
        path = self.repo / ".env"
        if text is not None:
            path.write_text(text)
        return path.read_text() if path.exists() else ""

    def run_cn(self, *args, answers=None):
        env = dict(self.env)
        if answers is not None:
            env["CN_SETUP_INTERACTIVE"] = "1"
        return subprocess.run(["bash", str(CN_SANDBOX), *args], cwd=self.repo, env=env, input=answers or "",
                              capture_output=True, text=True, timeout=60)

    def block(self, *lines):
        return "\n".join([BEGIN, *lines, END]) + "\n"

    def test_up_as_me_writes_the_block_keeps_other_lines_and_starts_the_sandbox(self):
        self.env_file("# mine\nOPENAI_KEY=x\n")
        out = self.run_cn("up", "--as-me")
        text = out.stdout + out.stderr
        self.assertEqual(out.returncode, 0, text)
        expected = "# mine\nOPENAI_KEY=x\n\n" + self.block(
            "CN_IDENTITY_PROVIDER=developer", f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}",
            f"WORKFORCE_URL={OBSERVER}", "WORKFORCE_MODE=shadow")
        self.assertEqual(self.env_file(), expected)
        log = (self.state / "sandbox.log").read_text()
        self.assertIn("sandbox.sh up file=", log)          # --as-me is not passed on
        self.assertNotIn("--as-me", log)
        self.assertIn("--under-development--", text)
        self.assertNotIn("SECRETSIG", text)

    def test_a_second_run_refreshes_the_block_in_place(self):
        self.env_file("A=1\n" + self.block("CN_IDENTITY_PROVIDER=developer", "CN_IDENTITY_DEVELOPER_CLIENTS=old")
                      + "B=2\n")
        self.assertEqual(self.run_cn("up", "--as-me").returncode, 0)
        text = self.env_file()
        self.assertTrue(text.startswith("A=1\n" + BEGIN))
        self.assertTrue(text.endswith(END + "\nB=2\n"))
        self.assertIn(f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}", text)
        self.assertNotIn("=old", text)
        self.assertEqual(text.count(BEGIN), 1)

    def test_off_removes_only_the_block_and_status_shows_it(self):
        self.env_file("A=1\n")
        self.run_cn("up", "--as-me")
        status = self.run_cn("as-me", "status")
        self.assertIn(f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}", status.stdout)
        self.assertIn(f"Workforce {OBSERVER}", status.stdout)
        out = self.run_cn("as-me", "off")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("block removed", out.stdout)
        self.assertEqual(self.env_file(), f"A=1\n{OFF}\n")   # the block is gone; `off` is remembered
        self.assertIn("no developer identity block", self.run_cn("as-me", "status").stdout)
        self.assertIn("has no developer identity block", self.run_cn("as-me", "off").stdout)

    def test_a_foreign_line_with_another_value_stops_and_names_the_line(self):
        self.env_file("A=1\nCN_IDENTITY_DEVELOPER_CLIENTS=someone-else\nWORKFORCE_MODE=shadow\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertIn("line 2: CN_IDENTITY_DEVELOPER_CLIENTS=someone-else", out.stderr)
        self.assertNotIn("line 3", out.stderr)                 # the same value is no conflict
        self.assertNotIn(BEGIN, self.env_file())
        self.assertFalse((self.state / "sandbox.log").exists())

    def test_an_empty_line_of_a_block_key_is_removed_and_named(self):
        self.env_file("A=1\nWORKFORCE_URL=\nexport CN_IDENTITY_PROVIDER=  \nWORKFORCE_MODE=shadow\nB=2\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("removed line 2: WORKFORCE_URL=", out.stdout)
        self.assertIn("removed line 3: export CN_IDENTITY_PROVIDER=", out.stdout)
        self.assertNotIn("removed line 4", out.stdout)          # a same, non-empty value stays
        expected = "A=1\nWORKFORCE_MODE=shadow\nB=2\n\n" + self.block(
            "CN_IDENTITY_PROVIDER=developer", f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}",
            f"WORKFORCE_URL={OBSERVER}", "WORKFORCE_MODE=shadow")
        self.assertEqual(self.env_file(), expected)
        self.assertIn("sandbox.sh up file=", (self.state / "sandbox.log").read_text())

    def test_an_empty_line_after_an_existing_block_is_removed_too(self):
        self.env_file(self.block("CN_IDENTITY_PROVIDER=developer", f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}")
                      + "WORKFORCE_URL=\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("removed line 5: WORKFORCE_URL=", out.stdout)
        self.assertTrue(self.env_file().endswith(END + "\n"))

    def test_an_empty_line_and_a_conflict_stop_without_a_change(self):
        original = "WORKFORCE_URL=\nWORKFORCE_MODE=enforce\n"
        self.env_file(original)
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertIn("line 2: WORKFORCE_MODE=enforce", out.stderr)
        self.assertNotIn("line 1", out.stderr)
        self.assertEqual(self.env_file(), original)

    def test_plain_up_with_the_block_keeps_developer_mode(self):
        self.env_file("A=1\n")
        self.assertEqual(self.run_cn("up", "--as-me").returncode, 0)
        self.assertEqual(self.run_cn("down").returncode, 0)
        (self.state / "sandbox.log").unlink()
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stderr)
        log = (self.state / "sandbox.log").read_text()
        self.assertIn("sandbox.sh up file=", log)
        self.assertNotIn("file= ", log)                     # the token file is passed: developer mode

    def test_up_as_me_after_a_deployment_token_up_and_down(self):
        self.env_file("A=1\nWORKFORCE_URL=\n")
        out = self.run_cn("up", "--deployment-token")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("sandbox.sh up file= ", (self.state / "sandbox.log").read_text())   # deployment token
        self.assertEqual(self.run_cn("down").returncode, 0)
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(BEGIN, self.env_file())
        self.assertNotIn("\nWORKFORCE_URL=\n", self.env_file())

    def test_up_prints_the_console_on_localhost(self):
        (self.repo / "sandbox" / ".run").mkdir()
        (self.repo / "sandbox" / ".run" / "port").write_text("8083\n")
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("console: http://localhost:8083/", out.stdout)
        self.assertNotIn("http://127.0.0.1", out.stdout)

    def test_status_developer(self):
        self.env_file("A=1\n")
        self.run_cn("up", "--as-me")
        (self.state / "agent.log").write_text(DEV_LOG)
        out = self.run_cn("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"cn-sandbox: identity: developer (demotenant, client {CLIENT})\n", out.stdout)
        self.assertIn("cn-sandbox: Workforce: onboarding approved (instance dev-a1b2, mode shadow)\n", out.stdout)
        self.assertIn("console: http://localhost:8080/", out.stdout)
        self.assertNotIn("SECRETSIG", out.stdout + out.stderr)
        self.assertNotIn("eyJ", out.stdout + out.stderr)
        self.assertTrue((self.state / "sandbox.log").read_text().splitlines()[-1].startswith("sandbox.sh status"))

    def test_up_as_me_passes_the_gateway_and_iam_for_the_pre_deploy_sandbox(self):
        self.settings(f"CODENOW_AGW_CLIENT_ID={CLIENT}\nCODENOW_WORKFORCE_URL={OBSERVER}\n"
                      "CODENOW_AGW_URL=https://agent-gateway.example\n"
                      "CODENOW_IAM_ISSUER=https://iam.example/auth/realms/codenow\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("agw=https://agent-gateway.example iam=https://iam.example/auth/realms/codenow",
                      (self.state / "sandbox.log").read_text())

    def test_the_deployment_token_passes_no_gateway(self):
        self.settings(f"CODENOW_AGW_CLIENT_ID={CLIENT}\nCODENOW_AGW_URL=https://agent-gateway.example\n")
        out = self.run_cn("up", "--deployment-token")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("agw= iam=", (self.state / "sandbox.log").read_text())

    def test_status_names_the_local_console_login_before_the_first_deployment(self):
        self.env_file("A=1\n")
        self.run_cn("up", "--as-me")
        (self.state / "agent.log").write_text(DEV_LOG)
        (self.repo / "sandbox" / ".run" / "predeploy").write_text("user=demotenant\n")
        out = self.run_cn("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("cn-sandbox: console login: local dev IdP (not deployed yet)\n", out.stdout)
        (self.repo / "sandbox" / ".run" / "predeploy").unlink()
        out = self.run_cn("status")
        self.assertIn("cn-sandbox: console login: agent's own client\n", out.stdout)

    def test_status_deployment_token(self):
        (self.state / "agent.log").write_text(LEGACY_LOG)
        out = self.run_cn("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("identity: deployment token (legacy-refresh-token); run cn-sandbox up --as-me to run as "
                      "yourself", out.stdout)
        self.assertNotIn("Workforce:", out.stdout)

    def test_status_agent_not_running(self):
        out = self.run_cn("status")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("cn-sandbox: identity: unknown (agent not running)\n", out.stdout)
        self.assertIn("sandbox.sh status", (self.state / "sandbox.log").read_text())

    def test_status_a_refusal_is_shown(self):
        (self.state / "agent.log").write_text(
            "identity: adapter developer\nWARNING x: Workforce: onboarding refused (instance -, mode shadow)\n")
        out = self.run_cn("status")
        self.assertIn("cn-sandbox: Workforce: onboarding refused (instance -, mode shadow)\n", out.stdout)

    def test_a_missing_client_says_run_cn_setup(self):
        self.settings(f"CODENOW_WORKFORCE_URL={OBSERVER}\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertIn("cn-setup --only-gateway", out.stderr)
        self.assertFalse((self.repo / ".env").exists())

    def test_a_missing_workforce_url_leaves_the_workforce_lines_out(self):
        self.settings(f"CODENOW_AGW_CLIENT_ID={CLIENT}\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.env_file(), self.block("CN_IDENTITY_PROVIDER=developer",
                                                     f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}"))
        self.assertIn("will not appear in Workforce", out.stdout)
        self.assertIn("cn-setup --only-gateway", out.stdout)

    def test_an_old_sdk_pin_asks_and_consent_edits_only_that_line(self):
        (self.repo / "requirements.txt").write_text("langchain==1.0\ncodenow-agent-sdk==2.23.3\nhttpx==0.28\n")
        out = self.run_cn("up", "--as-me", answers="y\n")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("2.23.3 is too old", out.stdout)
        self.assertEqual((self.repo / "requirements.txt").read_text(),
                         "langchain==1.0\ncodenow-agent-sdk==2.25.1\nhttpx==0.28\n")
        self.assertIn("commit it", out.stdout)

    def test_an_old_sdk_pin_without_consent_changes_nothing(self):
        (self.repo / "requirements.txt").write_text("codenow-agent-sdk==2.23.3\n")
        out = self.run_cn("up", "--as-me", answers="n\n")
        self.assertEqual(out.returncode, 1)
        self.assertEqual((self.repo / "requirements.txt").read_text(), "codenow-agent-sdk==2.23.3\n")
        self.assertFalse((self.repo / ".env").exists())

    def test_an_old_sdk_pin_without_a_terminal_stops_with_the_hint(self):
        (self.repo / "requirements.txt").write_text("codenow-agent-sdk==2.20.0\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertIn("pins codenow-agent-sdk 2.20.0, older than 2.24.0", out.stderr)
        self.assertEqual((self.repo / "requirements.txt").read_text(), "codenow-agent-sdk==2.20.0\n")
        self.assertFalse((self.state / "pip.log").exists())

    def mode(self):
        return (self.repo / "sandbox" / ".run" / "identity-mode").read_text().strip()

    def last_up(self):
        return (self.state / "sandbox.log").read_text().splitlines()[-1]

    def test_plain_up_runs_as_you_by_default_when_the_identity_is_ready(self):
        self.env_file("A=1\n")
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(BEGIN, self.env_file())
        self.assertNotIn("sandbox.sh up file= ", self.last_up())   # the token file is passed: developer mode
        self.assertEqual(self.mode(), "as you (default)")

    def test_without_a_client_plain_up_says_why_and_uses_the_deployment_token(self):
        self.settings(f"CODENOW_WORKFORCE_URL={OBSERVER}\n")
        self.env_file("A=1\n")
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("identity: deployment token: your own identity is not ready: no agent gateway client is set "
                      "(CODENOW_AGW_CLIENT_ID); fix: cn-setup --only-gateway", out.stdout)
        self.assertNotIn(BEGIN, self.env_file())
        self.assertIn("sandbox.sh up file= ", self.last_up())
        self.assertEqual(self.mode(), "deployment token (identity not ready: no agent gateway client is set "
                                      "(CODENOW_AGW_CLIENT_ID))")

    def test_a_failing_oidc_token_falls_back_with_the_reason_and_removes_a_stale_block(self):
        self.env_file("A=1\n" + self.block("CN_IDENTITY_PROVIDER=developer", f"CN_IDENTITY_DEVELOPER_CLIENTS={CLIENT}"))
        self.env["FAKE_OIDC_FAIL"] = "1"
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("not ready: oidc-token cn-agw gave no token; fix: oidc-add cn-agw", out.stdout)
        self.assertNotIn(BEGIN, self.env_file())
        self.assertIn("sandbox.sh up file= ", self.last_up())

    def test_as_me_without_a_ready_identity_stops(self):
        self.settings("")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertIn("cannot run as you: no agent gateway client", out.stderr)

    def test_as_me_off_is_remembered_until_as_me_on(self):
        self.env_file("A=1\n")
        self.run_cn("up")
        self.assertEqual(self.run_cn("as-me", "off").returncode, 0)
        for _ in range(2):   # every later plain up keeps the deployment token
            out = self.run_cn("up")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("identity: deployment token (as-me off); cn-sandbox as-me on runs the agent as you again",
                          out.stdout)
            self.assertIn("sandbox.sh up file= ", self.last_up())
            self.assertEqual(self.mode(), "deployment token (as-me off)")
        self.assertIn("as-me off: cn-sandbox up uses the deployment token", self.run_cn("as-me", "status").stdout)
        out = self.run_cn("as-me", "on")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(OFF, self.env_file())
        self.assertIn(BEGIN, self.env_file())
        self.run_cn("up")
        self.assertNotIn("sandbox.sh up file= ", self.last_up())
        self.assertEqual(self.mode(), "as you (default)")

    def test_up_as_me_clears_as_me_off(self):
        self.env_file("A=1\n")
        self.run_cn("as-me", "off")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(OFF, self.env_file())
        self.assertEqual(self.mode(), "as you (--as-me)")
        self.run_cn("up")
        self.assertEqual(self.mode(), "as you (default)")

    def test_deployment_token_is_for_one_run_only(self):
        self.env_file("A=1\n")
        self.run_cn("up")
        out = self.run_cn("up", "--deployment-token")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("the next cn-sandbox up runs as you again", out.stdout)
        self.assertIn("sandbox.sh up file= ", self.last_up())
        self.assertEqual(self.mode(), "deployment token (this run: --deployment-token)")
        self.assertNotIn(OFF, self.env_file())
        self.run_cn("up")
        self.assertNotIn("sandbox.sh up file= ", self.last_up())
        self.assertIn(BEGIN, self.env_file())

    def test_status_shows_the_mode_and_its_source(self):
        self.env_file("A=1\n")
        self.run_cn("up")
        (self.state / "agent.log").write_text(DEV_LOG)
        self.assertIn("cn-sandbox: mode: as you (default)\n", self.run_cn("status").stdout)
        self.run_cn("as-me", "off")
        self.run_cn("up")
        (self.state / "agent.log").write_text(LEGACY_LOG)
        self.assertIn("cn-sandbox: mode: deployment token (as-me off)\n", self.run_cn("status").stdout)

    def test_plain_up_of_an_adk_agent_runs_as_you_without_the_sdk_pin_check(self):
        (self.repo / "requirements.txt").write_text("google-adk[a2a]==2.14.1\n")
        self.env_file("A=1\n")
        out = self.run_cn("up")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ADK agent: SDK pin check not needed", out.stdout)
        self.assertIn(BEGIN, self.env_file())
        self.assertEqual(self.mode(), "as you (default)")

    def test_an_adk_agent_skips_the_sdk_pin_check(self):
        (self.repo / "requirements.txt").write_text("google-adk[a2a]==2.14.1\na2a-sdk[http-server]==1.3.1\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("ADK agent: SDK pin check not needed", out.stdout)
        self.assertNotIn("has no codenow-agent-sdk", out.stdout)
        self.assertFalse((self.state / "pip.log").exists())
        self.assertIn("CN_IDENTITY_PROVIDER=developer", self.env_file())
        self.assertIn("sandbox.sh up", (self.state / "sandbox.log").read_text())

    def test_an_adk_agent_that_also_pins_the_sdk_is_checked(self):
        (self.repo / "requirements.txt").write_text("google-adk==2.14.1\ncodenow-agent-sdk==2.20.0\n")
        out = self.run_cn("up", "--as-me")
        self.assertEqual(out.returncode, 1)
        self.assertNotIn("ADK agent", out.stdout + out.stderr)
        self.assertIn("pins codenow-agent-sdk 2.20.0, older than 2.24.0", out.stderr)

    def test_as_me_needs_off_or_status(self):
        out = self.run_cn("as-me", "bogus")
        self.assertEqual(out.returncode, 2)
        self.assertIn("off, on or status", out.stderr)


if __name__ == "__main__":
    unittest.main()
