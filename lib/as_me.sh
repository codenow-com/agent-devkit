# cn-sandbox up --as-me, cn-sandbox as-me off|status: run the local agent under the developer's own identity.
# Sourced by cn-sandbox after common.sh, sandbox_token.sh and gateway_setup.sh (interactive, ask_yes). Not run.
#
# A managed block in the agent's .env holds the four lines; every other line stays as it is:
#   # >>> cn-devkit: developer identity (cn-sandbox as-me off removes it)
#   CN_IDENTITY_PROVIDER=developer
#   CN_IDENTITY_DEVELOPER_CLIENTS=<CODENOW_AGW_CLIENT_ID>
#   WORKFORCE_URL=<CODENOW_WORKFORCE_URL>      (left out when cn-setup has no Workforce URL)
#   WORKFORCE_MODE=shadow                      (the same)
#   # <<< cn-devkit
# The values come from ~/.codenow/config (cn-setup --only-gateway). None of them is a secret.

ASME_BEGIN='# >>> cn-devkit: developer identity (cn-sandbox as-me off removes it)'
ASME_END='# <<< cn-devkit'
ASME_SDK=codenow-agent-sdk
ASME_SDK_MIN=2.24.0

# asme_lines: the lines of the block (without its markers), from the stored settings.
asme_lines() {
  [ -n "${CODENOW_AGW_CLIENT_ID:-}" ] \
    || die "no agent gateway client is set (CODENOW_AGW_CLIENT_ID): run cn-setup --only-gateway"
  printf 'CN_IDENTITY_PROVIDER=developer\nCN_IDENTITY_DEVELOPER_CLIENTS=%s\n' "$CODENOW_AGW_CLIENT_ID"
  [ -z "${CODENOW_WORKFORCE_URL:-}" ] || printf 'WORKFORCE_URL=%s\nWORKFORCE_MODE=shadow\n' "$CODENOW_WORKFORCE_URL"
}

# asme_edit <env file> write|remove|conflicts [lines]: one Python helper for the three file operations.
#   conflicts  prints "line N: KEY=value" for each of the block's keys outside the block with another, non-empty value
#   write      replaces the block (or appends it) with the lines on stdin and deletes the empty `KEY=` lines of the
#              block's keys outside it (prints "removed line N: KEY=" for each); the file keeps its mode (new: 600)
#   remove     deletes the block; prints "removed" when there was one
ASME_PY="$(cat <<'PY'
import os, sys, tempfile
path, action, begin, end = sys.argv[1:5]
wanted = sys.stdin.read().splitlines() if action != "remove" else []
try:
    with open(path) as f:
        lines = f.read().splitlines()
except FileNotFoundError:
    lines = []
outside, start, stop = [], None, None
for n, line in enumerate(lines):
    if line == begin and start is None:
        start = n
    elif line == end and start is not None and stop is None:
        stop = n
    elif start is None or stop is not None:
        outside.append((n + 1, line))
if start is not None and stop is None:
    sys.exit(f"{path}: the line '{begin}' has no closing '{end}': fix the file by hand")
want = dict(l.split("=", 1) for l in wanted)
def setting(line):  # (key, value) of a KEY=value line of a key of the block, else None
    text = line.strip()
    if text.startswith("export "):
        text = text[7:].lstrip()
    key, sep, value = text.partition("=")
    return (key.strip(), value.strip()) if sep and key.strip() in want else None
def empty(value):  # only whitespace after the = sign, or an empty quoted string
    return value in ("", '""', "''")
if action == "conflicts":
    for n, line in outside:
        found = setting(line)
        if found and not empty(found[1]) and found[1].strip('"').strip("'") != want[found[0]]:
            print(f"line {n}: {line}")
    sys.exit(0)
dropped = set()
if action == "write":
    for n, line in outside:
        found = setting(line)
        if found and empty(found[1]):
            dropped.add(n - 1)
            print(f"removed line {n}: {line.strip()}")
if action == "remove" and start is None:
    sys.exit(0)
block = [begin, *wanted, end] if action == "write" else []
if start is None:
    kept = [l for n, l in enumerate(lines) if n not in dropped]
    new = kept + ([""] if kept and kept[-1].strip() else []) + block
else:
    keep = lambda a, b: [lines[n] for n in range(a, b) if n not in dropped]
    new = keep(0, start) + block + keep(stop + 1, len(lines))
    if action == "remove" and start > 0 and not lines[start - 1].strip() and (stop + 1 >= len(lines)):
        new = lines[:start - 1]
mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=".env.")
with os.fdopen(fd, "w") as out:
    out.write("\n".join(new) + ("\n" if new else ""))
os.chmod(tmp, mode)
os.replace(tmp, path)
if action == "remove":
    print("removed")
PY
)"
asme_edit() { python3 -I -c "$ASME_PY" "$1" "$2" "$ASME_BEGIN" "$ASME_END"; }

# asme_newest_sdk: the newest codenow-agent-sdk on the pip index of this computer; ASME_SDK_MIN when unknown.
asme_newest_sdk() {
  local out versions
  out="$(python3 -m pip index versions "$ASME_SDK" --disable-pip-version-check 2>/dev/null || true)"
  versions="$(printf '%s\n' "$out" | sed -n 's/^Available versions: //p' | tr ',' '\n' | tr -d ' ')"
  if [ -z "$versions" ]; then   # older pip: the error of an empty pin lists the versions
    out="$(python3 -m pip download --no-deps --disable-pip-version-check -d "${TMPDIR:-/tmp}" "$ASME_SDK==" 2>&1 || true)"
    versions="$(printf '%s\n' "$out" | sed -n 's/.*(from versions: \(.*\)).*/\1/p' | tr ',' '\n' | tr -d ' ')"
  fi
  versions="$(printf '%s\n' "$versions" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1)"
  printf '%s' "${versions:-$ASME_SDK_MIN}"
}

# asme_pin_check <repo>: the agent's SDK pin must be ASME_SDK_MIN or newer; raised only with the developer's consent.
asme_pin_check() {
  local req="$1/requirements.txt" pin newest
  [ -f "$req" ] || { say "no requirements.txt: cannot check the $ASME_SDK version"; return 0; }
  pin="$(sed -n "s/^$ASME_SDK==\([0-9][0-9.]*\)[[:space:]]*\$/\1/p" "$req" | head -n 1)"
  if [ -z "$pin" ]; then say "requirements.txt has no $ASME_SDK==X.Y.Z pin: not checked"; return 0; fi
  if [ "$(printf '%s\n%s\n' "$ASME_SDK_MIN" "$pin" | sort -V | head -n 1)" = "$ASME_SDK_MIN" ]; then return 0; fi
  say "$ASME_SDK $pin is too old: the developer identity needs $ASME_SDK_MIN or newer"
  interactive || die "raise the pin in requirements.txt to $ASME_SDK==$ASME_SDK_MIN or newer, then run again"
  newest="$(asme_newest_sdk)"
  ask_yes "Change requirements.txt to $ASME_SDK==$newest (only that line)?" \
    || die "not changed; raise the pin to $ASME_SDK_MIN or newer, then run again"
  python3 -I - "$req" "$ASME_SDK" "$newest" <<'PY'
import os, re, sys, tempfile
path, name, version = sys.argv[1:4]
text = open(path).read()
text = re.sub(rf"^{re.escape(name)}==[0-9][0-9.]*[ \t]*$", f"{name}=={version}", text, count=1, flags=re.M)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))
with os.fdopen(fd, "w") as out:
    out.write(text)
os.chmod(tmp, os.stat(path).st_mode & 0o777)
os.replace(tmp, path)
PY
  say "requirements.txt: $ASME_SDK==$newest; commit it (git add requirements.txt && git commit)"
}

# asme_on <repo> <env file>: the pin check, then the block (conflicts stop it).
asme_on() {
  local repo="$1" env="$2" lines conflicts removed
  asme_pin_check "$repo"
  lines="$(asme_lines)" || exit 1
  conflicts="$(printf '%s\n' "$lines" | asme_edit "$env" conflicts)" || die "cannot read $env"
  if [ -n "$conflicts" ]; then
    say "$env sets the developer identity outside the cn-devkit block with other values:" >&2
    printf '%s\n' "$conflicts" | sed "s/^/${CN_CMD:-cn}:   /" >&2
    die "remove these lines from $env (cn-sandbox up --as-me writes the values), then run again"
  fi
  removed="$(printf '%s\n' "$lines" | asme_edit "$env" write)" || die "could not write $env"
  [ -z "$removed" ] || printf '%s\n' "$removed" | sed "s/^/${CN_CMD:-cn}: $(basename "$env"): empty setting outside the block, /"
  say "$env: developer identity block written (client $CODENOW_AGW_CLIENT_ID)"
  if [ -n "${CODENOW_WORKFORCE_URL:-}" ]; then
    say "Workforce: $CODENOW_WORKFORCE_URL (shadow); you see the agent under you as --under-development-- <agent>"
  else
    say "no Workforce URL: the agent will not appear in Workforce (cn-setup --only-gateway sets it)"
  fi
}

# The persistent `as-me off` of one repository: this comment line in its .env (never a value).
ASME_OFF_LINE='# cn-devkit: identity=deployment (cn-sandbox as-me on runs the agent as you again)'
ASME_TOKEN_WRITTEN=""

asme_is_off() { [ -f "$1" ] && grep -qxF "$ASME_OFF_LINE" "$1"; }

asme_mark_off() {
  local env="$1"
  asme_is_off "$env" && return 0
  [ -f "$env" ] || ( umask 077; : > "$env" )
  if [ -s "$env" ] && [ -n "$(tail -c 1 "$env")" ]; then echo >> "$env"; fi
  echo "$ASME_OFF_LINE" >> "$env"
}

asme_mark_on() {  # removes the marker line in place (the file keeps its mode)
  local env="$1" kept
  asme_is_off "$env" || return 0
  kept="$(grep -vxF "$ASME_OFF_LINE" "$env" || true)"
  printf '%s\n' "$kept" > "$env"
}

# asme_pin_old <repo>: the SDK pin when it is older than ASME_SDK_MIN, else nothing.
asme_pin_old() {
  local pin
  pin="$(sed -n "s/^$ASME_SDK==\([0-9][0-9.]*\)[[:space:]]*\$/\1/p" "$1/requirements.txt" 2>/dev/null | head -n 1)"
  [ -n "$pin" ] || return 0
  [ "$(printf '%s\n%s\n' "$ASME_SDK_MIN" "$pin" | sort -V | head -n 1)" = "$ASME_SDK_MIN" ] || printf '%s' "$pin"
}

# asme_not_ready <repo> <token file>: why the developer identity cannot be used now (one line), else nothing. The
# token check writes the token file (oidc-token), so `up` does not ask for it twice. Run it in $( ): it may exit.
asme_not_ready() {
  local pin
  if [ -z "${CODENOW_AGW_CLIENT_ID:-}" ]; then
    echo "no agent gateway client is set (CODENOW_AGW_CLIENT_ID); fix: cn-setup --only-gateway"; return 0
  fi
  if ! have oidc-token; then echo "oidc-token is missing; fix: cn-doctor"; return 0; fi
  pin="$(asme_pin_old "$1")"
  if [ -n "$pin" ] && ! interactive; then
    echo "requirements.txt pins $ASME_SDK $pin, older than $ASME_SDK_MIN; fix: cn-sandbox up --as-me in a terminal"
    return 0
  fi
  if ! ( token_write "$2" ) >/dev/null 2>&1; then
    echo "oidc-token $(token_account) gave no token; fix: oidc-add $(token_account)"
  fi
}

# asme_choose <repo> <env file> default|as-me|deployment: the identity of this `up` (developer by default; the
# deployment token only on an explicit command, or with the reason when the identity is not ready). It writes the
# mode and its source to sandbox/.run/identity-mode for cn-sandbox status and the hub.
asme_choose() {
  local repo="$1" env="$2" choice="$3" mode reason
  case "$choice" in
    deployment)
      asme_edit "$env" remove >/dev/null || die "could not change $env"
      mode="deployment token (this run: --deployment-token)"
      say "identity: deployment token for this run (--deployment-token); the next cn-sandbox up runs as you again" ;;
    *)
      if [ "$choice" = default ] && asme_is_off "$env"; then
        asme_edit "$env" remove >/dev/null || die "could not change $env"
        mode="deployment token (as-me off)"
        say "identity: deployment token (as-me off); cn-sandbox as-me on runs the agent as you again"
      else
        reason="$(asme_not_ready "$repo" "$(token_file_path "$env")")"
        [ -n "$reason" ] || ASME_TOKEN_WRITTEN=1   # asme_not_ready wrote the token
        if [ -n "$reason" ] && [ "$choice" = as-me ]; then die "cannot run as you: $reason"; fi
        if [ -n "$reason" ]; then
          asme_edit "$env" remove >/dev/null || die "could not change $env"
          mode="deployment token (identity not ready: ${reason%%; fix:*})"
          say "identity: deployment token: your own identity is not ready: $reason"
        else
          [ "$choice" = default ] || asme_mark_on "$env"
          asme_on "$repo" "$env"
          if [ "$choice" = default ]; then mode="as you (default)"; else mode="as you (--as-me)"; fi
        fi
      fi ;;
  esac
  mkdir -p "$repo/sandbox/.run"
  printf '%s\n' "$mode" > "$repo/sandbox/.run/identity-mode"
}

# asme_mode <repo>: the mode of the last `cn-sandbox up` and its source, or nothing.
asme_mode() { head -n 1 "$1/sandbox/.run/identity-mode" 2>/dev/null || true; }

asme_off() {
  local env="$1" out
  out="$(asme_edit "$env" remove)" || die "could not change $env"
  if [ "$out" = removed ]; then say "$env: developer identity block removed"
  else say "$env has no developer identity block"; fi
}

asme_status() {
  local env="$1"
  if [ -f "$env" ] && grep -qxF "$ASME_BEGIN" "$env"; then
    say "$env has the developer identity block:"
    sed -n "/^# >>> cn-devkit: developer identity/,/^# <<< cn-devkit\$/p" "$env" | sed 's/^/  /'
  else
    say "${env:-.env} has no developer identity block (cn-sandbox up --as-me writes it)"
  fi
  if asme_is_off "$env"; then say "as-me off: cn-sandbox up uses the deployment token (cn-sandbox as-me on: as you)"
  else say "cn-sandbox up runs the agent as you when your identity is ready (cn-sandbox as-me off: the deployment token)"; fi
  say "stored (~/.codenow/config): client ${CODENOW_AGW_CLIENT_ID:-<not set>}, Workforce ${CODENOW_WORKFORCE_URL:-<not set>}"
}

# asme_predeploy_env: before the agent's first deployment its sandbox.sh (a template newer than 1.7.0) takes the agent gateway
# and the IAM issuer from CODENOW_AGW_URL and CODENOW_IAM_ISSUER (cn-setup --only-gateway); pass the stored values on.
asme_predeploy_env() {
  local name
  for name in CODENOW_AGW_URL CODENOW_IAM_ISSUER; do
    if [ -z "${!name:-}" ] && [ -f "${CODENOW_CONFIG:-}" ]; then
      # the devkit's own file (save_setting writes it with printf %q): read as load_config does, in a subshell
      printf -v "$name" '%s' "$( . "$CODENOW_CONFIG" >/dev/null 2>&1; printf '%s' "${!name:-}")"
    fi
    [ -z "${!name:-}" ] || export "$name"
  done
}

# asme_console_login <repo>: whose client the console login uses. sandbox.sh writes sandbox/.run/predeploy when the
# agent runs before its first deployment (the local dev identity provider signs in as the developer).
asme_console_login() {
  if [ -f "$1/sandbox/.run/predeploy" ]; then
    say "console login: local dev IdP (not deployed yet)"
  else
    say "console login: agent's own client"
  fi
}

# asme_env_value <env file> <KEY>: the last value of KEY in the file, without surrounding quotes; empty when missing.
asme_env_value() {
  [ -f "$1" ] || return 0
  sed -n "s/^$2=//p" "$1" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# asme_project <repo>: the compose project of the agent's sandbox (the same rule as its sandbox.sh).
asme_project() { printf 'sandbox-%s' "$(basename "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')"; }

# asme_console <repo>: the console URL. The login returns to localhost and its state cookie is per host, so a login
# started on 127.0.0.1 fails ("Login expired or invalid").
asme_console() {
  local port="${SANDBOX_PORT:-}"
  [ -n "$port" ] || port="$(cat "$1/sandbox/.run/port" 2>/dev/null || true)"
  printf 'http://localhost:%s/' "${port:-8080}"
}

# asme_identity <repo> <env file>: the identity the running agent uses (the last "identity: adapter" line of its log)
# and its last Workforce onboarding line. Never prints a token.
asme_identity() {
  local repo="$1" env="$2" id="" log adapter client tenant workforce block=""
  if have docker; then
    id="$(docker ps -q --filter "label=com.docker.compose.project=$(asme_project "$repo")" \
      --filter label=com.docker.compose.service=agent 2>/dev/null | head -n 1 || true)"
  fi
  if [ -z "$id" ]; then say "identity: unknown (agent not running)"; return 0; fi
  log="$(docker logs "$id" 2>&1 | sed -E 's/eyJ[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]*)*/<token>/g' || true)"
  adapter="$(printf '%s\n' "$log" | sed -n 's/.*identity: adapter \([A-Za-z0-9_.-]*\).*/\1/p' | tail -n 1 || true)"
  if [ -f "$env" ] && grep -qxF "$ASME_BEGIN" "$env"; then block=1; fi
  case "$adapter" in
    developer)
      client="$(asme_env_value "$env" CN_IDENTITY_DEVELOPER_CLIENTS)"
      [ -n "$client" ] || client="${CODENOW_AGW_CLIENT_ID:-<not set>}"
      tenant="$(gw_tenant)"
      [ -z "$tenant" ] || tenant="$tenant, "
      say "identity: developer (${tenant}client $client)" ;;
    legacy-refresh-token)
      if [ -n "$block" ]; then
        say "identity: deployment token (legacy-refresh-token); .env has the developer block: run cn-sandbox up"
      else
        say "identity: deployment token (legacy-refresh-token); run cn-sandbox up --as-me to run as yourself"
      fi ;;
    "") say "identity: unknown (no identity line in the agent log yet)" ;;
    *) say "identity: adapter $adapter" ;;
  esac
  workforce="$(printf '%s\n' "$log" | grep -E 'Workforce: (onboarding|declaration) ' | tail -n 1 \
    | sed 's/.*Workforce: /Workforce: /' || true)"
  [ -z "$workforce" ] || say "$workforce"
  [ -z "$(asme_mode "$repo")" ] || say "mode: $(asme_mode "$repo")"
  asme_console_login "$repo"
  say "console: $(asme_console "$repo") (log in on localhost, not on 127.0.0.1)"
}
