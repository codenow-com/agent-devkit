"""Tests of `cn-sandbox token` and the oidc-agent check of cn-doctor (lib/sandbox_token.sh), with a fake oidc-agent.

    python3 -m unittest discover -s tests
"""
import os
import pathlib
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CN_SANDBOX = ROOT / "bin" / "cn-sandbox"

FAKE_TOKEN = """#!/usr/bin/env bash
# fake oidc-token: a new JWT-shaped token per call; FAKE_FAIL=1 fails like an account that is not loaded
[ "${FAKE_FAIL:-}" = 1 ] && { echo "account not loaded" >&2; exit 1; }
n=$(( $(cat "$FAKE_STATE/count" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE_STATE/count"
echo "$*" > "$FAKE_STATE/args"
printf 'eyJhbGciOiJSUzI1NiJ9.eyJuIjo%sfQ.sig%s\\n' "$n" "$n"
"""
FAKE_AGENT = """#!/usr/bin/env bash
echo "oidc-agent ${FAKE_VERSION:-5.2.3}"
"""
SANDBOX_STUB = """#!/usr/bin/env bash
echo "sandbox.sh $* file=${CN_IDENTITY_TOKEN_FILE:-}" >> "$FAKE_STATE/sandbox.log"
"""


def write_exe(path: pathlib.Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        for d in (self.home, self.bin, self.state):
            d.mkdir()
        write_exe(self.bin / "oidc-token", FAKE_TOKEN)
        write_exe(self.bin / "oidc-agent", FAKE_AGENT)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "FAKE_STATE": str(self.state), "CN_SANDBOX_TOKEN_INTERVAL": "1"}
        self.token = self.home / ".codenow" / "sandbox-token" / "token"

    def tearDown(self):
        self.run_cn("token", "--stop", cwd=self.home)
        subprocess.run(["rm", "-rf", str(self.tmp)], check=False)

    def run_cn(self, *args, cwd=None, **env):
        return subprocess.run(["bash", str(CN_SANDBOX), *args], cwd=cwd or self.home, env={**self.env, **env},
                              capture_output=True, text=True, timeout=30)

    def repo(self, env_text: str) -> pathlib.Path:
        repo = self.tmp / "agent"
        (repo / "sandbox").mkdir(parents=True)
        write_exe(repo / "sandbox" / "sandbox.sh", SANDBOX_STUB)
        (repo / ".env").write_text(env_text)
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=self.env)
        return repo

    def test_token_once_is_written_private_and_never_printed(self):
        out = self.run_cn("token")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.token.read_text().startswith("eyJ"))
        self.assertEqual(stat.S_IMODE(self.token.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.token.parent.stat().st_mode), 0o700)
        self.assertNotIn("eyJ", out.stdout + out.stderr)
        self.assertEqual((self.state / "args").read_text().split(), ["--time=120", "cn-agw"])

    def test_account_and_file_are_configurable(self):
        target = self.tmp / "tok" / "t"
        out = self.run_cn("token", CN_OIDC_ACCOUNT="mine", CN_IDENTITY_TOKEN_FILE=str(target))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(target.exists())
        self.assertIn("mine", (self.state / "args").read_text())

    def test_a_failing_oidc_token_writes_nothing(self):
        out = self.run_cn("token", FAKE_FAIL="1")
        self.assertEqual(out.returncode, 1)
        self.assertIn("oidc-add cn-agw", out.stdout + out.stderr)
        self.assertFalse(self.token.exists())

    def test_a_token_file_in_a_repository_or_home_is_refused(self):
        repo = self.repo("")
        out = self.run_cn("token", CN_IDENTITY_TOKEN_FILE=str(repo / "sub" / "token"))
        self.assertNotEqual(out.returncode, 0)
        (repo / "sub").mkdir()
        out = self.run_cn("token", CN_IDENTITY_TOKEN_FILE=str(repo / "sub" / "token"))
        self.assertIn("git repository", out.stderr)
        out = self.run_cn("token", CN_IDENTITY_TOKEN_FILE=str(self.home / "token"))
        self.assertIn("its own folder", out.stderr)

    def test_up_in_developer_mode_starts_the_refresh_and_down_stops_it(self):
        repo = self.repo("CN_IDENTITY_PROVIDER=developer\n")
        out = self.run_cn("up", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        log = (self.state / "sandbox.log").read_text()
        self.assertIn(f"sandbox.sh up file={self.token}", log)
        pid = int((self.token.parent / "watch.pid").read_text())
        os.kill(pid, 0)
        first = self.token.read_text()
        deadline = time.time() + 10
        while self.token.read_text() == first and time.time() < deadline:
            time.sleep(0.2)
        self.assertNotEqual(self.token.read_text(), first, "the background loop did not refresh the token")
        again = self.run_cn("up", cwd=repo)
        self.assertIn("already running", again.stdout)
        out = self.run_cn("down", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("stopped", out.stdout)
        time.sleep(0.3)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertFalse((self.token.parent / "watch.pid").exists())

    def test_up_without_developer_mode_starts_nothing(self):
        repo = self.repo("CN_IDENTITY_PROVIDER=legacy-refresh-token\n")
        out = self.run_cn("up", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(self.token.exists())
        self.assertIn("sandbox.sh up file=", (self.state / "sandbox.log").read_text())

    def test_other_token_commands_go_to_the_sandbox(self):
        repo = self.repo("")
        out = self.run_cn("token", "person", "alice", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("sandbox.sh token person alice", (self.state / "sandbox.log").read_text())


# docker ps -q --filter label=com.docker.compose.project=<p>: an id when $FAKE_STATE/running/<p> exists.
FAKE_DOCKER = """#!/usr/bin/env bash
if [ "$1" = ps ]; then
  for arg in "$@"; do
    case "$arg" in label=com.docker.compose.project=*)
      [ -f "$FAKE_STATE/running/${arg#label=com.docker.compose.project=}" ] && echo c0ffee ;;
    esac
  done
fi
exit 0
"""


class SharedRefreshTest(unittest.TestCase):
    """Several sandboxes at once share one refresh loop; `down` stops it only in the last one."""

    run_cn = TokenTest.run_cn
    tearDown = TokenTest.tearDown

    def setUp(self):
        TokenTest.setUp(self)
        write_exe(self.bin / "docker", FAKE_DOCKER)
        (self.state / "running").mkdir()
        self.env["CN_SANDBOX_TOKEN_INTERVAL"] = "30"
        self.users = self.token.parent / "users"

    def agent(self, name):
        repo = self.tmp / name
        (repo / "sandbox").mkdir(parents=True)
        write_exe(repo / "sandbox" / "sandbox.sh", SANDBOX_STUB)
        (repo / ".env").write_text("CN_IDENTITY_PROVIDER=developer\n")
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=self.env)
        return repo.resolve()   # git rev-parse gives the real path (/private/var/... on macOS)

    def up(self, repo, **env):
        out = self.run_cn("up", cwd=repo, **env)
        self.assertEqual(out.returncode, 0, out.stderr)
        (self.state / "running" / f"sandbox-{repo.name}").touch()
        return out

    def down(self, repo, **env):
        (self.state / "running" / f"sandbox-{repo.name}").unlink(missing_ok=True)
        out = self.run_cn("down", cwd=repo, **env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out

    def pid(self):
        return int((self.token.parent / "watch.pid").read_text())

    def alive(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    def gone(self, pid):
        deadline = time.time() + 5
        while self.alive(pid) and time.time() < deadline:
            time.sleep(0.1)
        return not self.alive(pid)

    def listed(self):
        if not self.users.exists():
            return set()
        return {p.read_text().splitlines()[0] for p in self.users.iterdir()}

    def test_two_sandboxes_share_one_loop_and_the_last_down_stops_it(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        pid = self.pid()
        out = self.up(b)
        self.assertIn("already running", out.stdout)
        self.assertEqual(self.pid(), pid)
        self.assertEqual(self.listed(), {str(a), str(b)})
        out = self.down(a)
        self.assertIn("keeps running for 1 other sandbox(es)", out.stdout)
        self.assertTrue(self.alive(pid), "down in one sandbox stopped the loop of the other")
        self.assertEqual(self.listed(), {str(b)})
        out = self.down(b)
        self.assertIn("stopped", out.stdout)
        self.assertTrue(self.gone(pid))
        self.assertEqual(self.listed(), set())
        self.assertFalse((self.token.parent / "watch.pid").exists())

    def test_as_me_off_keeps_the_loop_for_another_sandbox(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        self.up(b)
        pid = self.pid()
        out = self.run_cn("as-me", "off", cwd=a)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.alive(pid))
        self.assertEqual(self.listed(), {str(b)})

    def test_a_stale_entry_is_pruned(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        self.up(b)
        pid = self.pid()
        (self.state / "running" / "sandbox-alpha").unlink()   # alpha's containers are gone without a down
        out = self.down(b, CN_SANDBOX_TOKEN_GRACE="0")
        self.assertIn(f"no sandbox runs for {a}", out.stdout)
        self.assertTrue(self.gone(pid))
        self.assertEqual(self.listed(), set())

    def test_a_fresh_entry_is_not_pruned(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        self.up(b)
        (self.state / "running" / "sandbox-alpha").unlink()   # alpha may still be starting
        self.down(b)
        self.assertTrue(self.alive(self.pid()))
        self.assertEqual(self.listed(), {str(a)})

    def test_token_stop_stops_the_loop_for_all_and_clears_the_list(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        self.up(b)
        pid = self.pid()
        out = self.run_cn("token", "--stop")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.gone(pid))
        self.assertFalse(self.users.exists())

    def test_status_says_for_how_many_sandboxes(self):
        a, b = self.agent("alpha"), self.agent("beta")
        self.up(a)
        self.up(b)
        out = self.run_cn("status", cwd=a)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("cn-sandbox: token refresh: running for 2 sandbox(es)\n", out.stdout)
        self.assertNotIn("eyJ", out.stdout + out.stderr)
        (self.state / "running" / "sandbox-beta").unlink()
        out = self.run_cn("status", cwd=a, CN_SANDBOX_TOKEN_GRACE="0")
        self.assertIn("token refresh: running for 1 sandbox(es)\n", out.stdout)
        self.run_cn("token", "--stop")
        out = self.run_cn("status", cwd=a)
        self.assertIn("token refresh: not running\n", out.stdout)

    def test_parallel_ups_start_one_loop_and_list_every_repository(self):
        repos = [self.agent(f"agent{i}") for i in range(4)]
        procs = [subprocess.Popen(["bash", str(CN_SANDBOX), "up"], cwd=r, env=self.env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for r in repos]
        outs = []
        for p in procs:
            outs.append(p.communicate(timeout=30)[0])
            self.assertEqual(p.returncode, 0)
        self.assertEqual(self.listed(), {str(r) for r in repos})
        text = "".join(outs)
        self.assertEqual(text.count("token refresh started"), 1, text)
        self.assertEqual(text.count("already running"), 3, text)
        self.assertTrue(self.alive(self.pid()))
        self.assertFalse((self.token.parent / "users.lock").exists())


class DoctorTest(unittest.TestCase):
    def check(self, **env):
        tmp = pathlib.Path(tempfile.mkdtemp())
        write_exe(tmp / "oidc-token", FAKE_TOKEN)
        write_exe(tmp / "oidc-agent", FAKE_AGENT)
        script = f'. "{ROOT}/lib/common.sh"; . "{ROOT}/lib/sandbox_token.sh"; oidc_check'
        try:
            return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30,
                                  env={"HOME": str(tmp), "PATH": f"{tmp}:/usr/bin:/bin", "FAKE_STATE": str(tmp),
                                       **env})
        finally:
            subprocess.run(["rm", "-rf", str(tmp)], check=False)

    def test_a_working_account(self):
        out = self.check()
        self.assertEqual(out.returncode, 0, out.stdout)
        self.assertIn("oidc-token cn-agw works", out.stdout)

    def test_an_old_oidc_agent(self):
        out = self.check(FAKE_VERSION="5.1.0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("older than 5.2.0", out.stdout)

    def test_an_account_that_is_not_loaded(self):
        out = self.check(FAKE_FAIL="1")
        self.assertEqual(out.returncode, 1)
        self.assertIn("oidc-add cn-agw", out.stdout)

    def test_no_oidc_agent_is_no_problem(self):
        out = subprocess.run(["bash", "-c", f'. "{ROOT}/lib/common.sh"; . "{ROOT}/lib/sandbox_token.sh"; oidc_check'],
                             capture_output=True, text=True, timeout=30,
                             env={"HOME": "/nonexistent", "PATH": "/usr/bin:/bin"})
        self.assertEqual(out.returncode, 0)
        self.assertIn("not found: oidc-agent", out.stdout)


if __name__ == "__main__":
    unittest.main()
