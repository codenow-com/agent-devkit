"""The hub's A2A "Try it" (the hub's only state-changing action): one sandbox's agent card, and one JSON-RPC
`message/send` to it with the caller token of lib/cn_hub_a2a_token.py, polled with `tasks/get` until it ends.

    GET  /s/<project>/try                the page (cn_hub_render_a2a)
    GET  /api/s/<project>/a2a/card       the parsed agent card
    POST /api/s/<project>/a2a/send       {"skill", "text", "subject", "data"} -> the masked outcome

Requests go only to http://127.0.0.1:<the sandbox's console port><the card url's path>, never to the host the card
names. A send needs the same origin, the per-process CSRF token in X-CN-Hub-Token and a JSON body; one per sandbox
runs at a time, within TIMEOUT_S. The token never leaves this process: the outcome is masked and the token's own
text is cut out of it as well.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from cn_hub_a2a_token import GUIDANCE, NoToken, caller_token
from cn_hub_exec import mask_deep, mask_log

MAX_MESSAGE = 32 * 1024
MAX_BODY = 40 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
TIMEOUT_S = 120
POLL_S = 2.0
TERMINAL = {"completed", "failed", "canceled", "cancelled", "rejected", "input-required", "auth-required"}
SPECIAL_TAGS = {"consult", "tool-policy", "limits"}


class A2AFailure(Exception):
    def __init__(self, status: int, message: str, **extra):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra


def no_proxy_open(request, timeout):
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def read_capped(answer) -> bytes:
    body = answer.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise A2AFailure(502, "the agent's answer is larger than 4 MB")
    return body


def fetch_card(port: int, opener=no_proxy_open) -> dict:
    """The agent's card from its console port: /.well-known/agent.json, else /.well-known/agent-card.json."""
    last = "no answer"
    for path in ("/.well-known/agent.json", "/.well-known/agent-card.json"):
        try:
            with opener(f"http://127.0.0.1:{int(port)}{path}", 10) as answer:
                return json.loads(read_capped(answer).decode())
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (OSError, ValueError) as exc:
            last = type(exc).__name__
    raise A2AFailure(502, f"the agent card is not readable on 127.0.0.1:{port} ({last})")


def parse_card(raw: dict) -> dict:
    """The card's fields the page shows, for the SDK's card (url .../a2a, skills = pipelines) and ADK's to_a2a."""
    raw = raw if isinstance(raw, dict) else {}
    modes = raw.get("defaultInputModes") or []
    skills = []
    for skill in raw.get("skills") or []:
        if not isinstance(skill, dict) or not skill.get("id"):
            continue
        tags = [str(t) for t in skill.get("tags") or []]
        skills.append({"id": str(skill["id"]), "name": str(skill.get("name") or skill["id"]),
                       "description": str(skill.get("description") or ""), "tags": tags,
                       "examples": [str(x) for x in skill.get("examples") or []][:10],
                       "input_modes": skill.get("inputModes") or modes,
                       "special": bool(SPECIAL_TAGS & set(tags))})
    url = str(raw.get("url") or "")
    return {"name": str(raw.get("name") or ""), "description": str(raw.get("description") or ""), "url": url,
            "version": str(raw.get("version") or ""), "protocol": str(raw.get("protocolVersion") or ""),
            "input_modes": modes, "output_modes": raw.get("defaultOutputModes") or [],
            "streaming": bool((raw.get("capabilities") or {}).get("streaming")), "skills": skills,
            "flavor": "sdk" if urlparse(url).path.rstrip("/").endswith("/a2a") else "a2a"}


def endpoint(card: dict, port: int) -> str:
    """The card's url, rewritten to the sandbox's local port (the card may name the deployed or gateway url)."""
    path = urlparse(card.get("url") or "").path or "/"
    if not path.startswith("/") or ".." in path or not re.match(r"^[A-Za-z0-9/_.~-]*$", path):
        path = "/"
    return f"http://127.0.0.1:{int(port)}{path}"


def build_message(skill: str, text: str, subject: str, data, sdk: bool) -> dict:
    """The A2A message as `sandbox.sh run` builds it: metadata.skillId, a data part (facts and subject) and the text
    as a text part (the SDK joins text parts into the fact `message`). Parts carry `kind` (A2A 0.3) and, for the
    SDK, its own `type` too."""
    parts = []
    if text:
        parts.append({"kind": "text", "text": text})
    facts = dict(data or {})
    if subject:
        facts["subject"] = subject
    if facts:
        parts.append({"kind": "data", "data": facts})
    if sdk:
        for part in parts:
            part["type"] = part["kind"]
    return {"role": "user", "messageId": str(uuid.uuid4()), "kind": "message",
            "metadata": {"skillId": skill} if skill else {}, "parts": parts}


def rpc(url: str, token: str, method: str, params: dict, deadline: float, opener) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json", "Authorization": "Bearer " + token})
    left = deadline - time.monotonic()
    if left <= 0:
        raise A2AFailure(504, f"no answer within {TIMEOUT_S} s")
    try:
        with opener(request, left) as answer:
            return json.loads(read_capped(answer).decode())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = mask_log(exc.read(2000).decode(errors="replace").replace(token, "<token>"))
        except OSError:
            pass
        raise A2AFailure(exc.code, f"the agent answered HTTP {exc.code}", detail=detail[:500]) from None
    except (TimeoutError, OSError) as exc:
        if "timed out" in str(exc) or isinstance(exc, TimeoutError):
            raise A2AFailure(504, f"no answer within {TIMEOUT_S} s") from None
        raise A2AFailure(502, f"the agent did not answer ({type(exc).__name__})") from None
    except ValueError:
        raise A2AFailure(502, "the agent's answer is not JSON") from None


def task_of(answer: dict) -> dict:
    if not isinstance(answer, dict):
        raise A2AFailure(502, "the agent's answer is not a JSON-RPC object")
    if answer.get("error"):
        error = answer["error"] if isinstance(answer["error"], dict) else {"message": str(answer["error"])}
        raise A2AFailure(200, f"the agent answered a JSON-RPC error {error.get('code', '')}: "
                              f"{error.get('message', '')}".strip(), rpc_error=error)
    result = answer.get("result")
    return result if isinstance(result, dict) else {}


def texts_of(parts) -> list:
    return [p["text"] for p in parts or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]


def outcome_of(task: dict, sdk: bool) -> dict:
    """State, ids, the final text, data parts and the run id of a task (or of a direct message answer)."""
    status = task.get("status") if isinstance(task.get("status"), dict) else {}
    state = str(status.get("state") or ("completed" if task.get("kind") == "message" else "unknown"))
    texts = texts_of((status.get("message") or {}).get("parts")) + texts_of(task.get("parts"))
    data = []
    for artifact in task.get("artifacts") or []:
        parts = (artifact or {}).get("parts") or []
        texts += texts_of(parts)
        data += [p["data"] for p in parts if isinstance(p, dict) and isinstance(p.get("data"), dict)]
    record = task.get("result") if isinstance(task.get("result"), dict) else {}
    if record.get("summary") and not texts:
        texts.append(str(record["summary"]))
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    run_id = record.get("run_id") or meta.get("run_id") or meta.get("runId") or (task.get("id") if sdk else None)
    return {"state": state, "task_id": task.get("id"), "context_id": task.get("contextId"),
            "text": "\n\n".join(texts), "data": data, "run_id": str(run_id) if run_id else None,
            "error": record.get("error") or None}


def audience_mode(log: str) -> str:
    found = None
    """The A2A audience mode the agent logged last ("shadow", "enforce"), else "unknown"."""
    for found in re.finditer(r"A2A_AUDIENCE_MODE=(\w+) accepts|inbound audience \((\w+)\)", log or ""):
        pass
    return (found.group(1) or found.group(2)) if found else "unknown"


def explain_auth(status: int, mode: str, way_label: str) -> str:
    who = f"The caller token was {way_label}."
    if status == 401:
        return (f"The agent refused the caller token (401). {who} The agent checks the signature and the trusted "
                f"issuer (harness.a2a.trusted_issuer_url){', and the audience A2A_EXPECTED_AUDIENCE' if mode == 'enforce' else ''}"
                f"; audience mode: {mode} (shadow accepts any token of the trusted issuer). A dev token works only "
                "on an agent that trusts the dev identity provider; a tenant token only on one that trusts the "
                "tenant IAM.")
    return (f"The agent refused the call (403). {who} The token is valid, but this caller may not start this skill "
            "(Workforce mandate, console allowlist or the skill's policy); the agent log says which.")


def send(sb: dict, request: dict, log: str = "", opener=no_proxy_open, token_fn=None, clock=time.monotonic,
         sleep=time.sleep) -> dict:
    """One message/send (and tasks/get until a terminal state or TIMEOUT_S); the masked outcome for the page."""
    started, port = clock(), (sb.get("console") or {}).get("port")
    if not port:
        raise A2AFailure(409, "the sandbox has no console port: is it running?")
    deadline = started + TIMEOUT_S
    card = parse_card(fetch_card(port, opener))
    sdk = card["flavor"] == "sdk" or bool(sb.get("sdk_version"))
    url = endpoint(card, port)
    try:
        token, label = (token_fn or caller_token)(sb)
    except NoToken as exc:
        raise A2AFailure(424, str(exc), guidance=GUIDANCE) from None
    exchanges, outcome = [], None
    try:
        message = build_message(request["skill"], request["text"], request["subject"], request["data"], sdk)
        answer = rpc(url, token, "message/send", {"message": message}, deadline, opener)
        exchanges.append({"method": "message/send", "request": {"message": message}, "response": answer})
        task = task_of(answer)
        outcome = outcome_of(task, sdk)
        while outcome["state"] not in TERMINAL and outcome["task_id"] and clock() + POLL_S < deadline:
            sleep(POLL_S)
            answer = rpc(url, token, "tasks/get", {"id": outcome["task_id"]}, deadline, opener)
            exchanges = exchanges[:1] + [{"method": "tasks/get", "response": answer}]
            outcome = outcome_of(task_of(answer), sdk)
    except A2AFailure as exc:
        if exc.status in (401, 403):
            exc.extra["guidance"] = explain_auth(exc.status, audience_mode(log), label)
        exc.extra["raw"] = clean(exchanges, token)
        exc.extra["duration_s"] = round(clock() - started, 2)
        exc.message = exc.message.replace(token, "<token>")
        raise
    if outcome["state"] not in TERMINAL:
        outcome["note"] = f"still {outcome['state']} after {TIMEOUT_S} s: the run goes on; see its run page"
    return {**clean(outcome, token), "endpoint": url, "skill": request["skill"], "token_from": label,
            "duration_s": round(clock() - started, 2), "raw": clean(exchanges, token)}


def clean(value, token: str):
    """mask_deep, and the token's own text cut out wherever it appears."""
    text = json.dumps(mask_deep(value), ensure_ascii=False, default=str)
    return json.loads(text.replace(token, "<token>")) if token else json.loads(text)


def parse_request(raw: bytes) -> dict:
    try:
        body = json.loads(raw.decode())
    except (UnicodeDecodeError, ValueError):
        raise A2AFailure(400, "the body is not JSON") from None
    if not isinstance(body, dict):
        raise A2AFailure(400, "the body must be a JSON object")
    skill, text, subject = (str(body.get(k) or "").strip() if k != "text" else str(body.get(k) or "")
                            for k in ("skill", "text", "subject"))
    data = body.get("data")
    if isinstance(data, str) and data.strip():
        try:
            data = json.loads(data)
        except ValueError:
            raise A2AFailure(400, "data is not valid JSON") from None
    if data in (None, ""):
        data = {}
    if not isinstance(data, dict):
        raise A2AFailure(400, "data must be a JSON object")
    if len((text + subject + json.dumps(data)).encode()) > MAX_MESSAGE:
        raise A2AFailure(413, "the message is larger than 32 KB")
    if not (text.strip() or subject or data):
        raise A2AFailure(400, "write a message, a subject or data")
    if not re.match(r"^[A-Za-z0-9_.:-]{0,128}$", skill):
        raise A2AFailure(400, "the skill id is not valid")
    return {"skill": skill, "text": text, "subject": subject, "data": data}
