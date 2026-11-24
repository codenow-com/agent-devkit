"""Read-only access of the sandbox hub to a sandbox's run store (Postgres) and Valkey, and the hub's masking.

Neither service is published to the host: every read is one `docker exec` (an argument list, never a shell string)
into the sandbox's compose service, with a timeout. Postgres: `psql` in the `runstore` container, the SQL on stdin
inside a READ ONLY transaction, every outside value passed as a psql variable (`:'name'` quotes it). Valkey:
`valkey-cli --json` (or `redis-cli`) in the `valkey` container, only the commands of `VALKEY_READ`. The Postgres user
and database are the container's own POSTGRES_USER and POSTGRES_DB; no other variable of it is ever read.
"""
from __future__ import annotations

import json
import re
import subprocess
import time

TIMEOUT_S = 8
MAX_OUTPUT = 8 * 1024 * 1024
PROJECT = re.compile(r"^sandbox-[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}(?:\.[A-Za-z0-9_-]*)?")
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")
_ASSIGN = re.compile(r"(?i)\b([A-Z0-9_]*(?:token|secret|password|passwd|api_key|apikey)[A-Z0-9_]*)\s*([=:])\s*[^\s,;)]+")
_QUOTED = re.compile(r"(?i)(\"[A-Za-z0-9_]*(?:token|secret|password|passwd|api_key|apikey)[A-Za-z0-9_]*\"\s*:\s*)"
                     r"\"(?:[^\"\\]|\\.)+\"")
_LONG = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_-]{48,}={0,2}(?![A-Za-z0-9+/_=-])")
_SECRET_KEY = re.compile(r"(?i)(token|secret|password|passwd|api_key|apikey)")


def mask(text: str) -> str:
    """Everything that may be a credential, replaced: JWTs, bearer values, KEY=value of secret-like keys."""
    text = _JWT.sub("<token>", text)
    text = _BEARER.sub(r"\1 <token>", text)
    text = _QUOTED.sub(r'\1"<masked>"', text)
    return _ASSIGN.sub(r"\1\2<masked>", text)


def mask_log(text: str) -> str:
    """A log line or a data value: mask(), and every long opaque string (48+ base64 or hex characters) as well."""
    return _LONG.sub("<masked>", mask(text))


def mask_all(value):
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [mask_all(v) for v in value]
    if isinstance(value, dict):
        return {k: mask_all(v) for k, v in value.items()}
    return value


def mask_deep(value, key: str = ""):
    """Data from a run store or a stream: mask_log on every string and key, and the whole value of a secret key."""
    if isinstance(value, str):
        if key and _SECRET_KEY.search(key) and value:
            return "<masked>"
        if value[:1] in "{[" and len(value) < 2_000_000:   # JSON text inside a value: its keys count too
            try:
                parsed = json.loads(value)
            except ValueError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                return json.dumps(mask_deep(parsed), ensure_ascii=False)
        return mask_log(value)
    if isinstance(value, (list, tuple)):
        return [mask_deep(v, key) for v in value]
    if isinstance(value, dict):
        return {mask_log(str(k)): mask_deep(v, str(k)) for k, v in value.items()}
    return value


class ExecError(Exception):
    """A read that did not work; the message is for the page (masked, no secret in it)."""


def run_process(args: list, stdin: str | None = None, timeout: float = TIMEOUT_S) -> tuple:
    """One `docker` command: (exit code, stdout, stderr). Raises ExecError on a timeout or a missing docker."""
    try:
        out = subprocess.run(["docker", *args], input=stdin, capture_output=True, text=True, timeout=timeout,
                             errors="replace")
    except subprocess.TimeoutExpired:
        raise ExecError(f"docker did not answer in {timeout:g} s (docker {args[0]} {args[1] if len(args) > 1 else ''})")
    except OSError as exc:
        raise ExecError(f"docker cannot be run: {exc.strerror or exc}")
    return out.returncode, out.stdout[:MAX_OUTPUT], out.stderr[:4000]


# ---------------------------------------------------------------- Valkey: the read-only commands

VALKEY_READ = {"SCAN", "TYPE", "TTL", "XLEN", "XRANGE", "XREVRANGE", "HLEN", "HGETALL", "HSCAN", "LLEN", "LRANGE",
               "SCARD", "SSCAN", "ZCARD", "ZRANGE", "STRLEN", "GETRANGE", "DBSIZE", "MEMORY", "XINFO"}
VALKEY_SUB = {"MEMORY": {"USAGE"}, "XINFO": {"STREAM"}}


def check_valkey(command: list) -> list:
    """The command itself when it is a read of VALKEY_READ; ValueError before anything is built otherwise."""
    if not command or not isinstance(command[0], str):
        raise ValueError("empty Valkey command")
    name = command[0].upper()
    if name not in VALKEY_READ:
        raise ValueError(f"Valkey command {name} is not a read the hub allows")
    if name in VALKEY_SUB and (len(command) < 2 or str(command[1]).upper() not in VALKEY_SUB[name]):
        raise ValueError(f"Valkey command {name} {command[1:2]} is not a read the hub allows")
    return [name] + [str(a) for a in command[1:]]


def cli_quote(arg: str) -> str:
    """One argument for valkey-cli's own line parser (stdin mode): double quotes, every other byte as \\xHH."""
    out = []
    for byte in arg.encode("utf-8"):
        char = chr(byte)
        out.append(char if 0x20 < byte < 0x7f and char not in "\"\\'" else "\\x%02x" % byte)
    return '"' + "".join(out) + '"'


# ---------------------------------------------------------------- one sandbox

class Sandbox:
    """The run store and Valkey of one sandbox (compose project), read through `docker exec`."""

    def __init__(self, project: str, runner=run_process, timeout: float = TIMEOUT_S):
        if not PROJECT.match(project or ""):
            raise ExecError("not a sandbox project name")
        self.project, self.runner, self.timeout = project, runner, timeout
        self._ids, self._pg, self._cli = {}, None, None

    def container(self, service: str) -> str:
        if service not in self._ids:
            code, out, _ = self.runner(["ps", "-q", "--filter", f"label=com.docker.compose.project={self.project}",
                                        "--filter", f"label=com.docker.compose.service={service}"],
                                       None, self.timeout)
            ids = [line.strip() for line in out.splitlines() if line.strip()]
            if code != 0 or not ids:
                raise ExecError(f"the {service} container of {self.project} does not run")
            self._ids[service] = ids[0]
        return self._ids[service]

    # -------------------------------------------------- Postgres

    def pg_login(self) -> tuple:
        """POSTGRES_USER and POSTGRES_DB of the runstore container; nothing else of its environment is kept."""
        if self._pg is None:
            cid = self.container("runstore")
            code, out, _ = self.runner(["inspect", "--format", "{{json .Config.Env}}", cid], None, self.timeout)
            try:
                env = json.loads(out) if code == 0 else []
            except ValueError:
                env = []
            found = {}
            for item in env or []:
                key, _, value = str(item).partition("=")
                if key in ("POSTGRES_USER", "POSTGRES_DB"):
                    found[key] = value
            user = found.get("POSTGRES_USER") or "postgres"
            self._pg = (cid, user, found.get("POSTGRES_DB") or user)
        return self._pg

    def sql(self, select: str, params: dict | None = None):
        """One SELECT the code built (it returns one JSON value), run READ ONLY; `params` as psql variables."""
        if not select.lstrip().upper().startswith("SELECT"):
            raise ValueError("the hub runs only SELECT")
        cid, user, db = self.pg_login()
        args = ["exec", "-i", cid, "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
        for name, value in (params or {}).items():
            if not re.match(r"^[a-z_]{1,20}$", name):
                raise ValueError("bad psql variable name")
            args += ["-v", f"{name}={clean(str(value))}"]
        args += ["-U", user, "-d", db, "-f", "-"]
        script = ("BEGIN READ ONLY;\nSET LOCAL statement_timeout = '%ds';\n%s;\nCOMMIT;\n"
                  % (max(1, int(self.timeout) - 2), select.rstrip().rstrip(";")))
        started = time.monotonic()
        code, out, err = self.runner(args, script, self.timeout)
        if code != 0:
            raise ExecError("run store: " + mask_log(first_line(err) or f"psql exited {code}"))
        text = out.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise ExecError(f"run store: no JSON in psql's answer ({time.monotonic() - started:.1f} s)")

    # -------------------------------------------------- Valkey

    def valkey(self, *commands: list) -> list:
        """Several read commands in one `valkey-cli --json` (stdin mode); one parsed reply (or None) per command."""
        lines = [" ".join(cli_quote(a) for a in check_valkey(list(c))) for c in commands]
        cid = self.container("valkey")
        for cli in ([self._cli] if self._cli else ["valkey-cli", "redis-cli"]):
            code, out, err = self.runner(["exec", "-i", cid, cli, "--json"], "\n".join(lines) + "\n", self.timeout)
            if code == 0:
                self._cli = cli
                replies = []
                for line in out.splitlines()[: len(lines)]:
                    try:
                        replies.append(json.loads(line))
                    except ValueError:
                        replies.append(None)
                return replies + [None] * (len(lines) - len(replies))
            if "executable file not found" not in err and "not found" not in err:
                raise ExecError("valkey: " + mask_log(first_line(err) or f"{cli} exited {code}"))
        raise ExecError("valkey: neither valkey-cli nor redis-cli in the valkey container")


def clean(text: str, size: int = 200) -> str:
    """An outside value for a psql variable: no control characters, at most `size` characters."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:size]


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:300]
    return ""
