# cn-setup's optional step "Google ADK tools" and its cn-doctor report; cn-sandbox status uses adk_repo_hint. Sourced
# after common.sh, uv_env.sh and gateway_setup.sh (interactive, ask_yes). cn-setup defines `note` (a problem). Not run.
#
# The adk CLI (adk web, adk run, adk eval; the VS Code ADK extension looks for it) is installed with
# `uv tool install google-adk==<pin>`, the pin of the newest ADK agent template, the same repository as cn-warm's.
# gcloud is only offered: CodeNOW agents get their models through the CodeNOW agent gateway with the developer's
# identity and deploy through CodeNOW. Settings in ~/.codenow/config: CN_ADK=yes|no. Never sudo, never curl | sh.

CN_ADK_REPO_DEFAULT="https://gitlab.cloud.codenow.com/codenow-dev/demo-tenant/demo-tenant-adk-based-agent.git"
ADK_PYTHON="${CN_ADK_PYTHON:-3.12}"
ADK_PIN=""
ADK_PIN_SOURCE=""

# adk_req_pin <requirements.txt>: the google-adk version pinned with == (extras such as [a2a] allowed), or nothing.
adk_req_pin() {
  [ -f "$1" ] || return 0
  sed -n -E 's/^[[:space:]]*google[-_.]adk(\[[^]]*\])?[[:space:]]*==[[:space:]]*([0-9][0-9A-Za-z.+!]*).*/\2/p' "$1" \
    | head -n 1
}

# adk_template_repo: CN_ADK_REPO, else the ADK entry of CN_WARM_REPOS, else the ADK template (<git url>[#<ref>]).
adk_template_repo() {
  local r
  if [ -n "${CN_ADK_REPO:-}" ]; then printf '%s' "$CN_ADK_REPO"; return 0; fi
  for r in ${CN_WARM_REPOS:-}; do
    case "${r%%#*}" in *adk*) printf '%s' "$r"; return 0 ;; esac
  done
  printf '%s' "$CN_ADK_REPO_DEFAULT"
}

# adk_pypi_newest: the newest google-adk on public PyPI, or nothing.
adk_pypi_newest() {
  curl -fsS --max-time 15 https://pypi.org/pypi/google-adk/json 2>/dev/null \
    | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null || true
}

# adk_pin: sets ADK_PIN and ADK_PIN_SOURCE from the newest ADK template's requirements.txt (the highest tag
# <name>-v<x.y.z>, as cn-warm), else from PyPI. False when neither answers.
adk_pin() {
  local repo url ref name dir
  ADK_PIN=""; ADK_PIN_SOURCE=""
  repo="$(adk_template_repo)"; url="${repo%%#*}"; ref=""
  case "$repo" in *#*) ref="${repo#*#}" ;; esac
  name="$(basename "$url" .git)"
  if [ -z "$ref" ]; then
    ref="$(GIT_TERMINAL_PROMPT=0 git ls-remote --tags --refs "$url" 2>/dev/null | sed 's#.*refs/tags/##' \
      | grep -E -- '-v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -n 1 || true)"
  fi
  dir="$(mktemp -d "${TMPDIR:-/tmp}/cn-adk.XXXXXX")"
  if run_limited 60 env GIT_TERMINAL_PROMPT=0 git clone -q --depth 1 ${ref:+--branch "$ref"} "$url" "$dir/t"; then
    ADK_PIN="$(adk_req_pin "$dir/t/requirements.txt")"
  fi
  rm -rf "$dir"
  if [ -n "$ADK_PIN" ]; then ADK_PIN_SOURCE="$name ${ref:-default branch}"; return 0; fi
  ADK_PIN="$(adk_pypi_newest)"
  [ -n "$ADK_PIN" ] || return 1
  ADK_PIN_SOURCE="newest on PyPI; the pin of $name could not be read"
}

# adk_version [<adk>]: the version of the adk CLI (default: the one in PATH), or nothing.
adk_version() {
  local exe="${1:-adk}"
  [ -x "$exe" ] || have "$exe" || return 0
  "$exe" --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+)+[0-9A-Za-z.]*' | head -n 1 || true
}

adk_bin_dir() { uv tool dir --bin 2>/dev/null || true; }
on_path() { case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac; }

# adk_explain_gcloud: why gcloud is optional.
adk_explain_gcloud() {
  say "gcloud is optional: CodeNOW does not need it (models come through the CodeNOW agent gateway with your identity,"
  say "  deployment goes through CodeNOW); only Google Cloud services such as Vertex AI or adk deploy need it"
}

# adk_step [explicit]: cn-setup's step. Asks once "Do you build agents with Google ADK?" (CN_ADK); explicit
# (cn-setup --adk) means yes. Yes installs or upgrades adk to the template pin, then the PATH and gcloud offers.
adk_step() {
  local answer="" current log bindir found
  if [ "${1:-}" = explicit ]; then
    [ "${CN_ADK:-}" = yes ] || { CN_ADK=yes; save_setting CN_ADK yes; }
  elif [ -z "${CN_ADK:-}" ] && interactive; then
    if read -r -p "${CN_CMD:-cn}: Do you build agents with Google ADK? (yes installs the adk CLI: adk web, adk run, adk eval, the VS Code ADK extension) [y/N] " answer; then
      case "$answer" in y|Y|yes|Yes|YES) CN_ADK=yes ;; *) CN_ADK=no ;; esac
      save_setting CN_ADK "$CN_ADK"
    fi
  fi
  if [ "${CN_ADK:-}" != yes ]; then
    say "Google ADK tools: skipped${CN_ADK:+ (CN_ADK=$CN_ADK)}; later: cn-setup --adk"
    return 0
  fi
  if ! have uv; then
    note "Google ADK tools need uv (uv tool install): run cn-setup and answer yes to uv, or  $(install_hint uv)"
    return 0
  fi
  if ! adk_pin; then
    note "Google ADK tools: neither the google-adk pin of the ADK template nor PyPI could be read; run cn-setup --adk later"
    return 0
  fi
  case "$ADK_PIN_SOURCE" in "newest on PyPI"*) say "Google ADK tools: google-adk $ADK_PIN, the $ADK_PIN_SOURCE" ;; esac
  bindir="$(adk_bin_dir)"
  current="$(adk_version)"
  [ -n "$current" ] || [ -z "$bindir" ] || current="$(adk_version "$bindir/adk")"
  if [ "$current" = "$ADK_PIN" ]; then
    say "found adk $current (the pin of $ADK_PIN_SOURCE)"
  else
    if [ -n "$current" ]; then say "adk $current -> $ADK_PIN (the pin of $ADK_PIN_SOURCE)"
    else say "installing the adk CLI, google-adk $ADK_PIN (the pin of $ADK_PIN_SOURCE)"; fi
    say "  uv tool install --force --python $ADK_PYTHON google-adk==$ADK_PIN"
    log="$(mktemp "${TMPDIR:-/tmp}/cn-adk.XXXXXX")"
    if ( unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL CONDA_PROMPT_MODIFIER
         cn_uv_env || exit 1
         export UV_PYTHON_PREFERENCE="${UV_PYTHON_PREFERENCE:-only-managed}"
         uv tool install --force --python "$ADK_PYTHON" "google-adk==$ADK_PIN" ) >"$log" 2>&1; then
      say "adk $(adk_version "$bindir/adk") installed in $bindir"
    else
      tail -n 8 "$log" | cn_mask | sed "s/^/  /"
      note "uv could not install google-adk==$ADK_PIN"
    fi
    rm -f "$log"
  fi
  # PATH: uv's tool folder, so the terminal and VS Code find adk.
  if [ -n "$bindir" ] && ! on_path "$bindir"; then
    if ask_yes "$bindir (where uv puts adk) is not in PATH. Add it to your shell profile now (uv tool update-shell)?"; then
      if uv tool update-shell >/dev/null 2>&1; then say "PATH: added $bindir in your shell profile; open a new terminal and restart VS Code"
      else note "uv tool update-shell failed: add  export PATH=\"$bindir:\$PATH\"  to your shell profile"; fi
    else
      say "PATH: add $bindir with  uv tool update-shell  (or  export PATH=\"$bindir:\$PATH\"  in your shell profile), then open a new terminal"
    fi
  else
    found="$(command -v adk 2>/dev/null || true)"
    [ -z "$found" ] || [ -z "$bindir" ] || [ "$found" = "$bindir/adk" ] \
      || say "adk in PATH is $found, not uv's $bindir/adk: put $bindir first in PATH or remove the other one"
  fi
  # gcloud: an optional offer only.
  if have gcloud; then say "found gcloud (optional)"
  else
    adk_explain_gcloud
    if [ "$(uname -s)" = Darwin ] && have brew; then
      if ask_yes "Install the Google Cloud CLI anyway (optional) with  brew install --cask google-cloud-sdk  now?"; then
        brew install --cask google-cloud-sdk || say "brew did not install the Google Cloud CLI"
      else say "gcloud: not installed (later: brew install --cask google-cloud-sdk)"; fi
    else say "gcloud, if you need it: https://cloud.google.com/sdk/docs/install"; fi
  fi
}

# adk_report [explicit]: cn-doctor's lines; adk is recommended (a hint, never a problem), gcloud optional.
adk_report() {
  local current bindir pin_text
  if [ "${1:-}" != explicit ]; then
    case "${CN_ADK:-}" in
      yes) ;;
      no) return 0 ;;
      *) say "Google ADK tools: not set up (cn-setup asks once; cn-setup --adk)"; return 0 ;;
    esac
  fi
  have uv && bindir="$(adk_bin_dir)" || bindir=""
  current="$(adk_version)"
  if [ -z "$current" ]; then
    if [ -n "$bindir" ] && [ -x "$bindir/adk" ]; then
      say "adk is in $bindir, which is not in PATH: uv tool update-shell, then open a new terminal"
    else
      say "not found: adk (recommended for ADK agents: adk web, adk run, adk eval, the VS Code ADK extension): cn-setup --adk"
    fi
  elif ! adk_pin; then say "found adk $current (the pin of the ADK template cannot be read)"
  else
    case "$ADK_PIN_SOURCE" in "newest on PyPI"*) pin_text="google-adk $ADK_PIN is the $ADK_PIN_SOURCE" ;;
      *) pin_text="the pin of $ADK_PIN_SOURCE" ;; esac
    if [ "$current" = "$ADK_PIN" ]; then say "found adk $current ($pin_text)"
    else say "found adk $current; $pin_text is $ADK_PIN (recommended: cn-setup --adk)"; fi
  fi
  if have gcloud; then say "found gcloud (optional)"
  else say "not found: gcloud (optional: models come through the CodeNOW agent gateway, deployment through CodeNOW; only for Vertex AI or adk deploy)"; fi
}

# adk_repo_hint <repository root>: in an ADK agent repository (google-adk pinned in requirements.txt), where the
# VS Code ADK extension finds adk and which port is whose.
adk_repo_hint() {
  local root="${1:-}" pin
  [ -n "$root" ] || return 0
  pin="$(adk_req_pin "$root/requirements.txt")"
  [ -n "$pin" ] || return 0
  if [ -x "$root/.venv/bin/adk" ]; then say "ADK agent (google-adk $pin): adk is in .venv/bin"
  else say "ADK agent (google-adk $pin): no .venv/bin/adk yet: run cn-venv"; fi
  say "  VS Code ADK extension: select the interpreter .venv/bin/python (Python: Select Interpreter) so it finds adk"
  say "  port 8000 is adk web's default; the CodeNOW sandbox uses its own port (SANDBOX_PORT)"
}
