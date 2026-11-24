# cn-sandbox forget [--yes] [--reason TEXT]: remove your development instance of this agent from Workforce.
# Sourced by cn-sandbox after common.sh, sandbox_token.sh, gateway_setup.sh (interactive, ask_yes) and as_me.sh. Not run.
#
# A local agent under your own identity appears in Workforce as `--under-development-- <component>`, the instance
# dev-<username>-<component>. `forget` offboards it there (POST <Workforce>/workforce/api/instances/<id>/forget with
# your own token): only your own; your next `cn-sandbox up` as you declares it again. The Workforce URL is
# CODENOW_WORKFORCE_URL (~/.codenow/config), else WORKFORCE_URL of the agent's .env. The token is never printed and
# never put on a command line: Python reads it on stdin.

# forget_component <repo>: the agent's name (agent_name in agent-config/config.yaml, the component name the agent
# declares), else the repository folder's name.
forget_component() {
  local name=""
  [ -f "$1/agent-config/config.yaml" ] && name="$(sed -n 's/^[[:space:]]*agent_name:[[:space:]]*//p' \
    "$1/agent-config/config.yaml" | head -n 1 | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' \
    -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/")"
  case "$name" in ""|*"{{"*) name="$(basename "$1")" ;; esac
  printf '%s' "$name"
}

# forget_url <env file>: the Workforce base URL without a trailing slash; empty when none is stored.
forget_url() {
  local url="${CODENOW_WORKFORCE_URL:-}"
  [ -n "$url" ] || url="$(asme_env_value "$1" WORKFORCE_URL)"
  printf '%s' "${url%/}"
}

# The token arrives on stdin, never as an argument. "id <component>" prints "<username> <instance id>"; "post <url>
# <reason>" sends the forget and prints "<status> <detail or forgotten flag>".
FORGET_PY="$(cat <<'PY'
import base64, json, re, sys, urllib.error, urllib.request
token = sys.stdin.read().strip()
mode = sys.argv[1]
if mode == "id":
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        sys.exit("the token is no JWT")
    user = claims.get("preferred_username") or ""
    if not isinstance(user, str) or not user:
        sys.exit("the token has no preferred_username")
    slug = lambda s: re.sub(r"[^a-z0-9._-]+", "-", s.lower())
    print(user, f"dev-{slug(user)}-{slug(sys.argv[2])}")
    sys.exit(0)
url, reason = sys.argv[2], sys.argv[3]
body = json.dumps({"reason": reason} if reason else {}).encode()
request = urllib.request.Request(url, data=body, method="POST", headers={
    "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=30) as answer:
        status, text = answer.status, answer.read().decode("utf-8", "replace")
except urllib.error.HTTPError as err:
    status, text = err.code, err.read().decode("utf-8", "replace")
except Exception as err:  # no answer: say what kind of failure, never the request
    print("0", type(err).__name__)
    sys.exit(0)
try:
    data = json.loads(text)
except ValueError:
    data = {}
if status == 200:
    print(status, "true" if data.get("forgotten") else "false")
else:
    detail = data.get("detail") if isinstance(data, dict) else ""
    print(status, (detail if isinstance(detail, str) else json.dumps(detail))[:300].replace("\n", " "))
PY
)"

# forget_token: your own access token (oidc-agent account CN_OIDC_ACCOUNT, default cn-agw) on stdout, for $( ).
forget_token() {
  have oidc-token || die "oidc-token is missing (oidc-agent ${OIDC_AGENT_MIN:-}+):  $(install_hint oidc-agent)"
  if [ -z "${OIDC_SOCK:-}" ] && have oidc-agent-service; then eval "$(oidc-agent-service use 2>/dev/null)" >/dev/null 2>&1 || true; fi
  oidc-token --time=60 "$(token_account)" 2>/dev/null </dev/null \
    || die "oidc-token $(token_account) gave no token: load the account with  oidc-add $(token_account)"
}

# forget_run <repo> <env file> <yes: 0|1> <reason>
forget_run() {
  local repo="$1" env="$2" yes="$3" reason="$4" url component token ids user id answer status detail
  url="$(forget_url "$env")"
  [ -n "$url" ] || die "no Workforce URL: set it with cn-setup --only-gateway (CODENOW_WORKFORCE_URL)"
  component="$(forget_component "$repo")"
  token="$(forget_token)" || exit 1
  [ -n "$token" ] || die "oidc-token $(token_account) gave no token: load the account with  oidc-add $(token_account)"
  ids="$(printf '%s' "$token" | python3 -I -c "$FORGET_PY" id "$component")" || die "cannot read your username from the token"
  user="${ids%% *}"; id="${ids#* }"
  say "Workforce: $url"
  say "your development instance: $id (--under-development-- $component, developer $user)"
  if [ "$yes" != 1 ]; then
    interactive || die "not a terminal: run cn-sandbox forget --yes to remove $id"
    ask_yes "Remove your development instance $id from Workforce?" || { say "nothing changed"; return 0; }
  fi
  answer="$(printf '%s' "$token" | python3 -I -c "$FORGET_PY" post "$url/workforce/api/instances/$id/forget" "$reason")" \
    || die "the call to Workforce failed"
  status="${answer%% *}"; detail="${answer#* }"
  case "$status" in
    200) if [ "$detail" = true ]; then say "removed: $id is offboarded in Workforce (cn-sandbox up as you declares it again)"
         else say "$id was offboarded already: nothing changed"; fi ;;
    404) say "Workforce has no development instance $id: nothing to forget" ;;
    401) die "Workforce refused your token (401): ${detail:-invalid token}; check oidc-token $(token_account)" ;;
    403) die "Workforce refused (403): $detail" ;;
    0)   die "no answer from $url ($detail)" ;;
    *)   die "Workforce answered $status: $detail" ;;
  esac
}
