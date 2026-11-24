"""Tests of the sandbox hub: the collector and page of lib/cn_hub.py with a fake Docker, and `cn-sandbox hub`.

    python3 -m unittest discover -s tests
"""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CN_SANDBOX = ROOT / "bin" / "cn-sandbox"
sys.path.insert(0, str(ROOT / "lib"))
import cn_hub  # noqa: E402
import cn_hub_render  # noqa: E402

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJwZXRyIn0.c2lnbmF0dXJlLXNlY3JldA"
SECRET = "refresh-secret-value-42"
FAKE_DOCKER_EMPTY = "#!/bin/bash\nexit 0\n"
SANDBOX_STUB = "#!/usr/bin/env bash\necho \"sandbox.sh $*\"\n"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def container(cid, project, service, state, workdir, port=None):
    labels = {"com.docker.compose.project": project, "com.docker.compose.service": service,
              "com.docker.compose.project.working_dir": workdir,
              "com.docker.compose.depends_on": "egress:service_started:false,runstore:service_healthy:false"}
    ports = {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]} if port else {}
    return {"Id": cid, "Name": f"/{project}-{service}-1", "Config": {"Labels": labels, "Env": [f"TOKEN={SECRET}"]},
            "State": {"Status": state}, "NetworkSettings": {"Ports": ports if state == "running" else {}},
            "HostConfig": {"PortBindings": ports}}


class FakeDocker:
    """Three sandboxes: alpha (developer, approved), beta (deployment token), gamma (stopped); one other project."""

    def __init__(self, tmp: pathlib.Path):
        self.containers, self.logs = [], {}
        for name, state, port, env, log in [
            ("alpha", "running", 8081, f"CN_IDENTITY_PROVIDER=developer\nWORKFORCE_URL=http://observer:8080\n"
                                       f"WORKFORCE_MODE=shadow\nCN_IDENTITY_DEVELOPER_CLIENTS=cli-a\n"
                                       f"AI_GATEWAY_REFRESH_TOKEN={SECRET}\n",
             f"INFO identity: adapter developer\nDEBUG Authorization: Bearer {JWT}\ntoken={JWT}\n"
             "INFO Workforce: onboarding approved (instance inst-1, mode shadow)\n"),
            ("beta", "running", 8082, f"AI_GATEWAY_REFRESH_TOKEN={JWT}\n",
             "INFO identity: adapter legacy-refresh-token\n"
             "WARNING tool_policy: Workforce is not configured; no mandate layer\n"),
            ("gamma", "exited", 8083, "", ""),
        ]:
            repo = tmp / name
            (repo / "sandbox" / ".run").mkdir(parents=True)
            (repo / ".env").write_text(env)
            (repo / "requirements.txt").write_text("codenow-agent-sdk==2.24.0\n")
            (repo / "sandbox" / ".run" / "allow").write_text(
                "^agent-gateway\\.demo\\.example\\.com$\n^iam\\.example\\.com$\n^observer$\n^api\\.tariffs\\.gov$\n")
            (repo / "sandbox" / ".run" / "port").write_text(str(port))
            project = f"sandbox-{name}"
            for service in ("agent", "edge", "egress", "runstore", "valkey"):
                cid = f"{name}-{service}"
                self.containers.append(container(cid, project, service, state, str(repo / "sandbox"),
                                                 port if service == "edge" else None))
            self.logs[f"{name}-agent"] = log
        self.containers.append(container("other-1", "observer", "observer", "running", str(tmp)))

    def __call__(self, *args):
        if args[0] == "ps":
            return "".join(json.dumps({"ID": c["Id"], "Labels": "a=b,c"}) + "\n" for c in self.containers)
        if args[0] == "inspect":
            return json.dumps([c for c in self.containers if c["Id"] in args[1:]])
        if args[0] == "logs":
            return self.logs.get(args[-1], "")
        return ""


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "codenow"
        self.docker = FakeDocker(self.tmp)
        self.data = {sb["name"]: sb for sb in cn_hub.collect(self.docker, self.home)}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_sandbox_project_and_nothing_else(self):
        self.assertEqual(sorted(self.data), ["alpha", "beta", "gamma"])

    def test_json_shape(self):
        alpha = self.data["alpha"]
        self.assertEqual(alpha["repo"], str(self.tmp / "alpha"))
        self.assertEqual(alpha["status"], "running")
        self.assertEqual([s["name"] for s in alpha["services"]], ["agent", "edge", "egress", "runstore", "valkey"])
        self.assertEqual(alpha["console"], {"host": "127.0.0.1", "port": 8081, "url": "http://localhost:8081/"})
        self.assertEqual(alpha["identity"]["mode"], "developer")
        self.assertEqual(alpha["workforce"]["state"], "approved")
        self.assertEqual(alpha["workforce"]["instance"], "inst-1")
        self.assertEqual(alpha["sdk_version"], "2.24.0")
        self.assertEqual(alpha["env"], {"CN_IDENTITY_PROVIDER": "developer", "WORKFORCE_URL": "http://observer:8080",
                                        "WORKFORCE_MODE": "shadow", "CN_IDENTITY_DEVELOPER_CLIENTS": "set"})
        kinds = {h["host"]: h["kind"] for h in alpha["egress"]}
        self.assertEqual(kinds["agent-gateway.demo.example.com"], "agent gateway (models, MCP)")
        self.assertEqual(kinds["iam.example.com"], "IAM (tokens)")
        self.assertEqual(kinds["observer"], "observer (Workforce)")
        self.assertIn("connector", kinds["api.tariffs.gov"])
        for key in ("watch_running", "watch_pid", "token_age_s", "registry"):
            self.assertIn(key, alpha["token_refresh"])
        beta = self.data["beta"]
        self.assertEqual(beta["identity"]["label"], "deployment token")
        self.assertEqual(beta["workforce"]["state"], "not configured")
        gamma = self.data["gamma"]
        self.assertEqual(gamma["status"], "stopped")
        self.assertEqual(gamma["console"]["port"], 8083)   # from the edge's port binding, kept while stopped
        self.assertEqual(gamma["identity"]["mode"], "unknown")

    def test_the_shared_refresh_list_of_devkit_0_1_13(self):
        users = self.home / "sandbox-token" / "users"
        users.mkdir(parents=True)
        (users / "alpha").write_text(f"{self.tmp / 'alpha'}\nsandbox-alpha\n")
        data = {sb["name"]: sb for sb in cn_hub.collect(self.docker, self.home)}
        self.assertEqual(data["alpha"]["token_refresh"]["registry"], 1)
        self.assertTrue(data["alpha"]["token_refresh"]["uses_it"])
        self.assertFalse(data["beta"]["token_refresh"]["uses_it"])
        self.assertNotIn("projects", data["alpha"]["token_refresh"])
        self.assertIn("used by 1 sandbox(es)", cn_hub_render.card(data["alpha"], False))

    def test_the_pre_deploy_marker_shows_a_chip(self):
        self.assertFalse(self.data["alpha"]["predeploy"])
        self.assertNotIn(">pre-deploy</span>", cn_hub_render.card(self.data["alpha"], False))
        (self.tmp / "alpha" / "sandbox" / ".run" / "predeploy").write_text("user=demotenant\n")
        data = {sb["name"]: sb for sb in cn_hub.collect(self.docker, self.home)}
        self.assertTrue(data["alpha"]["predeploy"])
        self.assertFalse(data["beta"]["predeploy"])
        self.assertIn('class="chip warn">pre-deploy</span>', cn_hub_render.card(data["alpha"], False))

    def test_the_identity_chip_names_the_mode_and_its_source(self):
        self.assertIsNone(self.data["alpha"]["identity_mode"])
        (self.tmp / "alpha" / "sandbox" / ".run" / "identity-mode").write_text("as you (default)\n")
        (self.tmp / "beta" / "sandbox" / ".run" / "identity-mode").write_text("deployment token (as-me off)\n")
        data = {sb["name"]: sb for sb in cn_hub.collect(self.docker, self.home)}
        self.assertEqual(data["alpha"]["identity_mode"], "as you (default)")
        self.assertIn('class="chip ok">as you (default)</span>', cn_hub_render.card(data["alpha"], False))
        self.assertIn('class="chip warn">deployment token (as-me off)</span>', cn_hub_render.card(data["beta"], False))
        # the agent's log wins when the two disagree (e.g. CN_IDENTITY_PROVIDER set in the shell)
        (self.tmp / "alpha" / "sandbox" / ".run" / "identity-mode").write_text("deployment token (as-me off)\n")
        data = {sb["name"]: sb for sb in cn_hub.collect(self.docker, self.home)}
        self.assertIn('class="chip ok">as you (developer)</span>', cn_hub_render.card(data["alpha"], False))

    def test_no_token_or_secret_in_the_json_or_the_page(self):
        sandboxes = list(self.data.values())
        for text in (json.dumps(sandboxes), cn_hub_render.page(sandboxes)):
            self.assertNotIn("eyJ", text)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("AI_GATEWAY_REFRESH_TOKEN", text)

    def test_mask(self):
        self.assertEqual(cn_hub.mask(f"Bearer {JWT}"), "Bearer <token>")
        self.assertEqual(cn_hub.mask(f"x api_key={SECRET} y"), "x api_key=<masked> y")
        self.assertEqual(cn_hub.mask_log("blob " + "a" * 60), "blob <masked>")

    def test_page_links_consoles_and_draws_one_diagram_per_sandbox(self):
        html = cn_hub_render.page(sorted(self.data.values(), key=lambda s: s["name"]))
        self.assertIn("<h1>Agent sandboxes</h1>", html)
        self.assertEqual(html.count('<svg class="dia"'), 3)
        self.assertEqual(html.count('aria-label="How the sandbox'), 3)
        self.assertIn('href="http://localhost:8081/" target="_blank"', html)
        self.assertIn('href="http://localhost:8082/" target="_blank"', html)
        self.assertNotIn('href="http://localhost:8083/"', html)   # stopped: no link, the hint instead
        self.assertIn("<code>cn-sandbox up</code>", html)
        self.assertIn('class="chip ok">as you (developer)', html)
        self.assertIn('class="chip warn">deployment token', html)
        self.assertIn("Workforce: approved", html)
        self.assertIn("observer (Workforce)", html)
        self.assertNotIn("http://", html.replace("http://localhost:", "").replace("http://www.w3.org", "")
                         .replace("http://observer", ""))

    def test_empty_state(self):
        html = cn_hub_render.page([])
        self.assertIn("No sandbox runs. In an agent repository: <code>cn-sandbox up --as-me</code>", html)
        self.assertNotIn('<svg class="dia"', html)


class HubCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        (self.bin / "docker").write_text(FAKE_DOCKER_EMPTY)
        (self.bin / "docker").chmod(0o755)
        self.port = free_port()
        self.env = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "CN_SANDBOX_HUB_PORT": str(self.port)}
        self.pidf = self.home / ".codenow" / "sandbox-hub" / "hub.pid"

    def tearDown(self):
        self.run_cn("hub", "--stop")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cn(self, *args, cwd=None, **env):
        return subprocess.run(["/bin/bash", str(CN_SANDBOX), *args], cwd=cwd or self.home, env={**self.env, **env},
                              capture_output=True, text=True, timeout=30)

    def get(self, path, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                         headers={"Host": host or f"localhost:{self.port}"})
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, answer.read().decode()

    def test_start_status_stop(self):
        out = self.run_cn("hub")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn(f"http://localhost:{self.port}/", out.stdout)
        pid = int(self.pidf.read_text())
        os.kill(pid, 0)
        self.assertIn("already running", self.run_cn("hub").stdout)
        status = self.run_cn("hub", "--status")
        self.assertEqual(status.returncode, 0)
        self.assertIn(f"pid {pid}", status.stdout)
        self.assertEqual(json.loads(self.get("/api/sandboxes")[1]), {"sandboxes": []})
        self.assertIn("No sandbox runs", self.get("/")[1])
        with self.assertRaises(urllib.error.HTTPError) as refused:
            self.get("/api/sandboxes", host="evil.example")
        self.assertEqual(refused.exception.code, 403)
        out = self.run_cn("hub", "--stop")
        self.assertIn("stopped", out.stdout)
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the hub still runs")
        self.assertFalse(self.pidf.exists())
        status = self.run_cn("hub", "--status")
        self.assertEqual(status.returncode, 1)
        self.assertIn("not running", status.stdout)

    def test_a_stale_pid_file_is_not_the_hub(self):
        self.pidf.parent.mkdir(parents=True)
        self.pidf.write_text(str(os.getpid()))   # alive, but not cn_hub.py
        self.assertEqual(self.run_cn("hub", "--status").returncode, 1)
        out = self.run_cn("hub")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotEqual(int(self.pidf.read_text()), os.getpid())

    def test_a_port_taken_by_another_program(self):
        with socket.socket() as other:
            other.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            other.bind(("127.0.0.1", self.port))
            other.listen(1)
            out = self.run_cn("hub")
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"port {self.port} is taken by another program", out.stderr)
        self.assertIn("CN_SANDBOX_HUB_PORT", out.stderr)
        self.assertFalse(self.pidf.exists())

    def test_wrong_option(self):
        out = self.run_cn("hub", "--bogus")
        self.assertEqual(out.returncode, 2)

    def repo(self) -> pathlib.Path:
        repo = self.tmp / "agent"
        (repo / "sandbox").mkdir(parents=True)
        (repo / "sandbox" / "sandbox.sh").write_text(SANDBOX_STUB)
        (repo / ".env").write_text("CN_IDENTITY_PROVIDER=legacy-refresh-token\n")
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=self.env)
        return repo

    def test_up_starts_the_hub_and_prints_its_url(self):
        repo = self.repo()
        out = self.run_cn("up", cwd=repo)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("console: ", out.stdout)
        self.assertIn(f"sandboxes: http://localhost:{self.port}/", out.stdout)
        self.assertEqual(self.run_cn("hub", "--status").returncode, 0)
        again = self.run_cn("up", cwd=repo)
        self.assertIn(f"sandboxes: http://localhost:{self.port}/", again.stdout)
        self.assertEqual(again.stdout.count("sandboxes:"), 1)

    def test_up_with_the_hub_off(self):
        out = self.run_cn("up", cwd=self.repo(), CN_SANDBOX_HUB="off")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("sandboxes:", out.stdout)
        self.assertFalse(self.pidf.exists())


if __name__ == "__main__":
    unittest.main()
