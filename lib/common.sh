# Shared helpers of the cn-* commands. Sourced, not run.

CODENOW_HOME="${CODENOW_HOME:-$HOME/.codenow}"
CODENOW_CONFIG="$CODENOW_HOME/config"
DEVKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { echo "${CN_CMD:-cn}: $*"; }
die() { echo "${CN_CMD:-cn}: $*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Settings live in ~/.codenow/config (mode 600): CODENOW_MCP_URL, KUBECONFIG_FILE. Never a token.
load_config() {
  mkdir -p "$CODENOW_HOME"
  # shellcheck disable=SC1090
  [ -f "$CODENOW_CONFIG" ] && . "$CODENOW_CONFIG"
  return 0
}

save_setting() {  # save_setting <name> <value>
  local tmp="$CODENOW_CONFIG.tmp"
  { grep -v "^$1=" "$CODENOW_CONFIG" 2>/dev/null || true; printf '%s=%q\n' "$1" "$2"; } > "$tmp"
  mv "$tmp" "$CODENOW_CONFIG"
  chmod 600 "$CODENOW_CONFIG"
}

ask_setting() {  # ask_setting <name> <question>: keeps the current value; asks only on a terminal
  local name="$1" question="$2" value
  value="${!name:-}"
  if [ -z "$value" ] && [ -t 0 ]; then
    read -r -p "${CN_CMD:-cn}: $question " value
  fi
  if [ -n "$value" ]; then
    printf -v "$name" '%s' "$value"
    save_setting "$name" "$value"
  fi
}

# run_limited <seconds> <command...>: runs a command, stops it after the limit (macOS has no timeout(1)).
# Returns the command's status, or 124 when it ran out of time.
run_limited() {
  local limit="$1"; shift
  "$@" >/dev/null 2>&1 </dev/null &
  local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$limit" ]; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$pid"
}
