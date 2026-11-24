"""Tests of the Google ADK tools (lib/adk_tools.sh): cn-setup --adk and its question, the pin of the ADK template,
the PyPI fallback, the PATH and gcloud offers, the cn-doctor lines and the hint in an ADK agent repository. Fake uv,
git, curl and brew; no network.

    python3 -m unittest discover -s tests
"""
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "s3cr3t-T0KEN"
PIP_CONF = f"""[global]
extra-index-url =
    https://pypi.org/simple
    https://alice:{TOKEN}@codenow.jfrog.io/artifactory/api/pypi/demo-tenant-pip/simple
"""
TEMPLATE = "demo-tenant-adk-based-agent adk-based-agent-v1.1.0"

# uv: tool dir --bin prints $FAKE_STATE/toolbin; tool install writes an adk of the pinned version there.
FAKE_UV = """#!/bin/bash
case "$1 $2" in
  "--version "*) echo "uv 0.9.9 (fake)" ;;
  "cache dir") echo "$FAKE_STATE/uvcache" ;;
  "tool dir") echo "$FAKE_STATE/toolbin" ;;
  "tool update-shell") echo "update-shell" >> "$FAKE_STATE/uv.log" ;;
  "tool install")
    echo "tool $* strategy=${UV_INDEX_STRATEGY:-} python=${UV_PYTHON_PREFERENCE:-} conda=${CONDA_PREFIX:-}" >> "$FAKE_STATE/uv.log"
    if [ -f "$FAKE_STATE/fail" ]; then echo "error: 403 Forbidden for $UV_EXTRA_INDEX_URL" >&2; exit 1; fi
    for a in "$@"; do case "$a" in google-adk==*) v="${a#google-adk==}" ;; esac; done
    mkdir -p "$FAKE_STATE/toolbin"
    printf '#!/bin/bash\\necho "adk, version %s"\\n' "$v" > "$FAKE_STATE/toolbin/adk"; chmod +x "$FAKE_STATE/toolbin/adk" ;;
esac
"""
# git: ls-remote prints tags; clone writes the ADK template's requirements.txt (fails with $FAKE_STATE/noclone);
# rev-parse --show-toplevel prints $FAKE_TOPLEVEL when it is set.
FAKE_GIT = """#!/bin/bash
echo "git $*" >> "$FAKE_STATE/git.log"
case "$1" in
  ls-remote) printf 'a\\trefs/tags/adk-based-agent-v1.0.0\\nb\\trefs/tags/adk-based-agent-v1.1.0\\n' ;;
  clone) [ -f "$FAKE_STATE/noclone" ] && exit 128
    for a in "$@"; do last="$a"; done; mkdir -p "$last"
    printf 'a2a-sdk==0.3.9\\ngoogle-adk[a2a]==2.14.1  # the runtime\\n' > "$last/requirements.txt" ;;
  rev-parse) [ -n "${FAKE_TOPLEVEL:-}" ] || exit 1; echo "$FAKE_TOPLEVEL" ;;
  *) exit 99 ;;
esac
"""
FAKE_CURL = """#!/bin/bash
echo "curl $*" >> "$FAKE_STATE/curl.log"
case "$*" in *pypi.org/pypi/google-adk/json*) [ -f "$FAKE_STATE/pypi" ] && echo '{"info": {"version": "9.9.9"}}' && exit 0 ;; esac
exit 22
"""
FAKE_PYTHON = """#!/bin/bash
[ "$1" = -m ] && [ "$2" = pip ] && exit 1
exec "$REAL_PYTHON" "$@"
"""


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class AdkCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp()).resolve()
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        self.tmpdir = self.tmp / "t"
        for d in (self.home, self.bin, self.state, self.tmpdir):
            d.mkdir()
        (self.home / ".pip").mkdir()
        (self.home / ".pip" / "pip.conf").write_text(PIP_CONF)
        self.toolbin = self.state / "toolbin"
        write_exe(self.bin / "uv", FAKE_UV)
        write_exe(self.bin / "git", FAKE_GIT)
        write_exe(self.bin / "curl", FAKE_CURL)
        write_exe(self.bin / "python3", FAKE_PYTHON)
        write_exe(self.bin / "brew", 'echo "brew $*" >> "$FAKE_STATE/brew.log"\nexit 0\n')
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_STATE": str(self.state),
                    "REAL_PYTHON": sys.executable, "TMPDIR": str(self.tmpdir), "CONDA_PREFIX": "/opt/conda"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cn(self, command, *args, env=None, stdin=None, cwd=None):
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / command), *args], cwd=cwd or self.home,
                              env=env or self.env, capture_output=True, text=True, timeout=60, input=stdin)

    def log(self, name):
        path = self.state / name
        return path.read_text() if path.exists() else ""

    def config(self):
        path = self.home / ".codenow" / "config"
        return path.read_text() if path.exists() else ""

    def fake_adk(self, version):
        self.toolbin.mkdir(exist_ok=True)
        write_exe(self.toolbin / "adk", f'#!/bin/bash\necho "adk, version {version}"\n')

    def with_toolbin_on_path(self):
        return {**self.env, "PATH": f"{self.toolbin}:{self.env['PATH']}"}


class PinTest(AdkCase):
    def pin_of(self, text):
        req = self.tmp / "requirements.txt"
        req.write_text(text)
        out = subprocess.run(["/bin/bash", "-c", f'. "{ROOT}/lib/common.sh"; . "{ROOT}/lib/adk_tools.sh"; '
                              f'adk_req_pin "{req}"'], capture_output=True, text=True, env=self.env)
        return out.stdout.strip()

    def test_pin_forms(self):
        self.assertEqual(self.pin_of("google-adk==1.18.0\n"), "1.18.0")
        self.assertEqual(self.pin_of("x==1\ngoogle-adk[a2a]==2.14.1  # runtime\n"), "2.14.1")
        self.assertEqual(self.pin_of("google_adk[a2a,eval] == 2.0.0rc1\n"), "2.0.0rc1")
        self.assertEqual(self.pin_of("google-adk>=1.0\n"), "")
        self.assertEqual(self.pin_of("# google-adk==1.0\ngoogle-adk-extras==3.0\n"), "")


class SetupAdkTest(AdkCase):
    def test_adk_installs_the_template_pin_through_the_devkit_index(self):
        out = self.run_cn("cn-setup", "--adk")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        self.assertIn("CN_ADK=yes", self.config())
        uv_log = self.log("uv.log")
        self.assertIn("tool install --force --python 3.12 google-adk==2.14.1", uv_log)
        self.assertIn("strategy=unsafe-first-match", uv_log)
        self.assertIn("python=only-managed", uv_log)
        self.assertTrue(uv_log.rstrip().endswith("conda="), uv_log)
        self.assertIn(f"installing the adk CLI, google-adk 2.14.1 (the pin of {TEMPLATE})", out.stdout)
        self.assertIn("cn-setup:   uv tool install --force --python 3.12 google-adk==2.14.1", out.stdout)
        self.assertIn(f"adk 2.14.1 installed in {self.toolbin}", out.stdout)
        # no person: the PATH is explained, never changed; gcloud is explained, never installed
        self.assertIn(f"PATH: add {self.toolbin} with  uv tool update-shell", out.stdout)
        self.assertNotIn("update-shell\n", uv_log)
        self.assertIn("gcloud is optional: CodeNOW does not need it", out.stdout)
        self.assertEqual(self.log("brew.log"), "")
        self.assertIn("Google ADK tools: done", out.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [], "the temporary folder stays")

    def test_upgrade_when_the_pin_changes_and_nothing_when_it_matches(self):
        self.fake_adk("2.13.0")
        env = self.with_toolbin_on_path()
        out = self.run_cn("cn-setup", "--adk", env=env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(f"adk 2.13.0 -> 2.14.1 (the pin of {TEMPLATE})", out.stdout)
        self.assertNotIn("PATH: add", out.stdout)
        out = self.run_cn("cn-setup", "--adk", env=env)
        self.assertIn(f"found adk 2.14.1 (the pin of {TEMPLATE})", out.stdout)
        self.assertEqual(self.log("uv.log").count("tool install"), 1)

    def test_the_pin_falls_back_to_pypi_and_says_so(self):
        (self.state / "noclone").write_text("")
        (self.state / "pypi").write_text("")
        out = self.run_cn("cn-setup", "--adk")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("google-adk 9.9.9, the newest on PyPI; the pin of demo-tenant-adk-based-agent could not be read",
                      out.stdout)
        self.assertIn("google-adk==9.9.9", self.log("uv.log"))

    def test_no_pin_and_no_pypi_is_a_problem(self):
        (self.state / "noclone").write_text("")
        out = self.run_cn("cn-setup", "--adk")
        self.assertEqual(out.returncode, 1)
        self.assertIn("neither the google-adk pin", out.stdout)
        self.assertEqual(self.log("uv.log"), "")

    def test_a_failed_install_is_masked(self):
        (self.state / "fail").write_text("")
        out = self.run_cn("cn-setup", "--adk")
        self.assertEqual(out.returncode, 1)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        self.assertIn("403 Forbidden for https://***@", out.stdout)
        self.assertIn("uv could not install google-adk==2.14.1", out.stdout)

    def test_without_uv(self):
        (self.bin / "uv").unlink()
        out = self.run_cn("cn-setup", "--adk")
        self.assertEqual(out.returncode, 1)
        self.assertIn("Google ADK tools need uv", out.stdout)

    def test_the_repository_url_comes_from_cn_adk_repo(self):
        out = self.run_cn("cn-setup", "--adk", env={**self.env, "CN_ADK_REPO": "https://git.example/x/my-adk.git#v7"})
        self.assertIn("(the pin of my-adk v7)", out.stdout)
        self.assertNotIn("ls-remote", self.log("git.log"))
        self.assertIn("--branch v7 https://git.example/x/my-adk.git", self.log("git.log"))

    def test_adk_and_only_gateway_exclude_each_other(self):
        out = self.run_cn("cn-setup", "--adk", "--only-gateway")
        self.assertEqual(out.returncode, 2)
        self.assertIn("leave out --only-gateway", out.stderr)


@unittest.skipUnless(platform.system() == "Darwin", "cn-setup offers brew install --cask google-cloud-sdk on macOS only")
class SetupQuestionTest(AdkCase):
    """The full cn-setup: uv is there, so it asks about cn-warm, then about Google ADK. (read -p prints its prompt
    only on a terminal, so the answers are checked by their effect.)"""

    def setup(self, stdin):
        env = {**self.env, "CN_SETUP_INTERACTIVE": "1"}
        return self.run_cn("cn-setup", "--skip-gateway", env=env, stdin=stdin)

    def test_no_is_remembered(self):
        out = self.setup("n\nn\n")
        self.assertIn("CN_ADK=no", self.config())
        self.assertIn("Google ADK tools: skipped (CN_ADK=no); later: cn-setup --adk", out.stdout)
        out = self.setup("n\ny\ny\n")   # not asked again: the y answers nothing
        self.assertIn("Google ADK tools: skipped (CN_ADK=no)", out.stdout)
        self.assertIn("CN_ADK=no", self.config())
        self.assertEqual(self.log("uv.log"), "")

    def test_yes_installs_and_offers_path_and_gcloud(self):
        out = self.setup("n\ny\ny\ny\n")
        self.assertIn("CN_ADK=yes", self.config())
        self.assertIn("google-adk==2.14.1", self.log("uv.log"))
        self.assertIn("update-shell", self.log("uv.log"))
        self.assertIn("open a new terminal and restart VS Code", out.stdout)
        self.assertEqual(self.log("brew.log"), "brew install --cask google-cloud-sdk\n")

    def test_yes_with_no_to_path_and_gcloud(self):
        out = self.setup("n\ny\nn\nn\n")
        self.assertNotIn("update-shell\n", self.log("uv.log"))
        self.assertIn("PATH: add", out.stdout)
        self.assertIn("gcloud: not installed (later: brew install --cask google-cloud-sdk)", out.stdout)
        self.assertEqual(self.log("brew.log"), "")

    def test_without_a_person_nothing_is_asked_or_saved(self):
        out = self.run_cn("cn-setup", "--skip-gateway")
        self.assertNotIn("CN_ADK", self.config())
        self.assertIn("Google ADK tools: skipped; later: cn-setup --adk", out.stdout)
        self.assertEqual(self.log("uv.log"), "")


class DoctorAdkTest(AdkCase):
    def doctor(self, *args, env=None, cwd=None):
        return self.run_cn("cn-doctor", *(args or ("--adk",)), env=env, cwd=cwd)

    def test_matching_adk_and_optional_gcloud(self):
        self.fake_adk("2.14.1")
        out = self.doctor(env=self.with_toolbin_on_path())
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(f"cn-doctor: found adk 2.14.1 (the pin of {TEMPLATE})", out.stdout)
        self.assertIn("cn-doctor: not found: gcloud (optional:", out.stdout)
        self.assertEqual(self.log("uv.log"), "")

    def test_other_version_is_a_recommendation_not_a_problem(self):
        self.fake_adk("2.0.0")
        out = self.doctor(env=self.with_toolbin_on_path())
        self.assertEqual(out.returncode, 0)
        self.assertIn(f"found adk 2.0.0; the pin of {TEMPLATE} is 2.14.1 (recommended: cn-setup --adk)", out.stdout)

    def test_missing_and_off_path(self):
        out = self.doctor()
        self.assertEqual(out.returncode, 0)
        self.assertIn("not found: adk (recommended for ADK agents", out.stdout)
        self.fake_adk("2.14.1")
        out = self.doctor()
        self.assertIn(f"adk is in {self.toolbin}, which is not in PATH: uv tool update-shell", out.stdout)

    def test_found_gcloud(self):
        write_exe(self.bin / "gcloud", "exit 0\n")
        self.assertIn("found gcloud (optional)", self.doctor().stdout)

    def test_full_doctor_follows_cn_adk(self):
        out = self.doctor("--skip-gateway")
        self.assertIn("Google ADK tools: not set up (cn-setup asks once; cn-setup --adk)", out.stdout)
        self.assertNotIn("ls-remote", self.log("git.log"))
        (self.home / ".codenow").mkdir(exist_ok=True)
        (self.home / ".codenow" / "config").write_text("CN_ADK=no\n")
        out = self.doctor("--skip-gateway")
        self.assertNotIn("adk", out.stdout.replace("cn-setup --adk", ""))
        (self.home / ".codenow" / "config").write_text("CN_ADK=yes\n")
        out = self.doctor("--skip-gateway")
        self.assertIn("not found: adk (recommended", out.stdout)
        self.assertIn("not found: gcloud (optional", out.stdout)


class RepoHintTest(AdkCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "agent"
        (self.repo / "sandbox").mkdir(parents=True)
        (self.repo / "requirements.txt").write_text("google-adk[a2a]==2.14.1\n")
        (self.repo / "sandbox" / "sandbox.sh").write_text('echo "sandbox.sh $*"\n')
        self.env = {**self.env, "FAKE_TOPLEVEL": str(self.repo)}

    def test_doctor_in_an_adk_agent(self):
        out = self.run_cn("cn-doctor", "--adk", cwd=self.repo)
        self.assertIn("ADK agent (google-adk 2.14.1): no .venv/bin/adk yet: run cn-venv", out.stdout)
        self.assertIn("VS Code ADK extension: select the interpreter .venv/bin/python (Python: Select Interpreter) "
                      "so it finds adk", out.stdout)
        self.assertIn("port 8000 is adk web's default; the CodeNOW sandbox uses its own port", out.stdout)
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        write_exe(self.repo / ".venv" / "bin" / "adk", "exit 0\n")
        out = self.run_cn("cn-doctor", "--adk", cwd=self.repo)
        self.assertIn("ADK agent (google-adk 2.14.1): adk is in .venv/bin", out.stdout)

    def test_sandbox_status_in_an_adk_agent(self):
        out = self.run_cn("cn-sandbox", "status", cwd=self.repo)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("cn-sandbox: ADK agent (google-adk 2.14.1): no .venv/bin/adk yet: run cn-venv", out.stdout)
        self.assertIn("select the interpreter .venv/bin/python", out.stdout)
        self.assertTrue(out.stdout.rstrip().endswith("sandbox.sh status"))

    def test_no_hint_in_another_repository(self):
        (self.repo / "requirements.txt").write_text("codenow-agent-sdk==2.24.0\n")
        out = self.run_cn("cn-sandbox", "status", cwd=self.repo)
        self.assertNotIn("ADK agent", out.stdout)


if __name__ == "__main__":
    unittest.main()
