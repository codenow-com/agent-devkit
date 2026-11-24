# The sandbox hub (cn-sandbox hub): one local page with every agent sandbox on this computer, served by
# lib/cn_hub.py on 127.0.0.1:CN_SANDBOX_HUB_PORT (default 8079). Sourced after common.sh, not run.
#
# One hub per computer: its pid and log are in ~/.codenow/sandbox-hub/. `cn-sandbox up` starts it when it is not
# running (CN_SANDBOX_HUB=off: never). It reads Docker and the sandboxes' state files; it never changes them.

hub_dir() { printf '%s' "$CODENOW_HOME/sandbox-hub"; }
hub_port() { printf '%s' "${CN_SANDBOX_HUB_PORT:-8079}"; }
hub_url() { printf 'http://localhost:%s/' "$(hub_port)"; }
hub_py() { printf '%s' "$DEVKIT_DIR/lib/cn_hub.py"; }

# hub_pid: the pid of the running hub that this devkit started, or nothing (return 1).
hub_pid() {
  local pidf pid
  pidf="$(hub_dir)/hub.pid"
  [ -f "$pidf" ] || return 1
  pid="$(cat "$pidf" 2>/dev/null || true)"
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q -- "cn_hub.py" || return 1
  printf '%s' "$pid"
}

# hub_ping: a sandbox hub answers on the port (this one or one started elsewhere).
hub_ping() { python3 "$(hub_py)" --ping --port "$(hub_port)" >/dev/null 2>&1; }

# hub_start: start the hub in the background unless it runs; print its URL. Returns 1 when it cannot start.
hub_start() {
  local dir pid log i
  if pid="$(hub_pid)"; then say "sandbox hub already running (pid $pid): $(hub_url)"; return 0; fi
  have python3 || { say "the sandbox hub needs python3" >&2; return 1; }
  if hub_ping; then say "sandbox hub already running: $(hub_url)"; return 0; fi
  dir="$(hub_dir)"
  ( umask 077; mkdir -p "$dir" )
  log="$dir/hub.log"
  : > "$log"
  CN_SANDBOX_HUB_PORT="$(hub_port)" nohup python3 "$(hub_py)" --port "$(hub_port)" >>"$log" 2>&1 </dev/null &
  pid=$!
  echo "$pid" > "$dir/hub.pid"
  i=0
  while [ "$i" -lt 50 ]; do
    if hub_ping; then say "sandbox hub started (pid $pid): $(hub_url)"; return 0; fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
    i=$((i + 1))
  done
  rm -f "$dir/hub.pid"
  if grep -q "is in use" "$log" 2>/dev/null; then
    say "port $(hub_port) is taken by another program: choose a free port, e.g.  CN_SANDBOX_HUB_PORT=8078 cn-sandbox hub" >&2
  else
    kill "$pid" 2>/dev/null || true
    say "the sandbox hub did not start; see $log" >&2
  fi
  return 1
}

hub_stop() {
  local pid
  if pid="$(hub_pid)"; then
    kill "$pid" 2>/dev/null || true
    say "sandbox hub stopped (pid $pid)"
  else
    say "sandbox hub is not running"
  fi
  rm -f "$(hub_dir)/hub.pid"
}

# hub_status: prints the state; returns 0 when the hub runs.
hub_status() {
  local pid
  if pid="$(hub_pid)"; then say "sandbox hub running (pid $pid): $(hub_url)"; return 0; fi
  if hub_ping; then say "sandbox hub running (not started from $(hub_dir)): $(hub_url)"; return 0; fi
  say "sandbox hub is not running; start it with: cn-sandbox hub"
  return 1
}

# hub_for_up: after `cn-sandbox up`: start the hub when needed and print the page's URL. Never fails `up`.
hub_for_up() {
  case "${CN_SANDBOX_HUB:-on}" in off|0|no|false) return 0 ;; esac
  if hub_pid >/dev/null || hub_ping || hub_start >/dev/null 2>&1; then
    say "sandboxes: $(hub_url)"
  else
    say "sandbox hub not started (port $(hub_port) taken? set CN_SANDBOX_HUB_PORT, then: cn-sandbox hub)"
  fi
  return 0
}
