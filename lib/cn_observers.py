"""Finds the swarm observers (Workforce) of the tenant for cn-setup: their public URLs, one per line.

    cn_observers.py          prints "<url> <swarm>/<agent>" for each observer that answers; nothing when none

It reads the CodeNOW MCP server with read tools only (agent_swarms_list, agents_list, agent_swarm_deployments_list).
With CN_MCP_BEARER_STDIN=1 it sends the developer's access token read from stdin; else the API key of cn-call.
Exit codes: 0 done (also when nothing was found), 2 error (one line on stderr, never the token or the key).
"""
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cn_mcp  # noqa: E402

OBSERVER_TEMPLATE = "ai-swarm-observer"
PROBE_SECONDS = 8


def as_list(value):
    """A list from a tool's answer: a JSON list, or the list under content/items/data of a page."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for name in ("content", "items", "data"):
            if isinstance(value.get(name), list):
                return as_list(value[name])
    return []


def observer_url(agent, swarm, dashboard_url):
    """The public URL of an agent in a swarm deployment: <scheme>://<agent>-<swarm>.<cluster domain>. The cluster
    domain is the host of the deployment's dashboard URL (cn.<cluster domain>) without its first label. The API
    has no endpoint field for agents; this is the name under which CodeNOW publishes them."""
    parsed = urllib.parse.urlsplit(dashboard_url or "")
    host = parsed.hostname or ""
    if not agent or parsed.scheme not in ("https", "http") or "." not in host:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{agent}-{swarm}.{host.split('.', 1)[1]}{port}"


def answers(url):
    """True when GET <url>/health answers 200. No credentials are sent; redirects are not followed.
    CN_PROBE_ADDR=<host:port> (tests only) sends the request to that address with the observer's Host header."""
    target = os.environ.get("CN_PROBE_ADDR")
    request_url = f"http://{target}/health" if target else f"{url}/health"
    headers = {"Host": urllib.parse.urlsplit(url).netloc} if target else {}
    try:
        with cn_mcp.OPENER.open(urllib.request.Request(request_url, headers=headers),
                                timeout=PROBE_SECONDS) as response:
            return response.status == 200
    except Exception:
        return False


def find_observers(client):
    """(url, "swarm/agent") of each agent made from the observer template whose public URL answers."""
    found = []
    for swarm in as_list(client.call("agent_swarms_list", {})):
        swarm_id = swarm.get("id")
        if not swarm_id:
            continue
        agents = as_list(client.call("agents_list", {"agentSwarmId": swarm_id}))
        observers = [a for a in agents if isinstance(a.get("template"), dict)
                     and a["template"].get("id") == OBSERVER_TEMPLATE]
        if not observers:
            continue
        swarm_name = swarm.get("runtimeName") or swarm_id
        for entry in as_list(client.call("agent_swarm_deployments_list", {"agentSwarmId": swarm_id})):
            deployment = entry.get("deployment") if isinstance(entry.get("deployment"), dict) else {}
            for agent in observers:
                url = observer_url(agent.get("runtimeId") or agent.get("id"), swarm_name,
                                   deployment.get("dashboardUrl"))
                if url and url not in [u for u, _ in found] and answers(url):
                    found.append((url, f"{swarm_id}/{agent.get('id')}"))
    return found


def client():
    deadline = time.monotonic() + 90
    if os.environ.get("CN_MCP_BEARER_STDIN") == "1":
        bearer = sys.stdin.read().strip()
        if not bearer:
            raise cn_mcp.CnError("no access token on stdin")
        cn_mcp._USED_KEYS.add(bearer)  # scrub hides it in error lines
        return cn_mcp.Client(cn_mcp.mcp_url(), "", deadline=deadline, bearer=bearer)
    return cn_mcp.Client(*cn_mcp.settings(), deadline=deadline)


def main():
    try:
        mcp = client()
        try:
            for url, name in find_observers(mcp.start()):
                print(f"{url} {name}")
        finally:
            mcp.close()
        return 0
    except cn_mcp.CnError as error:
        print(f"cn: {cn_mcp.scrub(str(error))}", file=sys.stderr)
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # a last guard: one line, no traceback
        print(f"cn: unexpected error: {type(error).__name__}: {cn_mcp.scrub(str(error))[:300]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
