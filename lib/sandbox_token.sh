# The developer's own access token for a local agent (cn-sandbox token, cn-doctor). Sourced after common.sh, not run.
#
# oidc-agent keeps the developer's Keycloak login (account CN_OIDC_ACCOUNT, default cn-agw, the account the agent
# gateway's tools use). `oidc-token --time=120 <account>` gives an access token valid for at least 120 more seconds;
# it is written atomically (mode 600) to CN_IDENTITY_TOKEN_FILE (default ~/.codenow/sandbox-token/token, a folder of
# its own, never in a repository). The agent's SDK reads that file (CN_IDENTITY_PROVIDER=developer).

OIDC_AGENT_MIN=5.2.0
TOKEN_SECONDS=120

token_account() { printf '%s' "${CN_OIDC_ACCOUNT:-cn-agw}"; }

# token_file_path [env-file]: CN_IDENTITY_TOKEN_FILE from the environment, else from the env file, else the default.
token_file_path() {
  local value="${CN_IDENTITY_TOKEN_FILE:-}"
  if [ -z "$value" ] && [ -n "${1:-}" ] && [ -f "$1" ]; then
    value="$(sed -n 's/^CN_IDENTITY_TOKEN_FILE=//p' "$1" | tail -n 1 | sed -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"
  fi
  [ -n "$value" ] || value="$CODENOW_HOME/sandbox-token/token"
  printf '%s' "${value/#\~/$HOME}"
}

# token_dir_ok <file>: the token's folder must be its own: not /, not HOME itself, not inside a git repository.
token_dir_ok() {
  local dir existing
  dir="$(dirname "$1")"
  case "$dir" in /|"$HOME"|"$HOME/") die "CN_IDENTITY_TOKEN_FILE must be in its own folder, not directly in $dir (e.g. ~/.codenow/sandbox-token/token)" ;; esac
  existing="$dir"   # the nearest folder that exists: a folder still to be made may be inside a repository too
  while [ ! -d "$existing" ] && [ "$existing" != / ] && [ "$existing" != . ]; do existing="$(dirname "$existing")"; done
  if git -C "$existing" rev-parse --git-dir >/dev/null 2>&1; then
    die "CN_IDENTITY_TOKEN_FILE ($1) is inside a git repository: keep the token outside every repository"
  fi
}

# token_write <file>: one fresh token into <file> (temporary file in the same folder, then rename). Never prints it.
token_write() {
  local file="$1" dir tmp token
  token_dir_ok "$file"
  have oidc-token || die "oidc-token is missing (oidc-agent ${OIDC_AGENT_MIN}+):  $(install_hint oidc-agent)"
  dir="$(dirname "$file")"
  ( umask 077; mkdir -p "$dir" )
  chmod 700 "$dir"
  if ! token="$(oidc-token --time="$TOKEN_SECONDS" "$(token_account)" 2>/dev/null </dev/null)"; then
    say "oidc-token $(token_account) failed: load the account with  oidc-add $(token_account)  (or create it, see the README)" >&2
    return 1
  fi
  case "$token" in
    *.*.*) ;;
    *) say "oidc-token $(token_account) gave no access token (not a JWT)" >&2; return 1 ;;
  esac
  tmp="$(umask 077; mktemp "$dir/.token.XXXXXX")"
  printf '%s' "$token" > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$file"
}

watch_pid_file() { printf '%s' "$(dirname "$1")/watch.pid"; }

# watch_alive <file>: the pid of a running watch loop for <file>, or nothing.
watch_alive() {
  local pidf pid
  pidf="$(watch_pid_file "$1")"
  [ -f "$pidf" ] || return 1
  pid="$(cat "$pidf" 2>/dev/null || true)"
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q -- "token --watch" || return 1
  printf '%s' "$pid"
}

# token_watch <file>: refresh every CN_SANDBOX_TOKEN_INTERVAL seconds (default 45) until stopped.
token_watch() {
  local file="$1" interval="${CN_SANDBOX_TOKEN_INTERVAL:-45}" failing=0
  while :; do
    if token_write "$file"; then
      [ "$failing" = 0 ] || say "token refreshed again ($(date '+%H:%M:%S'))"
      failing=0
    else
      failing=1
    fi
    sleep "$interval"
  done
}

# watch_start <file> <command>: start `<command> token --watch` in the background once (pid file next to the token).
watch_start() {
  local file="$1" cmd="$2" pid log
  if pid="$(watch_alive "$file")"; then say "token refresh already running (pid $pid)"; return 0; fi
  log="$(dirname "$file")/watch.log"
  ( umask 077; : > "$log" )
  CN_IDENTITY_TOKEN_FILE="$file" nohup "$cmd" token --watch >>"$log" 2>&1 </dev/null &
  echo $! > "$(watch_pid_file "$file")"
  say "token refresh started in the background (pid $!, every ${CN_SANDBOX_TOKEN_INTERVAL:-45} s, log $log)"
}

watch_stop() {
  local file="$1" pid
  if pid="$(watch_alive "$file")"; then
    kill "$pid" 2>/dev/null || true
    say "token refresh stopped (pid $pid)"
  fi
  rm -f "$(watch_pid_file "$file")"
}

# One refresh loop serves every sandbox of this user (several agents can run at once, each on its own port). Each
# agent repository that uses it has a file in <token folder>/users/: line 1 the repository, line 2 its compose
# project, line 3 the time of `up`. `up` adds its repository and starts the loop when it is not running; `down` and
# `as-me off` remove theirs and stop the loop only when no other sandbox is left. A mkdir lock (<token
# folder>/users.lock; macOS has no flock) makes the check and the change one step.
TOKEN_USER_GRACE="${CN_SANDBOX_TOKEN_GRACE:-300}"   # seconds an entry counts as alive: its sandbox may still start

users_dir() { printf '%s/users' "$(dirname "$1")"; }
user_key() { printf '%s' "$1" | cksum | cut -d' ' -f1; }

# users_lock <file>: wait for the lock; a lock whose owner is gone, or one held for about 10 s, is taken over.
users_lock() {
  local lock tries=0 owner
  lock="$(dirname "$1")/users.lock"
  until mkdir "$lock" 2>/dev/null; do
    owner="$(cat "$lock/pid" 2>/dev/null || true)"
    tries=$((tries + 1))
    if { [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; } || [ "$tries" -ge 100 ]; then
      rm -rf "$lock"
      tries=0
      continue
    fi
    sleep 0.1
  done
  echo "$$" > "$lock/pid"
}
users_unlock() { rm -rf "$(dirname "$1")/users.lock"; }

users_add() {
  local dir
  dir="$(users_dir "$1")"
  ( umask 077; mkdir -p "$dir" )
  printf '%s\n%s\n%s\n' "$2" "$3" "$(date +%s)" > "$dir/$(user_key "$2")"
}
users_remove() { rm -f "$(users_dir "$1")/$(user_key "$2")"; }

# users_prune <file>: drop the entries whose repository is gone or whose compose project has no running container.
# An entry younger than TOKEN_USER_GRACE stays, and so does every entry when docker does not answer.
users_prune() {
  local dir f repo project since now id
  dir="$(users_dir "$1")"
  [ -d "$dir" ] || return 0
  now="$(date +%s)"
  for f in "$dir"/*; do
    [ -f "$f" ] || continue
    repo="$(sed -n 1p "$f")"; project="$(sed -n 2p "$f")"; since="$(sed -n 3p "$f")"
    case "$since" in ''|*[!0-9]*) since=0 ;; esac
    if [ -n "$repo" ] && [ -d "$repo" ]; then
      [ $((now - since)) -ge "$TOKEN_USER_GRACE" ] || continue
      have docker || continue
      id="$(docker ps -q --filter "label=com.docker.compose.project=$project" 2>/dev/null)" || continue
      [ -z "$id" ] || continue
    fi
    rm -f "$f"
    say "token refresh: no sandbox runs for ${repo:-an unknown repository}; removed from its list"
  done
}

users_count() {
  local dir f n=0
  dir="$(users_dir "$1")"
  if [ -d "$dir" ]; then
    for f in "$dir"/*; do
      if [ -f "$f" ]; then n=$((n + 1)); fi
    done
  fi
  echo "$n"
}

# token_share_start <file> <repo> <project> <command>: add the repository; start the loop when it is not running.
token_share_start() {
  users_lock "$1"
  users_add "$1" "$2" "$3"
  watch_start "$1" "$4"
  users_unlock "$1"
}

# token_share_stop <file> <repo>: remove the repository; stop the loop only when no other sandbox uses it.
token_share_stop() {
  local file="$1" n
  [ -d "$(dirname "$file")" ] || return 0
  users_lock "$file"
  users_remove "$file" "$2"
  users_prune "$file"
  n="$(users_count "$file")"
  if [ "$n" = 0 ]; then
    if watch_alive "$file" >/dev/null; then watch_stop "$file"; fi
  elif watch_alive "$file" >/dev/null; then
    say "token refresh keeps running for $n other sandbox(es)"
  fi
  users_unlock "$file"
}

# token_share_clear <file>: `token --stop`: stop the loop whoever uses it, and empty the list.
token_share_clear() {
  local file="$1"
  watch_stop "$file"
  [ -d "$(dirname "$file")" ] || return 0
  users_lock "$file"
  rm -rf "$(users_dir "$file")"
  users_unlock "$file"
}

# token_share_status <file>: "token refresh: running for N sandbox(es)" or "not running". Never prints the token.
token_share_status() {
  local file="$1" n
  if [ -d "$(dirname "$file")" ] && watch_alive "$file" >/dev/null; then
    users_lock "$file"
    users_prune "$file"
    n="$(users_count "$file")"
    users_unlock "$file"
    say "token refresh: running for $n sandbox(es)"
  else
    say "token refresh: not running"
  fi
}

# oidc_check: cn-doctor's report on oidc-agent (prints; returns 1 when there is a problem). Optional tool: not
# installed is no problem.
oidc_check() {
  local version account
  account="$(token_account)"
  if ! have oidc-agent; then
    say "not found: oidc-agent (optional; a local agent under your own identity):  $(install_hint oidc-agent)"
    return 0
  fi
  version="$(oidc-agent --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)"
  if [ -z "$version" ] || [ "$(printf '%s\n%s\n' "$OIDC_AGENT_MIN" "$version" | sort -V | head -n 1)" != "$OIDC_AGENT_MIN" ]; then
    say "oidc-agent ${version:-of unknown version} is older than $OIDC_AGENT_MIN (PKCE at the device endpoint):  $(install_hint oidc-agent)"
    return 1
  fi
  if ! have oidc-token; then say "oidc-agent $version has no oidc-token in PATH"; return 1; fi
  if run_limited 15 oidc-token --time=60 "$account"; then
    say "oidc-agent $version: oidc-token $account works"
  else
    say "oidc-agent $version: oidc-token $account fails: load the account with  oidc-add $account  (or create it, see the README)"
    return 1
  fi
}
