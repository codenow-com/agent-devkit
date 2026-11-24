"""Tests of uv in the devkit: the indexes from pip.conf (lib/uv_env.py), cn-warm and cn-venv with a fake uv and git,
the uv lines of cn-doctor and the consent of cn-setup to install uv. No network.

    python3 -m unittest discover -s tests
"""
import importlib.util
import os
import pathlib
import platform
import pty
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = "s3cr3t-T0KEN"
TENANT = f"https://alice:{TOKEN}@codenow.jfrog.io/artifactory/api/pypi/demo-tenant-pip/simple"
PROXY = f"https://alice:{TOKEN}@codenow.jfrog.io/artifactory/api/pypi/stxcn-pip"
PIP_CONF = f"""[global]
index-url = {PROXY}
extra-index-url =
    https://pypi.org/simple
    {TENANT}
"""

spec = importlib.util.spec_from_file_location("uv_env", ROOT / "lib" / "uv_env.py")
uv_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uv_env)

# uv: venv makes the folder; pip install logs the index variables and fails with the index URL in its output when
# $FAKE_STATE/fail exists; cache dir prints a folder.
FAKE_UV = """#!/bin/bash
case "$1" in
  --version) echo "uv 0.9.9 (fake)" ;;
  cache) echo "$FAKE_STATE/uvcache" ;;
  venv) for a in "$@"; do last="$a"; done; mkdir -p "$last/bin"; printf '#!/bin/bash\\necho Python 3.12.9\\n' > "$last/bin/python"; chmod +x "$last/bin/python"; echo "venv $*" >> "$FAKE_STATE/uv.log" ;;
  pip)
    echo "pip $* offline=${UV_OFFLINE:-} strategy=${UV_INDEX_STRATEGY:-} python=${UV_PYTHON_PREFERENCE:-} conda=${CONDA_PREFIX:-} venv=$VIRTUAL_ENV req=$(head -n 1 requirements.txt)" >> "$FAKE_STATE/uv.log"
    echo "$UV_EXTRA_INDEX_URL" > "$FAKE_STATE/extra"
    if [ -f "$FAKE_STATE/fail" ]; then echo "error: 403 Forbidden for $UV_EXTRA_INDEX_URL" >&2; exit 1; fi
    mkdir -p "$FAKE_STATE/uvcache"; echo x > "$FAKE_STATE/uvcache/blob" ;;
esac
"""
# git: ls-remote prints tags; clone writes requirements.txt naming the ref.
FAKE_GIT = """#!/bin/bash
echo "git $*" >> "$FAKE_STATE/git.log"
case "$1" in
  ls-remote) printf 'a\\trefs/tags/tmpl-v1.9.0\\nb\\trefs/tags/tmpl-v1.10.0\\nc\\trefs/tags/other\\n' ;;
  clone) for a in "$@"; do last="$a"; done; ref=main
    prev=""; for a in "$@"; do [ "$prev" = --branch ] && ref="$a"; prev="$a"; done
    mkdir -p "$last"; echo "pkg-from-$ref==1.0" > "$last/requirements.txt" ;;
  rev-parse) exit 1 ;;
  *) exit 99 ;;
esac
"""
FAKE_PYTHON = """#!/bin/bash
[ "$1" = -m ] && [ "$2" = pip ] && exit 1
exec "$REAL_PYTHON" "$@"
"""


def write_exe(path, text):
    path.write_text(text)
    path.chmod(0o755)


class IndexesTest(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        (self.home / ".config" / "pip").mkdir(parents=True)
        (self.home / ".config" / "pip" / "pip.conf").write_text(PIP_CONF)
        self.env = {"HOME": str(self.home), "PATH": "/usr/bin:/bin"}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_env(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "uv_env.py"), *args],
                              env=env or self.env, capture_output=True, text=True, timeout=30)

    def test_tenant_first_then_pypi_then_the_index_url_with_simple(self):
        self.assertEqual(uv_env.tenant_indexes(self.env), [TENANT, "https://pypi.org/simple", PROXY + "/simple"])

    def test_exports_for_eval(self):
        out = self.run_env("exports")
        self.assertEqual(out.returncode, 0, out.stderr)
        env = subprocess.run(["bash", "-c", 'eval "$1"; echo "$UV_EXTRA_INDEX_URL|$UV_INDEX_STRATEGY"', "-",
                              out.stdout], capture_output=True, text=True).stdout.strip()
        self.assertEqual(env, f"{TENANT} https://pypi.org/simple {PROXY}/simple|unsafe-first-match")

    def test_show_masks_the_credentials(self):
        out = self.run_env("show")
        self.assertEqual(out.returncode, 0)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        self.assertNotIn("alice", out.stdout)
        self.assertIn("https://***@codenow.jfrog.io/artifactory/api/pypi/demo-tenant-pip/simple", out.stdout)

    def test_exports_refuse_a_terminal(self):
        master, slave = pty.openpty()
        try:
            p = subprocess.run([sys.executable, "-I", str(ROOT / "lib" / "uv_env.py"), "exports"], env=self.env,
                               stdout=slave, stderr=subprocess.PIPE, timeout=30)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn(TOKEN.encode(), p.stderr)

    def test_set_uv_variables_are_kept(self):
        for name in ("UV_EXTRA_INDEX_URL", "UV_INDEX", "UV_DEFAULT_INDEX", "UV_INDEX_URL"):
            with self.subTest(name=name):
                out = uv_env.exports({**self.env, name: "https://mine.example/simple"})
                self.assertNotIn("UV_EXTRA_INDEX_URL", out)
                self.assertNotIn("UV_INDEX_STRATEGY", out)
        self.assertNotIn("UV_INDEX_STRATEGY", uv_env.exports({**self.env, "UV_INDEX_STRATEGY": "first-index"}))

    def test_pip_variables_and_files(self):
        env = {**self.env, "PIP_EXTRA_INDEX_URL": "https://t@x.example/simple https://pypi.org/simple"}
        self.assertEqual(uv_env.tenant_indexes(env), ["https://t@x.example/simple", "https://pypi.org/simple",
                                                      PROXY + "/simple"])
        self.assertEqual(uv_env.tenant_indexes({**self.env, "PIP_CONFIG_FILE": os.devnull}), [])
        other = self.home / "other.conf"
        other.write_text("[install]\nextra-index-url = https://y.example/simple\n")
        self.assertEqual(uv_env.tenant_indexes({**self.env, "PIP_CONFIG_FILE": str(other)}),
                         ["https://y.example/simple", PROXY + "/simple"])

    def test_only_pypi_exports_no_index(self):
        (self.home / ".config" / "pip" / "pip.conf").write_text("[global]\nindex-url = https://pypi.org/simple\n")
        self.assertNotIn("UV_EXTRA_INDEX_URL", uv_env.exports(self.env))
        self.assertIn("public PyPI only", self.run_env("show").stdout)

    def test_hardlink_on_linux_only(self):
        with mock.patch.object(uv_env.platform, "system", return_value="Linux"):
            self.assertEqual(uv_env.exports(self.env)["UV_LINK_MODE"], "hardlink")
            self.assertNotIn("UV_LINK_MODE", uv_env.exports({**self.env, "UV_LINK_MODE": "copy"}))
        with mock.patch.object(uv_env.platform, "system", return_value="Darwin"):
            self.assertNotIn("UV_LINK_MODE", uv_env.exports(self.env))


class FakeToolsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.state = self.tmp / "state"
        self.tmpdir = self.tmp / "t"
        for d in (self.home, self.bin, self.state, self.tmpdir):
            d.mkdir()
        (self.home / ".pip").mkdir()
        (self.home / ".pip" / "pip.conf").write_text(PIP_CONF)
        write_exe(self.bin / "uv", FAKE_UV)
        write_exe(self.bin / "git", FAKE_GIT)
        write_exe(self.bin / "python3", FAKE_PYTHON)
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_STATE": str(self.state),
                    "REAL_PYTHON": sys.executable, "TMPDIR": str(self.tmpdir), "CONDA_PREFIX": "/opt/conda"}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cn(self, command, *args, cwd=None, env=None, stdin=None):
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / command), *args], cwd=cwd or self.home,
                              env=env or self.env, capture_output=True, text=True, timeout=60, input=stdin)

    def log(self, name):
        path = self.state / name
        return path.read_text() if path.exists() else ""


class WarmTest(FakeToolsCase):
    def test_newest_tag_cached_and_checked_offline(self):
        env = {**self.env, "CN_WARM_REPOS": "https://git.example/a/tmpl.git https://git.example/b/pinned.git#v0.1"}
        out = self.run_cn("cn-warm", env=env)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        uv_log = self.log("uv.log")
        self.assertIn("req=pkg-from-tmpl-v1.10.0==1.0", uv_log)   # sort -V: 1.10.0 is newer than 1.9.0
        self.assertIn("req=pkg-from-v0.1==1.0", uv_log)            # #ref: no ls-remote needed
        self.assertEqual(self.log("git.log").count("ls-remote"), 1)
        self.assertEqual(uv_log.count("offline=1"), 2)
        self.assertIn("strategy=unsafe-first-match", uv_log)
        self.assertIn("python=only-managed", uv_log)
        self.assertIn("conda= ", uv_log)
        self.assertEqual(self.log("extra").strip(), f"{TENANT} https://pypi.org/simple {PROXY}/simple")
        self.assertIn("tmpl (tmpl-v1.10.0): cached in", out.stdout)
        self.assertIn("offline install: ok", out.stdout)
        self.assertIn("uv cache:", out.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [], "the temporary folder stays")

    def test_a_failed_install_is_masked_and_exits_1(self):
        (self.state / "fail").write_text("")
        out = self.run_cn("cn-warm", env={**self.env, "CN_WARM_REPOS": "https://git.example/a/tmpl.git"})
        self.assertEqual(out.returncode, 1)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        self.assertIn("403 Forbidden for https://***@", out.stdout)
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_without_uv(self):
        (self.bin / "uv").unlink()
        out = self.run_cn("cn-warm")
        self.assertEqual(out.returncode, 1)
        self.assertIn("uv is missing", out.stderr)


class VenvTest(FakeToolsCase):
    def test_uv_venv_with_the_tenant_index_never_conda(self):
        repo = self.tmp.resolve() / "agent"
        (repo / "sandbox" / "wheels").mkdir(parents=True)
        (repo / "sandbox" / "wheels" / "sdk-1.0-py3-none-any.whl").write_text("")
        (repo / "requirements.txt").write_text("codenow-agent-sdk==2.24.0\n")
        out = self.run_cn("cn-venv", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        uv_log = self.log("uv.log")
        self.assertIn("venv -q --python 3.12 .venv", uv_log)
        self.assertIn("--find-links sandbox/wheels", uv_log)
        self.assertIn(f"venv={repo}/.venv", uv_log)
        self.assertIn("conda= ", uv_log)
        self.assertEqual(self.log("extra").strip(), f"{TENANT} https://pypi.org/simple {PROXY}/simple")
        self.assertIn(".venv ready", out.stdout)

    def test_no_requirements(self):
        out = self.run_cn("cn-venv", cwd=self.tmp)
        self.assertEqual(out.returncode, 1)
        self.assertIn("no requirements.txt", out.stderr)


@unittest.skipUnless(platform.system() == "Darwin", "cn-setup offers brew install uv on macOS only")
class SetupTest(FakeToolsCase):
    def setUp(self):
        super().setUp()
        (self.bin / "uv").unlink()
        # brew install uv: puts the fake uv on PATH
        write_exe(self.bin / "brew", f'echo "brew $*" >> "$FAKE_STATE/brew.log"\n'
                                     f'[ "$1 $2" = "install uv" ] && cp "$FAKE_STATE/uv" "{self.bin}/uv"\nexit 0\n')
        write_exe(self.state / "uv", FAKE_UV)
        write_exe(self.bin / "curl", "exit 1\n")

    def test_doctor_reports_uv_and_its_indexes_masked(self):
        write_exe(self.bin / "uv", FAKE_UV)
        out = self.run_cn("cn-doctor", "--skip-gateway")
        self.assertNotIn(TOKEN, out.stdout + out.stderr)
        self.assertIn("cn-doctor: found uv 0.9.9; indexes, in this order: https://***@codenow.jfrog.io", out.stdout)
        self.assertIn("cn-doctor: uv cache: empty in ", out.stdout)
        self.assertEqual(self.log("brew.log"), "")

    def test_doctor_without_uv_recommends_it(self):
        out = self.run_cn("cn-doctor", "--skip-gateway")
        self.assertIn("not found: uv (recommended", out.stdout)
        self.assertIn("brew install uv", out.stdout)
        self.assertEqual(self.log("brew.log"), "")

    def test_setup_installs_uv_only_with_consent(self):
        env = {**self.env, "CN_SETUP_INTERACTIVE": "1"}
        out = self.run_cn("cn-setup", "--skip-gateway", env=env, stdin="n\n")
        self.assertEqual(self.log("brew.log"), "")
        self.assertIn("not found: uv", out.stdout)
        out = self.run_cn("cn-setup", "--skip-gateway", env=env, stdin="y\nn\n")
        self.assertEqual(self.log("brew.log"), "brew install uv\n")
        self.assertIn("found uv 0.9.9", out.stdout)
        self.assertIn("cn-warm", out.stdout)          # the offer at the end, answered no
        self.assertEqual(self.log("git.log").count("ls-remote"), 0)

    def test_setup_without_a_person_installs_nothing(self):
        self.run_cn("cn-setup", "--skip-gateway")
        self.assertEqual(self.log("brew.log"), "")


if __name__ == "__main__":
    unittest.main()
