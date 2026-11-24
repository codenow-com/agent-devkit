# The --help texts and the usage errors of the cn-* commands. Sourced, not run.
#
# Each command sources this file first, before it reads ~/.codenow/config or does any other work, and calls
# cn_help_first or cn_help_any. They only print and exit; they never touch a file, the network or a container.

# cn_usage_line <command>: the one-line synopsis that a usage error prints.
cn_usage_line() {
  case "$1" in
    cn-call) echo "usage: cn-call <tool> [<json object of arguments>]" ;;
    cn-doctor) echo "usage: cn-doctor [--skip-gateway | --only-gateway]" ;;
    cn-new-agent) echo "usage: cn-new-agent [--with claude|codex|copilot]" ;;
    cn-sandbox) echo "usage: cn-sandbox up|run|logs|events|status|down|token [args]" ;;
    cn-setup) echo "usage: cn-setup [--check] [--forget-key] [--skip-gateway | --only-gateway]" ;;
    cn-update) echo "usage: cn-update" ;;
    cn-wait) echo "usage: cn-wait build|deploy <swarm> <agent|environment> [build id] [--max <s>]" ;;
  esac
}

# cn_usage_error <command> <message>: the message, the usage line and a hint on stderr; exit 2.
cn_usage_error() {
  {
    echo "$1: $2"
    cn_usage_line "$1"
    echo "Try '$1 --help'."
  } >&2
  exit 2
}

# cn_help_first <command> [args]: the help when the first argument is -h or --help (commands that pass their
# arguments on, where a later -h belongs to someone else).
cn_help_first() {
  local cmd="$1"; shift
  case "${1:-}" in -h|--help) cn_help "$cmd"; exit 0 ;; esac
}

# cn_help_any <command> [args]: the help when any argument is -h or --help.
cn_help_any() {
  local cmd="$1" arg; shift
  for arg in "$@"; do
    case "$arg" in -h|--help) cn_help "$cmd"; exit 0 ;; esac
  done
}

cn_help() {
  case "$1" in
    cn-call) cat <<'EOF'
NAME
    cn-call - call one CodeNOW MCP tool and print its JSON

SYNOPSIS
    cn-call <tool> [<json object of arguments>]
    cn-call -h | --help

DESCRIPTION
    Calls one tool of the CodeNOW MCP server of your tenant and prints the
    result as JSON on stdout, for scripts and coding assistants. The
    arguments are one JSON object. It needs the API key that cn-setup
    saves; the URL must be https:// (http:// only for localhost), and
    redirects are not followed, so the key goes to that server only.

OPTIONS
    -h, --help
        Print this help and exit.

ENVIRONMENT
    CODENOW_MCP_URL   the MCP server URL; default: from ~/.codenow/config
    CODENOW_API_KEY   the API key; default: from ~/.codenow/credentials
    CODENOW_HOME      the settings folder (default ~/.codenow)

FILES
    ~/.codenow/config        CODENOW_MCP_URL (written by cn-setup)
    ~/.codenow/credentials   the API key (mode 600, written by cn-setup)

EXIT STATUS
    0    the call worked
    2    error: wrong arguments, no setup, the server cannot be reached,
         refuses the key or answers with an error (one line on stderr,
         never the key)
    130  interrupted

EXAMPLES
    cn-call agent_swarms_list
    cn-call agent_swarm_deployment_detail \
        '{"agentSwarmId": "<swarm>", "environmentId": "<env>"}'

SEE ALSO
    cn-wait(1), cn-setup(1), cn-doctor(1)
EOF
    ;;
    cn-doctor) cat <<'EOF'
NAME
    cn-doctor - report what this computer lacks for CodeNOW agents

SYNOPSIS
    cn-doctor [--skip-gateway | --only-gateway]
    cn-doctor -h | --help

DESCRIPTION
    Reports the tools (git, curl, python3, Docker with Compose, kubectl,
    pinniped, openspec, the coding assistants), the devkit version, the
    CodeNOW MCP server in each assistant, the devkit skills, the API key,
    the kubeconfig, the CodeNOW Agent SDK index of pip and the optional
    developer identity (agent gateway). It changes nothing. It is the
    same as cn-setup --check.

OPTIONS
    --skip-gateway
        Leave out the report on the developer identity (agent gateway).
    --only-gateway
        Report only on the developer identity (agent gateway).
    -h, --help
        Print this help and exit.

ENVIRONMENT
    CODENOW_MCP_URL, KUBECONFIG_FILE, CODENOW_API_KEY, CODENOW_MCP_NAME,
    CODENOW_AGW_URL, CODENOW_IAM_ISSUER, CODENOW_AGW_CLIENT_ID,
    CN_OIDC_ACCOUNT, OIDC_CONFIG_DIR, CODENOW_HOME
        As for cn-setup(1).

FILES
    ~/.codenow/config        the settings (cn-setup writes them)
    ~/.codenow/credentials   the API key of cn-call and cn-wait
    ~/.codenow/devkit        the devkit; its version is compared with the
                             newest release

EXIT STATUS
    0    all good
    1    one or more problems (each printed, with the fix)
    2    wrong arguments

EXAMPLES
    cn-doctor
    cn-doctor --only-gateway

SEE ALSO
    cn-setup(1), cn-update(1)
EOF
    ;;
    cn-new-agent) cat <<'EOF'
NAME
    cn-new-agent - create a CodeNOW agent with your coding assistant

SYNOPSIS
    cn-new-agent [--with claude|codex|copilot]
    cn-new-agent -h | --help

DESCRIPTION
    Starts your coding assistant in the current folder with the
    codenow-new-agent skill. The assistant asks what the agent does, its
    swarm and name, creates it from the template you pick through the
    CodeNOW MCP server and clones its repository here. Without --with it
    uses the first assistant found: claude, codex, copilot.

OPTIONS
    --with <assistant>
        Use this assistant: claude, codex or copilot.
    -h, --help
        Print this help and exit.

ENVIRONMENT
    PATH   where the assistants (claude, codex, copilot) are found

FILES
    ~/.claude/skills, ~/.codex/skills, ~/.copilot/skills
        The codenow-new-agent skill (installed by cn-setup).

EXIT STATUS
    The exit status of the assistant, which replaces this command.
    1    no assistant found, or the one named is not installed
    2    wrong arguments

EXAMPLES
    cn-new-agent
    cn-new-agent --with codex

SEE ALSO
    cn-setup(1), cn-sandbox(1), cn-wait(1)
EOF
    ;;
    cn-sandbox) cat <<'EOF'
NAME
    cn-sandbox - run the local sandbox of the agent repository you are in

SYNOPSIS
    cn-sandbox up | down | logs | events | status
    cn-sandbox run <pipeline> [subject] [json]
    cn-sandbox token [--watch | --stop]
    cn-sandbox <other sandbox.sh command> [args]
    cn-sandbox -h | --help

DESCRIPTION
    Runs sandbox/sandbox.sh of the agent repository you are in, so the
    sandbox always matches the agent's template version (1.1.0 or newer).
    The devkit handles `token' and, with CN_IDENTITY_PROVIDER=developer,
    adds your own access token to `up' and `down'. Every other command and
    argument goes to the agent repository's sandbox.sh unchanged; see
    `bash sandbox/sandbox.sh help' there.

OPTIONS
    up       Start the sandbox. In developer mode it first writes your
             token and starts `token --watch' in the background.
    down     Stop the sandbox, and the background token refresh.
    token    Write your own access token (oidc-agent) to the token file,
             once. Any other `token ...' (e.g. `token person <name>') goes
             to the agent's sandbox.sh.
    token --watch
             The same every CN_SANDBOX_TOKEN_INTERVAL seconds until
             stopped.
    token --stop
             Stop the background refresh that `up' started.
    -h, --help
             Print this help and exit (only as the first argument).

ENVIRONMENT
    CN_IDENTITY_PROVIDER       developer: run the agent under your own
                               identity (also read from the agent's .env)
    CN_OIDC_ACCOUNT            the oidc-agent account (default cn-agw)
    CN_IDENTITY_TOKEN_FILE     the token file, also read from the agent's
                               .env (default ~/.codenow/sandbox-token/token)
    CN_SANDBOX_TOKEN_INTERVAL  seconds between refreshes (default 45)
    CODENOW_HOME               the settings folder (default ~/.codenow)

FILES
    sandbox/sandbox.sh, .env   in the agent repository
    ~/.codenow/sandbox-token/token
        The token (mode 600, folder 700); never inside a repository.
    ~/.codenow/sandbox-token/watch.pid, watch.log
        The pid and log of the background refresh.

EXIT STATUS
    The exit status of sandbox.sh for the commands it runs.
    0    token written, or refresh stopped
    1    not in a git repository, no sandbox/sandbox.sh, or no token
    token --watch runs until it is stopped.

EXAMPLES
    cn-sandbox up
    cn-sandbox run <pipeline>
    cn-sandbox token --watch
    cn-sandbox down

SEE ALSO
    cn-setup(1), cn-doctor(1), cn-new-agent(1)
EOF
    ;;
    cn-setup) cat <<'EOF'
NAME
    cn-setup - prepare this computer for developing CodeNOW agents

SYNOPSIS
    cn-setup [--skip-gateway | --only-gateway]
    cn-setup --check [--skip-gateway | --only-gateway]
    cn-setup --forget-key
    cn-setup -h | --help

DESCRIPTION
    Checks the tools, adds the CodeNOW MCP server of your tenant to Claude
    Code, Codex, Copilot CLI and VS Code Copilot Chat, installs the devkit
    skills into them and checks the kubeconfig and the CodeNOW Agent SDK
    index of pip. Asks once for the MCP URL and the kubeconfig path, then
    offers the optional developer identity (agent gateway, oidc-agent).
    It never stores a token in ~/.codenow/config.

OPTIONS
    --check
        Only report, change nothing (the same as cn-doctor).
    --forget-key
        Remove the API key that cn-call and cn-wait use, then exit.
    --skip-gateway
        Leave out the optional step "Developer identity (agent gateway)".
    --only-gateway
        Run only that step (with --check: only its report).
    -h, --help
        Print this help and exit.

ENVIRONMENT
    CODENOW_MCP_URL        the MCP URL of your tenant
                           (https://mcp-server-<tenant>.<domain>/mcp)
    KUBECONFIG_FILE        the kubeconfig from the CodeNOW UI
    CODENOW_MCP_NAME       the MCP server name in the assistants
                           (default codenow)
    CODENOW_API_KEY        an API key to check and save for cn-call,
                           cn-wait, Codex and Copilot CLI
    CODENOW_AGW_URL, CODENOW_IAM_ISSUER, CODENOW_AGW_CLIENT_ID
                           the agent gateway values of the identity step
    CN_OIDC_ACCOUNT        the oidc-agent account (default cn-agw)
    OIDC_CONFIG_DIR        the oidc-agent folder
    CODENOW_HOME           the settings folder (default ~/.codenow)

FILES
    ~/.codenow/config        the settings (mode 600), never a token
    ~/.codenow/credentials   the API key (mode 600)
    ~/.codenow/devkit        the devkit
    ~/.claude.json, ~/.codex/config.toml, ~/.copilot/mcp-config.json
                             the MCP server of each assistant
    ~/.claude/skills, ~/.codex/skills, ~/.copilot/skills
                             the devkit skills

EXIT STATUS
    0    done (with --check: all good)
    1    a required tool is missing or a step failed (with --check or
         --only-gateway: one or more problems)
    2    wrong arguments

EXAMPLES
    cn-setup
    CODENOW_API_KEY=<key> cn-setup
    cn-setup --only-gateway
    cn-setup --forget-key

SEE ALSO
    cn-doctor(1), cn-update(1), cn-new-agent(1), cn-call(1)
EOF
    ;;
    cn-update) cat <<'EOF'
NAME
    cn-update - update the devkit to its newest release

SYNOPSIS
    cn-update
    cn-update -h | --help

DESCRIPTION
    Fetches the newest release tag of the devkit into ~/.codenow/devkit,
    links the cn-* commands into ~/.local/bin again and runs cn-setup
    (without questions) to refresh the skills in the assistants. Local
    changes in the devkit folder are kept only until the next release.

OPTIONS
    -h, --help
        Print this help and exit.

ENVIRONMENT
    CODENOW_HOME      the settings folder (default ~/.codenow)
    CODENOW_BIN_DIR   where the commands are linked (default ~/.local/bin)

FILES
    ~/.codenow/devkit   the devkit (a git clone)
    ~/.local/bin/cn-*   the links to the commands
    ~/.codenow/config   the settings that cn-setup reads

EXIT STATUS
    0    updated
    >0   the fetch, the install or cn-setup failed
    2    wrong arguments

EXAMPLES
    cn-update
    cn-update && cn-doctor

SEE ALSO
    cn-setup(1), cn-doctor(1)
EOF
    ;;
    cn-wait) cat <<'EOF'
NAME
    cn-wait - wait for a CodeNOW build or deployment

SYNOPSIS
    cn-wait build <swarm> <agent> [build id] [--max <seconds>]
    cn-wait deploy <swarm> <environment> [--max <seconds>]
    cn-wait -h | --help

DESCRIPTION
    Waits for a build of an agent (the newest one, or the build id given)
    or for the deployment of a swarm in an environment, and prints each
    change of its status. One run waits at most 50 s, under the time limit
    that assistants put on one command; exit status 3 means: run it again.
    It needs the API key that cn-setup saves.

OPTIONS
    --max <seconds>
        Wait at most this long (1 to 3600, default 50).
    -h, --help
        Print this help and exit.

ENVIRONMENT
    CODENOW_MCP_URL   the MCP server URL; default: from ~/.codenow/config
    CODENOW_API_KEY   the API key; default: from ~/.codenow/credentials
    CODENOW_HOME      the settings folder (default ~/.codenow)

FILES
    ~/.codenow/config        CODENOW_MCP_URL (written by cn-setup)
    ~/.codenow/credentials   the API key (mode 600, written by cn-setup)

EXIT STATUS
    0    done: the build finished, the deployment is HEALTHY
    1    failed, or a status that is not known as running
    2    error: wrong arguments, no setup, network or server
    3    still running after --max seconds: run it again
    130  interrupted

EXAMPLES
    cn-wait build <swarm> <agent>
    cn-wait build <swarm> <agent> <build id> --max 300
    cn-wait deploy <swarm> <environment>

SEE ALSO
    cn-call(1), cn-setup(1)
EOF
    ;;
  esac
}
