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
#   conflicts  prints "line N: KEY=value" for each of the block's keys outside the block with another value
#   write      replaces the block (or appends it) with the lines on stdin; the file keeps its mode (new: 600)
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
if action == "conflicts":
    want = dict(l.split("=", 1) for l in wanted)
    for n, line in outside:
        text = line.strip()
        if text.startswith("export "):
            text = text[7:].lstrip()
        key, sep, value = text.partition("=")
        if sep and key.strip() in want:
            value = value.strip().strip('"').strip("'")
            if value != want[key.strip()]:
                print(f"line {n}: {line}")
    sys.exit(0)
if action == "remove" and start is None:
    sys.exit(0)
block = [begin, *wanted, end] if action == "write" else []
if start is None:
    new = lines + ([""] if lines and lines[-1].strip() else []) + block
else:
    new = lines[:start] + block + lines[stop + 1:]
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
  local repo="$1" env="$2" lines conflicts
  asme_pin_check "$repo"
  lines="$(asme_lines)" || exit 1
  conflicts="$(printf '%s\n' "$lines" | asme_edit "$env" conflicts)" || die "cannot read $env"
  if [ -n "$conflicts" ]; then
    say "$env sets the developer identity outside the cn-devkit block with other values:" >&2
    printf '%s\n' "$conflicts" | sed "s/^/${CN_CMD:-cn}:   /" >&2
    die "remove these lines from $env (cn-sandbox up --as-me writes the values), then run again"
  fi
  printf '%s\n' "$lines" | asme_edit "$env" write || die "could not write $env"
  say "$env: developer identity block written (client $CODENOW_AGW_CLIENT_ID)"
  if [ -n "${CODENOW_WORKFORCE_URL:-}" ]; then
    say "Workforce: $CODENOW_WORKFORCE_URL (shadow); you see the agent under you as --under-development-- <agent>"
  else
    say "no Workforce URL: the agent will not appear in Workforce (cn-setup --only-gateway sets it)"
  fi
}

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
  say "stored (~/.codenow/config): client ${CODENOW_AGW_CLIENT_ID:-<not set>}, Workforce ${CODENOW_WORKFORCE_URL:-<not set>}"
}
