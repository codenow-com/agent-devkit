#!/usr/bin/env python3
"""The sandbox hub of the CodeNOW agent devkit: one local page with every agent sandbox on this computer.

    python3 lib/cn_hub.py [--port 8079]      serve http://localhost:<port>/ (127.0.0.1 only) until stopped
    python3 lib/cn_hub.py --ping [--port P]  exit 0 when a sandbox hub answers on that port
    python3 lib/cn_hub.py --json             print the collected sandboxes once and exit

Routes: `/` the page, `/cards` the cards alone (the page reloads them every 5 s), `/api/sandboxes` the JSON,
`/api/hub` the hub's own name (for --ping). The data comes from Docker only (the compose projects named sandbox-*,
their labels, states, ports and the agent's log) and from the sandbox's own state files in the agent repository
(sandbox/.run/allow, sandbox/.run/port). It never reads a token: from .env it keeps only four non-secret keys, and
everything that looks like a token is masked before it leaves this process. Standard library only.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cn_hub_render as render  # noqa: E402  (next to this file)

HUB_NAME = "cn-sandbox-hub"
PREFIX = "sandbox-"
ENV_KEYS = ("CN_IDENTITY_PROVIDER", "CN_IDENTITY_DEVELOPER_CLIENTS", "WORKFORCE_URL", "WORKFORCE_MODE")
LOG_TAIL = "3000"
CORE_SERVICES = ("agent", "edge", "egress", "runstore", "valkey")

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")
_ASSIGN = re.compile(r"(?i)\b([A-Z0-9_]*(?:token|secret|password|passwd|api_key|apikey)[A-Z0-9_]*)\s*([=:])\s*[^\s,;)]+")
_LONG = re.compile(r"\b[A-Za-z0-9_-]{48,}\b")


def mask(text: str) -> str:
    """Everything that may be a credential, replaced: JWTs, bearer values, KEY=value of secret-like keys."""
    text = _JWT.sub("<token>", text)
    text = _BEARER.sub(r"\1 <token>", text)
    return _ASSIGN.sub(r"\1\2<masked>", text)


def mask_log(text: str) -> str:
    """A log line: mask(), and every long opaque string as well."""
    return _LONG.sub("<masked>", mask(text))


def mask_all(value):
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [mask_all(v) for v in value]
    if isinstance(value, dict):
        return {k: mask_all(v) for k, v in value.items()}
    return value


def run_docker(*args: str) -> str:
    """One docker command; its stdout and stderr together (docker logs writes to both), or "" when it fails."""
    try:
        out = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout + out.stderr


def env_values(env_file: pathlib.Path) -> dict:
    """Only the four non-secret keys of the agent's .env; every other line is skipped unread."""
    values = {}
    try:
        lines = env_file.read_text(errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in ENV_KEYS:
            values[key] = value.strip().strip("'\"")
    return values


def host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def read_allow(repo: pathlib.Path) -> list:
    """The egress allowlist that sandbox.sh wrote (sandbox/.run/allow: one ^host$ regular expression per line)."""
    try:
        lines = (repo / "sandbox" / ".run" / "allow").read_text().splitlines()
    except OSError:
        return []
    hosts = []
    for line in lines:
        host = line.strip().lstrip("^").rstrip("$").replace("\\.", ".")
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def host_kind(host: str, workforce_host: str) -> str:
    lower = host.lower()
    if workforce_host and lower == workforce_host.lower():
        return "observer (Workforce)"
    if "gateway" in lower or lower.startswith("agw"):
        return "agent gateway (models, MCP)"
    if lower.startswith(("iam.", "keycloak", "auth.", "sso.")) or ".iam." in lower:
        return "IAM (tokens)"
    if "mcp" in lower:
        return "MCP server"
    if "observer" in lower or "workforce" in lower:
        return "observer (Workforce)"
    return "allowed host (connector, A2A peer)"


def sdk_version(repo: pathlib.Path):
    try:
        text = (repo / "requirements.txt").read_text()
    except OSError:
        return None
    found = re.search(r"^\s*codenow-agent-sdk\s*==\s*([0-9][0-9A-Za-z.+-]*)", text, re.M)
    return found.group(1) if found else None


def identity_of(log: str, env: dict) -> dict:
    adapter = None
    for found in re.finditer(r"identity: adapter ([A-Za-z0-9_.-]+)", log):
        adapter = found.group(1)
    source = "log"
    if adapter is None:
        adapter, source = env.get("CN_IDENTITY_PROVIDER") or None, ".env"
    if adapter is None:
        return {"mode": "unknown", "adapter": None, "label": "identity unknown", "source": None}
    labels = {"developer": "as you (developer)", "legacy-refresh-token": "deployment token",
              "dev": "dev identity provider", "devidp": "dev identity provider"}
    mode = adapter if adapter in ("developer", "legacy-refresh-token") else "other"
    return {"mode": mode, "adapter": adapter, "label": labels.get(adapter, adapter), "source": source}


def workforce_of(log: str, env: dict) -> dict:
    line = None
    for raw in log.splitlines():
        if "Workforce: onboarding" in raw or "Workforce: developer identity" in raw \
                or "Workforce is not configured" in raw or "Workforce: offboarded" in raw:
            line = raw
    state = "unknown"
    if line is None:
        state = "not configured" if not env.get("WORKFORCE_URL") else "unknown"
    elif "onboarding approved" in line:
        state = "approved"
    elif "Workforce: onboarding" in line:
        found = re.search(r"Workforce: onboarding (\w+)", line)
        state = found.group(1) if found else "pending"
    elif "developer identity" in line:
        state = "no mandate (developer)"
    elif "not configured" in line:
        state = "not configured"
    elif "offboarded" in line:
        state = "offboarded"
    text = None
    if line is not None:
        text = line[line.find("Workforce"):].strip()
    instance = re.search(r"instance ([^,)\s]+)", text or "")
    return {"state": state, "line": mask_log(text) if text else None,
            "instance": instance.group(1) if instance else None,
            "url_host": host_of(env.get("WORKFORCE_URL", "")) or None, "mode": env.get("WORKFORCE_MODE") or None}


def token_refresh(home: pathlib.Path) -> dict:
    """The devkit's background refresh: is watch.pid alive, how old is the token file (its time, never its content)."""
    folder = home / "sandbox-token"
    info = {"watch_running": False, "watch_pid": None, "token_age_s": None, "registry": None, "projects": []}
    try:
        pid = int((folder / "watch.pid").read_text().strip())
        os.kill(pid, 0)
        command = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                                 timeout=5).stdout
        if "token --watch" in command:
            info["watch_running"], info["watch_pid"] = True, pid
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    try:
        info["token_age_s"] = int(time.time() - (folder / "token").stat().st_mtime)
    except OSError:
        pass
    registry = folder / "users"   # devkit 0.1.13+: one file per sandbox that uses the refresh (repository, project)
    if registry.is_dir():
        entries = [p for p in registry.iterdir() if p.is_file() and not p.name.startswith(".")]
        info["registry"] = len(entries)
        for entry in entries:
            try:
                lines = entry.read_text(errors="replace").splitlines()
            except OSError:
                continue
            if len(lines) > 1 and lines[1].strip():
                info["projects"].append(lines[1].strip())
    return info


def published_port(container: dict, private: str = "8080/tcp"):
    for key in ("NetworkSettings", "HostConfig"):
        ports = (container.get(key) or {}).get("Ports" if key == "NetworkSettings" else "PortBindings") or {}
        for binding in ports.get(private) or []:
            if binding.get("HostPort"):
                return binding.get("HostIp") or "127.0.0.1", int(binding["HostPort"])
    return None, None


def collect(docker=run_docker, codenow_home: pathlib.Path | None = None) -> list:
    """Every compose project named sandbox-* on this Docker, as one dict per sandbox (no secret in it)."""
    home = codenow_home or pathlib.Path(os.environ.get("CODENOW_HOME") or pathlib.Path.home() / ".codenow")
    ids = []
    for line in docker("ps", "-a", "--filter", "label=com.docker.compose.project", "--format", "{{json .}}").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("ID"):
            ids.append(row["ID"])
    containers = []
    if ids:
        try:
            containers = json.loads(docker("inspect", *ids) or "[]")
        except ValueError:
            containers = []
    projects = {}
    for container in containers:
        labels = (container.get("Config") or {}).get("Labels") or {}
        project = labels.get("com.docker.compose.project", "")
        if project.startswith(PREFIX):
            projects.setdefault(project, []).append(container)
    refresh = token_refresh(home)
    sandboxes = [one_sandbox(project, items, docker, refresh) for project, items in sorted(projects.items())]
    return mask_all(sandboxes)


def one_sandbox(project: str, containers: list, docker, refresh: dict) -> dict:
    services, agent, edge, working_dir = {}, None, None, ""
    for container in containers:
        labels = container["Config"].get("Labels") or {}
        name = labels.get("com.docker.compose.service", "?")
        state = (container.get("State") or {}).get("Status", "unknown")
        services[name] = {"state": state, "container": (container.get("Name") or "").lstrip("/")}
        working_dir = working_dir or labels.get("com.docker.compose.project.working_dir", "")
        if name == "agent":
            agent = container
        elif name == "edge":
            edge = container
    repo = pathlib.Path(working_dir)
    if repo.name == "sandbox":
        repo = repo.parent
    env = env_values(repo / ".env") if working_dir else {}
    host, port = published_port(edge) if edge else (None, None)
    if port is None and working_dir:
        try:
            port = int((repo / "sandbox" / ".run" / "port").read_text().strip())
        except (OSError, ValueError):
            port = None
    running = [s for s in services.values() if s["state"] == "running"]
    status = "running" if len(running) == len(services) else ("stopped" if not running else "partial")
    log = docker("logs", "--tail", LOG_TAIL, agent["Id"]) if agent and agent.get("Id") else ""
    workforce = workforce_of(log, env)
    allow = read_allow(repo) if working_dir else []
    order = [s for s in CORE_SERVICES if s in services] + sorted(s for s in services if s not in CORE_SERVICES)
    return {
        "name": project[len(PREFIX):],
        "project": project,
        "repo": str(repo) if working_dir else None,
        "status": status,
        "services": [{"name": s, **services[s]} for s in order],
        "console": {"host": host, "port": port, "url": f"http://localhost:{port}/" if port else None},
        "identity": identity_of(log, env),
        "workforce": workforce,
        "egress": [{"host": h, "kind": host_kind(h, workforce["url_host"] or "")} for h in allow],
        "token_refresh": {**{k: v for k, v in refresh.items() if k != "projects"},
                          "uses_it": project in refresh.get("projects", [])},
        "sdk_version": sdk_version(repo) if working_dir else None,
        "env": {k: env[k] for k in ENV_KEYS if k in env and k != "CN_IDENTITY_DEVELOPER_CLIENTS"}
        | ({"CN_IDENTITY_DEVELOPER_CLIENTS": "set"} if env.get("CN_IDENTITY_DEVELOPER_CLIENTS") else {}),
    }


class Cache:
    """Collects at most every 2 s, however many browser tabs ask."""

    def __init__(self, collector, ttl: float = 2.0):
        self.collector, self.ttl, self.lock, self.at, self.value = collector, ttl, threading.Lock(), 0.0, []

    def get(self) -> list:
        with self.lock:
            if time.monotonic() - self.at > self.ttl:
                self.value, self.at = self.collector(), time.monotonic()
            return self.value


def make_handler(cache: Cache, port: int):
    allowed_hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = HUB_NAME

        def log_message(self, fmt, *args):  # quiet: the log file keeps only errors
            pass

        def send(self, code: int, body: str, kind: str) -> None:
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'; img-src data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            # A page on another site must not read this one through a DNS name pointed at 127.0.0.1.
            if self.headers.get("Host", "") not in allowed_hosts:
                self.send(403, "forbidden host\n", "text/plain; charset=utf-8")
                return
            path = urlparse(self.path).path
            if path == "/api/hub":
                self.send(200, json.dumps({"hub": HUB_NAME}), "application/json")
            elif path == "/api/sandboxes":
                self.send(200, json.dumps({"sandboxes": cache.get()}, indent=1), "application/json")
            elif path == "/cards":
                self.send(200, render.cards(cache.get()), "text/html; charset=utf-8")
            elif path == "/":
                self.send(200, render.page(cache.get()), "text/html; charset=utf-8")
            else:
                self.send(404, "not found\n", "text/plain; charset=utf-8")

    return Handler


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def ping(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/hub", timeout=1) as answer:
            return json.loads(answer.read().decode()).get("hub") == HUB_NAME
    except (OSError, ValueError):
        return False


def serve(port: int) -> int:
    if port_in_use(port):
        print(f"cn_hub: port {port} is in use", file=sys.stderr)
        return 3
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Cache(collect), port))
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(f"cn_hub: port {port} is in use", file=sys.stderr)
            return 3
        raise
    server.daemon_threads = True
    print(f"cn_hub: serving http://localhost:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cn_hub.py")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CN_SANDBOX_HUB_PORT") or 8079))
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.ping:
        return 0 if ping(args.port) else 1
    if args.json:
        print(json.dumps({"sandboxes": collect()}, indent=1))
        return 0
    return serve(args.port)


if __name__ == "__main__":
    sys.exit(main())
