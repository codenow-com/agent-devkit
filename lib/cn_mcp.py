"""A small client of the CodeNOW MCP server for the cn-call and cn-wait commands.

It talks JSON-RPC over HTTP to the server in ~/.codenow/config (CODENOW_MCP_URL) with the API key from
CODENOW_API_KEY or ~/.codenow/credentials. It uses the Python standard library only.

    cn_mcp.py call <tool> [json object of arguments]
    cn_mcp.py wait build <swarm> <agent> [build id] [--max seconds]
    cn_mcp.py wait deploy <swarm> <environment> [--max seconds]
    cn_mcp.py save-key      (cn-setup: checks CODENOW_API_KEY against the server, then saves it)

Exit codes: 0 done, 1 the build or deployment failed, 2 error (usage, setup, network, server),
3 still running after --max seconds (run it again).
"""
import http.client
import json
import os
import pathlib
import shlex
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

POLL_SECONDS = 10
DEFAULT_MAX_SECONDS = 50  # stays under the time limit that assistants put on one tool call
REQUEST_SECONDS = 30
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
# Status sets. Seen on a live tenant: builds INITIALISING, BUILDING, SUCCESSFUL, FAILED; deployments
# HEALTHY, UPDATING, FAILED_TO_UPDATE. Other values are a guess, so the rule is conservative: done ends with 0,
# a known running status goes on, and any other status ends with 1 and is printed. No status yet counts as running.
BUILD_DONE = {"BUILD_FINISHED", "SUCCESSFUL", "SUCCEEDED", "SUCCESS", "FINISHED", "COMPLETED"}
BUILD_RUNNING = {"INITIALISING", "INITIALIZING", "QUEUED", "PENDING", "CREATED", "SCHEDULED", "WAITING", "STARTED", "STARTING", "RUNNING",
                 "IN_PROGRESS", "BUILDING", "BUILD_STARTED", "BUILD_RUNNING", "BUILD_QUEUED", "BUILD_PENDING"}
DEPLOY_DONE = {"HEALTHY"}
DEPLOY_RUNNING = {"UPDATING", "PENDING", "QUEUED", "CREATED", "PROGRESSING", "DEPLOYING", "IN_PROGRESS", "RUNNING", "SYNCING",
                  "OUT_OF_SYNC", "MISSING", "STARTING"}
EXIT_DONE, EXIT_FAILED, EXIT_ERROR, EXIT_RUNNING = 0, 1, 2, 3


class CnError(Exception):
    pass


class OutOfTime(CnError):
    pass


def home():
    return pathlib.Path(os.environ.get("CODENOW_HOME") or pathlib.Path.home() / ".codenow")


def read_settings(path):
    """Reads NAME=value lines (shell format, as save_setting writes them)."""
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, _, raw = line.partition("=")
                try:
                    parts = shlex.split(raw) if raw.strip() else [""]
                except ValueError:
                    raise CnError(f"{path}: the line of {name.strip()} cannot be read") from None
                values[name.strip()] = parts[0] if parts else ""
    return values


def clean_key(key):
    """Strips spaces and line ends; a key is printable ASCII without spaces. Never puts the key in a message."""
    key = (key or "").strip()
    if key and not all("!" <= c <= "~" for c in key):
        raise CnError("the CodeNOW API key has spaces or characters that are not printable ASCII: copy it again")
    return key


def check_url(url):
    """https only; http only for this computer (a local test server)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "https" and parsed.hostname:
        return url
    if parsed.scheme == "http" and (parsed.hostname or "") in LOCAL_HOSTS:
        return url
    raise CnError("CODENOW_MCP_URL must start with https:// (http:// only for localhost): run cn-setup")


def mcp_url():
    url = (os.environ.get("CODENOW_MCP_URL") or read_settings(home() / "config").get("CODENOW_MCP_URL", "")).strip()
    if not url:
        raise CnError("CODENOW_MCP_URL is not set: run cn-setup and give the MCP URL of your tenant")
    return check_url(url)


def settings():
    url = mcp_url()
    key = clean_key(os.environ.get("CODENOW_API_KEY")
                    or read_settings(home() / "credentials").get("CODENOW_API_KEY", ""))
    if not key:
        raise CnError("no CodeNOW API key: run  CODENOW_API_KEY=<key> cn-setup  (CodeNOW profile > API keys)")
    return url, key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could send the API key to another host (or from https to http): refuse it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # urllib then raises HTTPError with the 3xx code


OPENER = urllib.request.build_opener(NoRedirect)


def parse_answer(text, content_type, request_id):
    """The JSON-RPC answer to request_id, from a JSON body or an SSE stream with one or more events."""
    stripped = text.lstrip()
    if "text/event-stream" in content_type or stripped.startswith(("event:", "data:", "id:", ":")):
        messages = []
        for event in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip(" ") for line in event.split("\n") if line.startswith("data:"))
            if data.strip():
                try:
                    messages.append(json.loads(data))
                except ValueError:
                    raise CnError("the CodeNOW MCP server sent an event that is not JSON") from None
    else:
        try:
            messages = [json.loads(text)]
        except ValueError:
            raise CnError(f"the CodeNOW MCP server answered with something that is not JSON "
                          f"({content_type or 'no content type'})") from None
    batch = [m for item in messages for m in (item if isinstance(item, list) else [item])]
    for message in batch:
        if isinstance(message, dict) and message.get("id") == request_id and ("result" in message
                                                                              or "error" in message):
            return message
    raise CnError("the CodeNOW MCP server sent no answer to the request")


class Client:
    def __init__(self, url, key, deadline=None):
        self.url, self.key, self.session, self.next_id, self.deadline = url, key, None, 1, deadline

    def _timeout(self):
        if self.deadline is None:
            return REQUEST_SECONDS
        left = self.deadline - time.monotonic()
        if left < 1:
            raise OutOfTime("out of time")
        return min(REQUEST_SECONDS, left)

    def _send(self, method, body=None, timeout=None):
        headers = {"X-Codenow-Api-Key": self.key}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url, data, headers, method=method)
        try:
            with OPENER.open(request, timeout=timeout or self._timeout()) as response:
                self.session = response.headers.get("Mcp-Session-Id") or self.session
                return response.read().decode("utf-8", "replace"), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            if 300 <= error.code < 400:
                raise CnError(f"the CodeNOW MCP server answered with a redirect (HTTP {error.code}); cn-call does "
                              f"not follow redirects: check CODENOW_MCP_URL in ~/.codenow/config") from None
            if error.code in (401, 403):
                raise CnError(f"the CodeNOW MCP server refused the API key (HTTP {error.code}): "
                              f"run  CODENOW_API_KEY=<key> cn-setup") from None
            raise CnError(f"the CodeNOW MCP server answered HTTP {error.code}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, (socket.timeout, TimeoutError)):
                raise OutOfTime("the CodeNOW MCP server did not answer in time") from None
            raise CnError(f"cannot reach the CodeNOW MCP server: {error.reason}") from None
        except (socket.timeout, TimeoutError):
            raise OutOfTime("the CodeNOW MCP server did not answer in time") from None
        except (http.client.HTTPException, ConnectionError, OSError) as error:
            raise CnError(f"the connection to the CodeNOW MCP server broke: {type(error).__name__}") from None

    def rpc(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        text, content_type = self._send("POST", body)
        if not text.strip():
            raise CnError(f"the CodeNOW MCP server sent an empty answer to {method}")
        answer = parse_answer(text, content_type, request_id)
        if answer.get("error"):
            error = answer["error"]
            raise CnError(str(error.get("message", "MCP error") if isinstance(error, dict) else error)[:500])
        return answer.get("result")

    def start(self):
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "codenow-agent-devkit", "version": "1"}})
        self._send("POST", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def close(self):
        """Ends the MCP session (HTTP DELETE); errors do not matter."""
        if not self.session:
            return
        try:
            left = 2 if self.deadline is None else self.deadline - time.monotonic()
            self._send("DELETE", timeout=max(0.5, min(2, left)))
        except Exception:
            pass
        self.session = None

    def call(self, tool, arguments):
        result = self.rpc("tools/call", {"name": tool, "arguments": arguments})
        if not isinstance(result, dict):
            raise CnError(f"{tool}: the server answered without a result")
        content = result.get("content") if isinstance(result.get("content"), list) else []
        text = "".join(str(part.get("text", "")) for part in content
                       if isinstance(part, dict) and part.get("type") == "text")
        if result.get("isError"):
            raise CnError(f"{tool}: {text.strip()[:500]}")
        if not text.strip() and isinstance(result.get("structuredContent"), (dict, list)):
            return result["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return text


def say(message):
    print(f"cn-wait: {message}", flush=True)


def wait_status(status, done, running):
    """done, running or failed for a status (None or empty: no status yet, counts as running)."""
    status = (status or "").upper()
    if status in done:
        return "done"
    if not status or status in running:
        return "running"
    return "failed"


def left_for_poll(deadline):
    return time.monotonic() + POLL_SECONDS <= deadline


def wait_build(client, swarm, agent, build_id, deadline):
    if not build_id:
        page = client.call("agents_builds_list", {"agentSwarmId": swarm, "agentId": agent, "size": 1})
        builds = page.get("content") if isinstance(page, dict) else None
        if not builds or not isinstance(builds, list) or not isinstance(builds[0], dict):
            raise CnError(f"agent {swarm}/{agent} has no build")
        build_id = builds[0].get("id")
        if not build_id:
            raise CnError(f"the newest build of {swarm}/{agent} has no id")
    seen_status, seen_results, first = object(), set(), True
    while True:
        build = client.call("agents_builds_detail", {"agentSwarmId": swarm, "agentId": agent, "id": build_id,
                                                     "expand": ["results"]})
        if not isinstance(build, dict):
            raise CnError(f"build {build_id} of {swarm}/{agent}: the server sent no build detail")
        status = build.get("status")
        if first:
            say(f"build {build.get('buildType', '')} {build.get('version', '')} of {agent}, {build.get('url', '')}")
            first = False
        results = [str(r.get("type")) for r in build.get("results") or [] if isinstance(r, dict)]
        if status != seen_status or set(results) - seen_results:
            say(f"{status}" + (f", done: {', '.join(results)}" if results else ""))
            seen_status, seen_results = status, set(results)
        state = wait_status(status, BUILD_DONE, BUILD_RUNNING)
        if state == "done":
            say(f"build finished: {status}")
            return EXIT_DONE
        if state == "failed":
            say(f"build ended with status {status} (failed or not known as running); see {build.get('url', '')}")
            return EXIT_FAILED
        if not left_for_poll(deadline):
            say(f"still {status}: run  cn-wait build {swarm} {agent} {build_id}  again")
            return EXIT_RUNNING
        time.sleep(POLL_SECONDS)


def wait_deploy(client, swarm, environment, deadline):
    seen_status = object()
    while True:
        detail = client.call("agent_swarm_deployment_detail", {"agentSwarmId": swarm, "environmentId": environment})
        deployment = detail.get("deployment") if isinstance(detail, dict) else None
        if not isinstance(deployment, dict) or not deployment:
            raise CnError(f"swarm {swarm} has no deployment in {environment}")
        status = deployment.get("status")
        if status != seen_status:
            say(f"deployment {deployment.get('version', '')} of {swarm} in {environment}: {status}")
            seen_status = status
        state = wait_status(status, DEPLOY_DONE, DEPLOY_RUNNING)
        if state == "done":
            say("deployment is HEALTHY: the agent's Secret exists, .env and the sandbox can go on")
            return EXIT_DONE
        if state == "failed":
            say(f"deployment ended with status {status} (failed or not known as running); "
                f"see {deployment.get('dashboardUrl', '')}")
            return EXIT_FAILED
        if not left_for_poll(deadline):
            say(f"still {status}: run  cn-wait deploy {swarm} {environment}  again")
            return EXIT_RUNNING
        time.sleep(POLL_SECONDS)


class UsageError(CnError):
    pass


def split_max(args):
    max_seconds = DEFAULT_MAX_SECONDS
    if "--max" in args:
        at = args.index("--max")
        try:
            max_seconds = int(args[at + 1])
        except (IndexError, ValueError):
            raise UsageError("--max needs a whole number of seconds") from None
        if not 1 <= max_seconds <= 3600:
            raise UsageError("--max must be between 1 and 3600 seconds")
        args = args[:at] + args[at + 2:]
    return args, max_seconds


def save_key():
    """Checks CODENOW_API_KEY against the server and only then replaces ~/.codenow/credentials (mode 600)."""
    key = clean_key(os.environ.get("CODENOW_API_KEY"))
    if not key:
        raise UsageError("CODENOW_API_KEY is empty")
    client = Client(mcp_url(), key, deadline=time.monotonic() + REQUEST_SECONDS)
    try:
        client.start().call("agent_swarms_list", {})
    except CnError as error:
        raise CnError(f"the new API key does not work, the stored key stays: {error}") from None
    finally:
        client.close()
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=".credentials.")  # mode 600
    try:
        with os.fdopen(fd, "w") as out:
            out.write(f"CODENOW_API_KEY={shlex.quote(key)}\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(folder / "credentials"))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"cn-setup: the API key works; saved it for cn-call and cn-wait in {folder / 'credentials'} (mode 600)")
    return EXIT_DONE


def run(argv):
    started = time.monotonic()
    if argv == ["save-key"]:
        return save_key()
    if argv and argv[0] == "call" and len(argv) in (2, 3):
        try:
            arguments = json.loads(argv[2]) if len(argv) == 3 else {}
        except ValueError as error:
            raise UsageError(f"the arguments are not valid JSON: {error}") from None
        if not isinstance(arguments, dict):
            raise UsageError('the arguments must be a JSON object, for example  \'{"agentSwarmId": "<swarm>"}\'')
        client = Client(*settings())
        try:
            result = client.start().call(argv[1], arguments)
        finally:
            client.close()
        print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))
        return EXIT_DONE
    if argv and argv[0] == "wait":
        args, max_seconds = split_max(argv[1:])
        deadline = started + max_seconds
        if args and args[0] == "build" and len(args) in (3, 4):
            target = lambda client: wait_build(client, args[1], args[2], args[3] if len(args) == 4 else None,
                                               deadline)
            again = f"cn-wait build {' '.join(args[1:])}"
        elif args and args[0] == "deploy" and len(args) == 3:
            target = lambda client: wait_deploy(client, args[1], args[2], deadline)
            again = f"cn-wait deploy {args[1]} {args[2]}"
        else:
            raise UsageError("wrong arguments")
        client = Client(*settings(), deadline=deadline)
        try:
            return target(client.start())
        except OutOfTime as error:
            if time.monotonic() < deadline - 1:
                raise CnError(str(error)) from None
            say(f"no answer within {max_seconds} s: run  {again}  again")
            return EXIT_RUNNING
        finally:
            client.close()
    raise UsageError("wrong arguments")


def scrub(text):
    """Error lines never show the API key."""
    key = (os.environ.get("CODENOW_API_KEY") or "").strip()
    if key:
        text = text.replace(key, "***")
    return " ".join(text.split())


def main(argv):
    try:
        return run(argv)
    except UsageError as error:
        print(f"cn: {scrub(str(error))}\n\n{__doc__.strip()}", file=sys.stderr)
    except CnError as error:
        print(f"cn: {scrub(str(error))}", file=sys.stderr)
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # a last guard: one line, no traceback
        print(f"cn: unexpected error: {type(error).__name__}: {scrub(str(error))[:300]}", file=sys.stderr)
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
