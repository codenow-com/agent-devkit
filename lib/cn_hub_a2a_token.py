"""The caller token of the hub's A2A "Try it" (lib/cn_hub_a2a.py): the same choice as the template's
`bash sandbox/sandbox.sh run`, made fresh for each send and never cached, logged, printed or sent to the browser.

    1. SANDBOX_CALLER_TOKEN in the hub's environment
    2. SANDBOX_IDP=dev in the agent's .env, or the pre-deploy marker sandbox/.run/predeploy: a dev person token from
       the sandbox's own helper, `bash sandbox/sandbox.sh token person <user> [--aud <A2A_EXPECTED_AUDIENCE>]`
       (pre-deploy: your oidc-agent token when the helper gives none)
    3. the developer identity (the agent logs `identity: adapter developer`): your own token,
       `oidc-token --time=60 <CN_OIDC_ACCOUNT, default cn-agw>`
    4. otherwise the agent's own refresh token at the tenant IAM (OIDC_ISSUER_URL, OIDC_CLIENT_ID and
       AI_GATEWAY_REFRESH_TOKEN of .env, read only for this exchange), as sandbox.sh does

Every program runs as an argument list with a timeout; its stderr is dropped (it may name the token).
"""
from __future__ import annotations

import getpass
import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = 20
_JWT = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*$")
NON_SECRET = ("SANDBOX_IDP", "A2A_EXPECTED_AUDIENCE", "CN_IDENTITY_PROVIDER")
GUIDANCE = ("No caller token. Start the run from the terminal in the agent repository instead: "
            "cn-sandbox run <pipeline> \"<subject>\" '<json facts>' (it uses the same tokens), or start the hub "
            "with SANDBOX_CALLER_TOKEN set.")


class NoToken(Exception):
    """No token could be obtained; the message says why and never contains a token."""


def env_keys(repo: pathlib.Path, keys) -> dict:
    """The named keys of the agent's .env (the last value of each); every other line is skipped unread."""
    values = {}
    try:
        lines = (repo / ".env").read_text(errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in keys:
            values[key] = value.strip().strip("'\"")
    return values


def plan(sb: dict, environ=None) -> dict:
    """Which way the token comes, without obtaining it: {"way", "label"} for the page."""
    environ = os.environ if environ is None else environ
    repo = pathlib.Path(sb.get("repo") or "")
    env = env_keys(repo, NON_SECRET) if sb.get("repo") else {}
    adapter = (sb.get("identity") or {}).get("adapter") or env.get("CN_IDENTITY_PROVIDER") or ""
    if environ.get("SANDBOX_CALLER_TOKEN"):
        return {"way": "env", "label": "SANDBOX_CALLER_TOKEN from the hub's environment"}
    if env.get("SANDBOX_IDP") == "dev":
        return {"way": "devidp", "label": "a dev person token from the sandbox (sandbox.sh token person)",
                "audience": env.get("A2A_EXPECTED_AUDIENCE", "")}
    if sb.get("repo") and (repo / "sandbox" / ".run" / "predeploy").is_file():
        return {"way": "predeploy", "label": "pre-deploy: a dev person token from the sandbox, else your own "
                "token (oidc-agent)", "audience": env.get("A2A_EXPECTED_AUDIENCE", "")}
    if adapter == "developer":
        return {"way": "developer", "label": "your own token (oidc-token " + account(environ) + ")"}
    return {"way": "refresh", "label": "the agent's refresh token at the tenant IAM (as sandbox.sh run does)"}


def account(environ) -> str:
    return environ.get("CN_OIDC_ACCOUNT") or "cn-agw"


def run_quiet(argv: list, cwd=None) -> str:
    """stdout of one program (stderr dropped), or "" when it fails, is missing or takes longer than TIMEOUT_S."""
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=cwd,
                             stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def jwt_or_none(text: str):
    text = (text or "").strip().splitlines()[-1].strip() if (text or "").strip() else ""
    return text if _JWT.match(text) else None


def from_sandbox(repo: pathlib.Path, audience: str, runner) -> str | None:
    script = repo / "sandbox" / "sandbox.sh"
    if not script.is_file():
        return None
    user = re.sub(r"[^A-Za-z0-9_.@-]", "", getpass.getuser() or "") or "developer"
    argv = ["bash", str(script), "token", "person", user] + (["--aud", audience] if audience else [])
    return jwt_or_none(runner(argv, str(repo)))


def from_oidc_agent(environ, runner) -> str | None:
    return jwt_or_none(runner(["oidc-token", "--time=60", account(environ)], None))


def no_proxy_open(request, timeout):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def from_refresh(repo: pathlib.Path, opener) -> str | None:
    """The refresh-token grant at the tenant IAM, as sandbox.sh's caller_token does."""
    env = env_keys(repo, ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID", "AI_GATEWAY_REFRESH_TOKEN"))
    issuer, client, refresh = (env.get(k, "") for k in ("OIDC_ISSUER_URL", "OIDC_CLIENT_ID",
                                                         "AI_GATEWAY_REFRESH_TOKEN"))
    if not (issuer and client and refresh) or urllib.parse.urlparse(issuer).scheme not in ("https", "http"):
        raise NoToken("the agent's .env has no OIDC_ISSUER_URL, OIDC_CLIENT_ID and AI_GATEWAY_REFRESH_TOKEN "
                      "(run `bash sandbox/sandbox.sh ready` in the agent repository first)")
    try:
        with opener(issuer.rstrip("/") + "/.well-known/openid-configuration", TIMEOUT_S) as answer:
            token_url = json.loads(answer.read(256 * 1024).decode()).get("token_endpoint") or ""
        form = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh,
                                       "client_id": client}).encode()
        request = urllib.request.Request(token_url, data=form, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        with opener(request, TIMEOUT_S) as answer:
            return jwt_or_none(json.loads(answer.read(256 * 1024).decode()).get("access_token") or "")
    except urllib.error.HTTPError as exc:
        raise NoToken(f"the tenant IAM refused the agent's refresh token (HTTP {exc.code}); run "
                      "`bash sandbox/sandbox.sh ready` in the agent repository to renew it") from None
    except (OSError, ValueError, AttributeError):
        raise NoToken("the tenant IAM did not answer the token refresh") from None


def caller_token(sb: dict, environ=None, runner=run_quiet, opener=no_proxy_open) -> tuple:
    """(token, label) for one send; raises NoToken with a reason (GUIDANCE follows it on the page)."""
    environ = os.environ if environ is None else environ
    how = plan(sb, environ)
    repo = pathlib.Path(sb.get("repo") or "")
    way = how["way"]
    token = None
    if way == "env":
        token = jwt_or_none(environ.get("SANDBOX_CALLER_TOKEN", ""))
        if not token:
            raise NoToken("SANDBOX_CALLER_TOKEN is not an access token (a JWT)")
    elif way in ("devidp", "predeploy"):
        token = from_sandbox(repo, how.get("audience", ""), runner)
        if not token and way == "predeploy":
            token = from_oidc_agent(environ, runner)
        if not token:
            raise NoToken("the sandbox gave no dev token (`bash sandbox/sandbox.sh token person <name>` failed: "
                          "is the dev identity provider running?)")
    elif way == "developer":
        token = from_oidc_agent(environ, runner)
        if not token:
            raise NoToken(f"oidc-token {account(environ)} gave no token: load the account with "
                          f"`oidc-add {account(environ)}`")
    else:
        token = from_refresh(repo, opener)
        if not token:
            raise NoToken("the tenant IAM gave no access token for the agent's refresh token")
    return token, how["label"]
