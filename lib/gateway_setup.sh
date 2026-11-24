# cn-setup's optional step "Developer identity (agent gateway)" and its cn-doctor report. Sourced after common.sh and
# sandbox_token.sh by cn-setup, which defines `note` (a problem) and `problems`. Not run.
#
# The developer's own Keycloak access token, kept by oidc-agent (account CN_OIDC_ACCOUNT, default cn-agw, device flow
# with PKCE S256), works for the agent gateway (models), the tenant's CodeNOW MCP server and a local agent under the
# developer's identity (cn-sandbox token). Settings in ~/.codenow/config: CODENOW_IAM_ISSUER, CODENOW_AGW_CLIENT_ID,
# CODENOW_AGW_URL, CN_OIDC_ACCOUNT. The token is never printed and never put on a command line.

GW_PROFILE_LINE='eval "$(oidc-agent-service use)" > /dev/null'

# interactive: a person can answer (a terminal; CN_SETUP_INTERACTIVE=1 lets the tests answer on stdin).
interactive() { [ -t 0 ] || [ "${CN_SETUP_INTERACTIVE:-}" = 1 ]; }

ask_yes() {  # ask_yes <question>: true on y or yes; false without a person to ask
  local answer=""
  interactive || return 1
  read -r -p "${CN_CMD:-cn}: $1 [y/N] " answer || return 1
  case "$answer" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
}

ask_default() {  # ask_default <name> <question> <default>: keeps a set value; else asks (Enter takes the default)
  local name="$1" question="$2" default="${3:-}" value
  value="${!name:-}"
  if [ -z "$value" ] && interactive; then
    read -r -p "${CN_CMD:-cn}: $question${default:+ [$default]} " value || value=""
    value="${value:-$default}"
  fi
  [ -n "$value" ] || value="$default"
  if [ -n "$value" ]; then
    printf -v "$name" '%s' "$value"
    save_setting "$name" "$value"
  fi
}

gw_account() { printf '%s' "${CN_OIDC_ACCOUNT:-cn-agw}"; }

# gw_url_ok <url>: https, or http only for localhost.
gw_url_ok() {
  case "$1" in https://?*|http://localhost*|http://127.0.0.1*) return 0 ;; *) return 1 ;; esac
}

# gw_tenant: <tenant> of CODENOW_MCP_URL https://mcp-server-<tenant>.<domain>/mcp, or nothing.
gw_tenant() {
  local host
  host="$(printf '%s' "${CODENOW_MCP_URL:-}" | sed -E -e 's#^[a-z]+://##' -e 's#[/:].*$##')"
  case "$host" in mcp-server-?*.*) host="${host#mcp-server-}"; printf '%s' "${host%%.*}" ;; esac
}

# gw_issuer_from_mcp: the first authorization server of the MCP server's OAuth protected-resource metadata.
gw_issuer_from_mcp() {
  local origin
  origin="$(printf '%s' "${CODENOW_MCP_URL:-}" | sed -E 's#^(https?://[^/]+).*#\1#')"
  [ -n "$origin" ] || return 1
  curl -fsS --max-time 10 "$origin/.well-known/oauth-protected-resource" 2>/dev/null | python3 -I -c '
import json, sys
servers = json.load(sys.stdin).get("authorization_servers") or []
print(servers[0] if servers and isinstance(servers[0], str) else "")'
}

# 1. Values: derived where possible, asked once, stored in ~/.codenow/config.
gw_values() {
  local found="" tenant environment="" client_default=""
  CN_OIDC_ACCOUNT="$(gw_account)"
  save_setting CN_OIDC_ACCOUNT "$CN_OIDC_ACCOUNT"
  if [ -z "${CODENOW_IAM_ISSUER:-}" ] && [ -n "${CODENOW_MCP_URL:-}" ]; then
    found="$(gw_issuer_from_mcp || true)"
    [ -z "$found" ] || say "IAM issuer from the MCP server's metadata: $found"
  fi
  ask_default CODENOW_IAM_ISSUER "IAM issuer (https://<iam host>/auth/realms/<realm>):" "$found"
  tenant="$(gw_tenant)"
  if [ -z "${CODENOW_AGW_CLIENT_ID:-}" ] && [ -n "$tenant" ] && interactive; then
    read -r -p "${CN_CMD:-cn}: environment of your agent gateway (e.g. demo-environment): " environment || environment=""
    [ -z "$environment" ] || client_default="$tenant-$environment-agent-gateway"
  fi
  ask_default CODENOW_AGW_CLIENT_ID "Keycloak client of the agent gateway (<tenant>-<environment>-agent-gateway):" \
    "$client_default"
  ask_default CODENOW_AGW_URL \
    "agent gateway URL (https://agent-gateway.${environment:-<environment>}.${tenant:-<tenant>}.<domain>):" ""
  if [ -n "${CODENOW_AGW_URL:-}" ]; then CODENOW_AGW_URL="${CODENOW_AGW_URL%/}"; save_setting CODENOW_AGW_URL "$CODENOW_AGW_URL"; fi
  local missing="" name
  for name in CODENOW_IAM_ISSUER CODENOW_AGW_CLIENT_ID CODENOW_AGW_URL; do [ -n "${!name:-}" ] || missing="$missing $name"; done
  if [ -n "$missing" ]; then note "developer identity: missing$missing (run cn-setup --only-gateway in a terminal)"; return 1; fi
  for name in CODENOW_IAM_ISSUER CODENOW_AGW_URL; do
    gw_url_ok "${!name}" || { note "developer identity: $name must use https:// (${!name})"; return 1; }
  done
  say "developer identity: issuer $CODENOW_IAM_ISSUER, client $CODENOW_AGW_CLIENT_ID, gateway $CODENOW_AGW_URL, account $CN_OIDC_ACCOUNT"
}

# 2. oidc-agent 5.2.0 or newer; installed with consent on macOS (brew), never with sudo.
gw_oidc_agent() {
  local hint version
  hint="$(install_hint oidc-agent)"
  if ! have oidc-agent; then
    case "$(uname -s)" in
      Darwin)
        if [ -z "${GW_REPORT:-}" ] && have brew && ask_yes "oidc-agent is missing. Run  $hint  now?"; then
          { brew tap indigo-dc/oidc-agent && brew install oidc-agent; } || { note "brew did not install oidc-agent"; return 1; }
        else
          note "oidc-agent is missing:  $hint"; return 1
        fi ;;
      Linux)
        if grep -qi microsoft /proc/version 2>/dev/null; then note "oidc-agent is missing (WSL):  $hint"
        else note "oidc-agent is missing:  $hint"; fi
        return 1 ;;
      *) note "oidc-agent runs in WSL on Windows: open WSL and run cn-setup there"; return 1 ;;
    esac
  fi
  version="$(oidc-agent --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
  if [ -z "$version" ] || [ "$(printf '%s\n%s\n' "$OIDC_AGENT_MIN" "$version" | sort -V | head -n 1)" != "$OIDC_AGENT_MIN" ]; then
    note "oidc-agent ${version:-of unknown version} is older than $OIDC_AGENT_MIN (PKCE): update it ($hint)"
    return 1
  fi
  say "found oidc-agent $version"
}

# 3. The shell profile starts oidc-agent in every shell (asked; idempotent). Also starts it for this run.
gw_profile() {
  local profile="$HOME/.$(basename "${SHELL:-bash}")rc"
  if [ -f "$profile" ] && grep -qF 'oidc-agent-service use' "$profile"; then
    say "$profile starts oidc-agent: ok"
  elif ask_yes "Add  $GW_PROFILE_LINE  to $profile (starts oidc-agent with every shell)?"; then
    printf '\n# oidc-agent for the CodeNOW agent gateway (cn-setup)\n%s\n' "$GW_PROFILE_LINE" >> "$profile"
    say "added the oidc-agent line to $profile (open a new terminal, or run it once)"
  else
    note "oidc-agent does not start with your shell: add  $GW_PROFILE_LINE  to $profile"
  fi
  if have oidc-agent-service; then eval "$(oidc-agent-service use 2>/dev/null)" >/dev/null 2>&1 || true; fi
}

gw_agent_dir() {
  if [ -n "${OIDC_CONFIG_DIR:-}" ]; then printf '%s' "$OIDC_CONFIG_DIR"
  elif [ -d "$HOME/.oidc-agent" ] && [ ! -d "$HOME/.config/oidc-agent" ]; then printf '%s' "$HOME/.oidc-agent"
  else printf '%s' "$HOME/.config/oidc-agent"; fi
}

# 4. PKCE: oidc-agent sends PKCE at the device endpoint only from custom_parameters.config. The pair for this
# account is added when missing (asked); entries of other accounts stay.
gw_pkce() {
  local account dir file question verifier challenge
  account="$(gw_account)"; dir="$(gw_agent_dir)"; file="$dir/custom_parameters.config"
  if [ -f "$file" ] && python3 -I - "$file" "$account" <<'PY'
import json, sys
try:
    entries = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(1)
names = {e.get("parameter") for e in entries if isinstance(e, dict) and sys.argv[2] in (e.get("for_account") or [])}
sys.exit(0 if {"code_challenge", "code_challenge_method", "code_verifier"} <= names else 1)
PY
  then
    say "PKCE parameters for $account: ok ($file)"; return 0
  fi
  if [ -f "$file" ]; then question="Rewrite $file to add the PKCE pair for $account (other accounts' entries stay)?"
  else question="Write the PKCE pair for $account to $file (Keycloak requires PKCE S256 for the device flow)?"; fi
  ask_yes "$question" || { note "no PKCE parameters for $account: oidc-gen will fail with 'Missing parameter: code_challenge_method'"; return 1; }
  have openssl || { note "openssl is missing (needed for the PKCE pair)"; return 1; }
  verifier="$(openssl rand -base64 48 | tr '+/' '-_' | tr -d '=\n')"
  challenge="$(printf '%s' "$verifier" | openssl dgst -sha256 -binary | openssl base64 | tr '+/' '-_' | tr -d '=\n')"
  ( umask 077; mkdir -p "$dir" )
  printf '%s\n%s\n' "$challenge" "$verifier" | python3 -I -c '
import json, os, sys, tempfile
path, account = sys.argv[1], sys.argv[2]
challenge, verifier = sys.stdin.read().split()
try:
    entries = json.load(open(path))
    entries = entries if isinstance(entries, list) else []
except (OSError, ValueError):
    entries = []
keep = []
for e in entries:
    if isinstance(e, dict) and account in (e.get("for_account") or []) and e.get("parameter") in (
            "code_challenge", "code_challenge_method", "code_verifier"):
        rest = [a for a in e["for_account"] if a != account]
        if not rest:
            continue
        e = {**e, "for_account": rest}
    keep.append(e)
keep += [{"parameter": "code_challenge", "value": challenge, "for_account": [account], "request": ["device-init"]},
         {"parameter": "code_challenge_method", "value": "S256", "for_account": [account], "request": ["device-init"]},
         {"parameter": "code_verifier", "value": verifier, "for_account": [account], "request": ["device-polling"]}]
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
with os.fdopen(fd, "w") as out:
    json.dump(keep, out, indent=2)
os.chmod(tmp, 0o600)
os.replace(tmp, path)' "$file" "$account"
  say "PKCE parameters for $account written to $file"
  if have oidc-agent-service; then   # the agent reads the file only when it starts
    oidc-agent-service restart >/dev/null 2>&1 || true
    eval "$(oidc-agent-service use 2>/dev/null)" >/dev/null 2>&1 || true
  fi
}

# 5. The account: created with the device flow when oidc-add does not list it (asked; needs a person).
gw_create_account() {
  local account password=""
  account="$(gw_account)"
  if oidc-add -l 2>/dev/null | grep -qx "$account"; then say "oidc-agent account $account: ok"; return 0; fi
  if ! interactive; then note "no oidc-agent account $account: run cn-setup --only-gateway in a terminal"; return 1; fi
  ask_yes "Create the oidc-agent account $account now (device flow: open the URL it prints and confirm the code)?" \
    || { note "no oidc-agent account $account"; return 1; }
  read -rs -p "${CN_CMD:-cn}: new password for the oidc-agent account file (local, not your Keycloak password): " password || true
  echo
  [ -n "$password" ] || { note "no password given: the account was not created"; return 1; }
  if OIDC_ENCRYPTION_PW="$password" oidc-gen "$account" --iss="$CODENOW_IAM_ISSUER" --client-id="$CODENOW_AGW_CLIENT_ID" \
      --client-secret=public --flow=device --scope="openid profile offline_access" --prompt=none --confirm-default \
      --pw-env; then
    password=""
    say "oidc-agent account $account created (after a reboot: oidc-add $account)"
  else
    password=""
    note "oidc-gen $account failed (see the troubleshooting table in the devkit README)"
    return 1
  fi
}

# 6. The check: a token, its claims (never the token), the gateway's models and the MCP server's initialize.
gw_check() {
  local account token claims aud azp user tmp code ok=0
  account="$(gw_account)"
  if ! token="$(oidc-token --time=60 "$account" 2>/dev/null </dev/null)" || [ -z "$token" ]; then
    note "oidc-token $account fails: open a new terminal, then  oidc-add $account  (an expired session: oidc-gen $account --reauthenticate)"
    return 1
  fi
  claims="$(printf '%s' "$token" | python3 -I -c '
import base64, json, sys
parts = sys.stdin.read().strip().split(".")
try:
    c = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
except Exception:
    c = {}
aud = c.get("aud") or []
aud = [aud] if isinstance(aud, str) else aud
print(" ".join(a.rstrip("/") for a in aud if isinstance(a, str)))
print(c.get("azp") or "")
print(c.get("preferred_username") or "")' || true)"
  aud="$(printf '%s\n' "$claims" | sed -n 1p)"; azp="$(printf '%s\n' "$claims" | sed -n 2p)"
  user="$(printf '%s\n' "$claims" | sed -n 3p)"
  case " $aud " in *" ${CODENOW_AGW_URL%/} "*) ;; *) note "the token's audience ($aud) lacks the gateway ${CODENOW_AGW_URL%/}: the client needs the Audience mapper; then oidc-token --force-new $account"; ok=1 ;; esac
  [ "$azp" = "${CODENOW_AGW_CLIENT_ID:-}" ] || { note "the token's client is $azp, not $CODENOW_AGW_CLIENT_ID"; ok=1; }
  say "token of ${user:-<no preferred_username>} (client $azp, valid at least 60 s)"
  tmp="$(mktemp)"
  code="$(printf 'Authorization: Bearer %s\n' "$token" | curl -sS --max-time 15 -H @- -o "$tmp" -w '%{http_code}' \
    "${CODENOW_AGW_URL%/}/v1/models" 2>/dev/null || true)"
  if [ "$code" = 200 ]; then
    say "agent gateway: models $(python3 -I -c '
import json, sys
print(", ".join(str(m.get("id")) for m in json.load(open(sys.argv[1])).get("data") or []) or "none")' "$tmp" 2>/dev/null || echo "?")"
  else
    note "agent gateway: GET /v1/models answered ${code:-nothing} (401: oidc-token --force-new $account; 403: none of your teams may use a model)"
    ok=1
  fi
  rm -f "$tmp"
  if [ -n "${CODENOW_MCP_URL:-}" ]; then
    code="$(printf 'Authorization: Bearer %s\nContent-Type: application/json\nAccept: application/json, text/event-stream\n' "$token" \
      | curl -sS --max-time 15 -X POST -H @- -o /dev/null -w '%{http_code}' \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"cn-setup","version":"1"}}}' \
        "$CODENOW_MCP_URL" 2>/dev/null || true)"
    if [ "$code" = 200 ]; then say "CodeNOW MCP server: initialize with your token: ok"
    else note "CodeNOW MCP server: initialize with your token answered ${code:-nothing} (403: you are not a member of the tenant)"; ok=1; fi
  fi
  token=""
  return "$ok"
}

# The setup step (cn-setup; cn-setup --only-gateway).
gateway_step() {
  say "Developer identity (agent gateway): your own Keycloak token for the agent gateway, the CodeNOW MCP server and a local agent"
  gw_values || return 0
  gw_oidc_agent || return 0
  gw_profile
  gw_pkce || return 0
  gw_create_account || return 0
  gw_check && say "developer identity: ready (a local agent: CN_IDENTITY_PROVIDER=developer, CN_IDENTITY_DEVELOPER_CLIENTS=$CODENOW_AGW_CLIENT_ID; cn-sandbox up)" || true
}

# The cn-doctor report: the stored values and the check; only the oidc-agent check when the step was never run.
gateway_report() {
  if [ -z "${CODENOW_AGW_URL:-}" ]; then
    oidc_check || problems=$((problems + 1))
    say "developer identity (agent gateway): not set up (optional): cn-setup --only-gateway"
    return 0
  fi
  GW_REPORT=1   # cn-doctor changes nothing
  say "developer identity: issuer ${CODENOW_IAM_ISSUER:-<missing>}, client ${CODENOW_AGW_CLIENT_ID:-<missing>}, gateway $CODENOW_AGW_URL, account $(gw_account)"
  gw_oidc_agent || return 0
  gw_check || true
}
