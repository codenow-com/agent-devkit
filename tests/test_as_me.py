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
echo "sandbox.sh $* file=${CN_IDENTITY_TOKEN_FILE:-}" >> "$FAKE_STATE/sandbox.log"
"""


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
        (self.home / ".codenow").mkdir()
        self.settings(f"CODENOW_AGW_CLIENT_ID={CLIENT}\nCODENOW_WORKFORCE_URL={OBSERVER}\n")
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_STATE": str(self.state), "REAL_PYTHON": real, "CN_SANDBOX_TOKEN_INTERVAL": "30"}
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
        self.assertEqual(self.env_file(), "A=1\n")
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
        self.assertIn("codenow-agent-sdk==2.24.0 or newer", out.stderr)
        self.assertEqual((self.repo / "requirements.txt").read_text(), "codenow-agent-sdk==2.20.0\n")
        self.assertFalse((self.state / "pip.log").exists())

    def test_as_me_needs_off_or_status(self):
        out = self.run_cn("as-me", "bogus")
        self.assertEqual(out.returncode, 2)
        self.assertIn("off or status", out.stderr)


if __name__ == "__main__":
    unittest.main()
