"""A small client of the CodeNOW MCP server for the cn-call and cn-wait commands.

It talks JSON-RPC over HTTP to the server in ~/.codenow/config (CODENOW_MCP_URL) with the API key from
CODENOW_API_KEY or ~/.codenow/credentials. It uses the Python standard library only.

    cn_mcp.py call <tool> [json arguments]
    cn_mcp.py wait build <swarm> <agent> [build id] [--max seconds]
    cn_mcp.py wait deploy <swarm> <environment> [--max seconds]

Exit codes of wait: 0 done, 1 failed or error, 3 still running after --max seconds (run it again).
"""
import json
import os
import pathlib
import shlex
import sys
import time
import urllib.error
import urllib.request

HOME = pathlib.Path(os.environ.get("CODENOW_HOME", pathlib.Path.home() / ".codenow"))
POLL_SECONDS = 10
DEFAULT_MAX_SECONDS = 50  # stays under the time limit that assistants put on one tool call
BUILD_DONE = {"BUILD_FINISHED", "SUCCESSFUL"}
DEPLOY_DONE = {"HEALTHY"}
FAILED_WORDS = ("FAIL", "ERROR", "CANCEL")


class CnError(Exception):
    pass


def read_settings(path):
    """Reads NAME=value lines (shell format, as save_setting writes them)."""
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, _, raw = line.partition("=")
                parts = shlex.split(raw) if raw.strip() else [""]
                values[name.strip()] = parts[0] if parts else ""
    return values


def settings():
    config = read_settings(HOME / "config")
    url = os.environ.get("CODENOW_MCP_URL") or config.get("CODENOW_MCP_URL", "")
    key = os.environ.get("CODENOW_API_KEY") or read_settings(HOME / "credentials").get("CODENOW_API_KEY", "")
    if not url:
        raise CnError("no CODENOW_MCP_URL: run cn-setup")
    if not key:
        raise CnError("no CodeNOW API key: run  CODENOW_API_KEY=<key> cn-setup  (CodeNOW profile > API keys)")
    return url, key


class Client:
    def __init__(self, url, key):
        self.url, self.key, self.session, self.next_id = url, key, None, 1

    def _post(self, body):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "X-Codenow-Api-Key": self.key}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                self.session = response.headers.get("Mcp-Session-Id") or self.session
                text = response.read().decode()
        except urllib.error.HTTPError as error:
            raise CnError(f"CodeNOW MCP server answered HTTP {error.code}") from None
        except urllib.error.URLError as error:
            raise CnError(f"cannot reach the CodeNOW MCP server: {error.reason}") from None
        if not text.strip():
            return None
        if text.lstrip().startswith("event:") or text.lstrip().startswith("data:"):
            text = "\n".join(line[5:].strip() for line in text.splitlines() if line.startswith("data:"))
        return json.loads(text)

    def rpc(self, method, params=None):
        body = {"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}
        self.next_id += 1
        answer = self._post(body)
        if answer.get("error"):
            raise CnError(answer["error"].get("message", "MCP error"))
        return answer.get("result")

    def start(self):
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "codenow-agent-devkit", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def call(self, tool, arguments):
        result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        text = "".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text")
        if result.get("isError"):
            raise CnError(f"{tool}: {text.strip()[:500]}")
        try:
            return json.loads(text)
        except ValueError:
            return text


def connect():
    return Client(*settings()).start()


def say(message):
    print(f"cn-wait: {message}", flush=True)


def failed(status):
    return any(word in (status or "").upper() for word in FAILED_WORDS)


def wait_build(client, swarm, agent, build_id, max_seconds):
    if not build_id:
        page = client.call("agents_builds_list", {"agentSwarmId": swarm, "agentId": agent, "size": 1})
        builds = page.get("content", []) if isinstance(page, dict) else []
        if not builds:
            raise CnError(f"agent {swarm}/{agent} has no build")
        build_id = builds[0]["id"]
    seen_status, seen_results, first = None, set(), True
    deadline = time.monotonic() + max_seconds
    while True:
        build = client.call("agents_builds_detail", {"agentSwarmId": swarm, "agentId": agent, "id": build_id,
                                                     "expand": ["results"]})
        status = build.get("status")
        if first:
            say(f"build {build.get('buildType', '')} {build.get('version', '')} of {agent}, {build.get('url', '')}")
            first = False
        results = [r.get("type") for r in build.get("results") or []]
        new = [r for r in results if r not in seen_results]
        if status != seen_status or new:
            say(f"{status}" + (f", done: {', '.join(results)}" if results else ""))
            seen_status, seen_results = status, set(results)
        if status in BUILD_DONE:
            say(f"build finished: {status}")
            return 0
        if failed(status):
            say(f"build failed: {status}; see {build.get('url', '')}")
            return 1
        if time.monotonic() + POLL_SECONDS > deadline:
            say(f"still {status}: run  cn-wait build {swarm} {agent} {build_id}  again")
            return 3
        time.sleep(POLL_SECONDS)


def wait_deploy(client, swarm, environment, max_seconds):
    seen_status = None
    deadline = time.monotonic() + max_seconds
    while True:
        detail = client.call("agent_swarm_deployment_detail", {"agentSwarmId": swarm, "environmentId": environment})
        deployment = (detail or {}).get("deployment") or {}
        status = deployment.get("status")
        if not deployment:
            raise CnError(f"swarm {swarm} has no deployment in {environment}")
        if status != seen_status:
            say(f"deployment {deployment.get('version', '')} of {swarm} in {environment}: {status}")
            seen_status = status
        if status in DEPLOY_DONE:
            say("deployment is HEALTHY: the agent's Secret exists, .env and the sandbox can go on")
            return 0
        if failed(status):
            say(f"deployment failed: {status}; see {deployment.get('dashboardUrl', '')}")
            return 1
        if time.monotonic() + POLL_SECONDS > deadline:
            say(f"still {status}: run  cn-wait deploy {swarm} {environment}  again")
            return 3
        time.sleep(POLL_SECONDS)


def split_max(args):
    max_seconds = DEFAULT_MAX_SECONDS
    if "--max" in args:
        at = args.index("--max")
        max_seconds = int(args[at + 1])
        args = args[:at] + args[at + 2:]
    return args, max_seconds


def main(argv):
    if len(argv) >= 2 and argv[0] == "call":
        arguments = json.loads(argv[2]) if len(argv) > 2 else {}
        result = connect().call(argv[1], arguments)
        print(json.dumps(result, indent=2, ensure_ascii=False) if not isinstance(result, str) else result)
        return 0
    if len(argv) >= 2 and argv[0] == "wait":
        args, max_seconds = split_max(argv[1:])
        if args[0] == "build" and len(args) in (3, 4):
            return wait_build(connect(), args[1], args[2], args[3] if len(args) == 4 else None, max_seconds)
        if args[0] == "deploy" and len(args) == 3:
            return wait_deploy(connect(), args[1], args[2], max_seconds)
    print(__doc__.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except CnError as error:
        print(f"cn: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
