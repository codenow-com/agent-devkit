# The --help texts and the usage errors of the cn-* commands. Sourced, not run.
#
# Each command sources this file first, before it reads ~/.codenow/config or does any other work, and calls
# cn_help_first or cn_help_any. They only print and exit; they never touch a file, the network or a container.

# cn_usage_line <command>: the one-line synopsis that a usage error prints.
cn_usage_line() {
  case "$1" in
    cn-call) echo "usage: cn-call <tool> [<json object of arguments>]" ;;
    cn-doctor) echo "usage: cn-doctor [--skip-gateway | --only-gateway]" ;;
    cn-new-agent) echo "usage: cn-new-agent [--with claude|codex|copilot] [--here]" ;;
    cn-sandbox) echo "usage: cn-sandbox up [--as-me]|down|run|logs|events|status|token|as-me|hub [args]" ;;
    cn-setup) echo "usage: cn-setup [--check] [--forget-key] [--skip-gateway | --only-gateway] [--workspace terminal|vscode]" ;;
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
    CODENOW_WORKFORCE_URL, CN_OIDC_ACCOUNT, OIDC_CONFIG_DIR, CODENOW_HOME
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
    cn-new-agent [--with claude|codex|copilot] [--here]
    cn-new-agent -h | --help

DESCRIPTION
    Starts your coding assistant in the current folder with the
    codenow-new-agent skill. The assistant asks what the agent does, its
    swarm and name, creates it from the template you pick through the
    CodeNOW MCP server and clones its repository here. Without --with it
    uses the first assistant found: claude, codex, copilot.
    First it settles where you work on the agent, stored as CN_WORKSPACE
    (cn-setup --workspace terminal|vscode); the skill asks once when it is
    not set.
    terminal: every step and /start go on in this session; `code' is
        never run.
    vscode: the whole flow moves to VS Code at once. With CN_WORKSPACE=
        vscode this command starts no assistant: it runs `code .' and
        tells you to type /codenow-new-agent in the chat of the window
        that opened. Without the `code' command it prints how to install
        it and exits 1.
    Inside VS Code (TERM_PROGRAM=vscode, VSCODE_PID or
    VSCODE_IPC_HOOK_CLI set) nothing is asked and the flow stays there.

OPTIONS
    --with <assistant>
        Use this assistant: claude, codex or copilot.
    --here
        Work in this terminal this once, also when CN_WORKSPACE=vscode.
    -h, --help
        Print this help and exit.

ENVIRONMENT
    PATH   where the assistants (claude, codex, copilot) and code are
           found
    TERM_PROGRAM, VSCODE_PID, VSCODE_IPC_HOOK_CLI
           set: you are inside VS Code

FILES
    ~/.claude/skills, ~/.codex/skills, ~/.copilot/skills
        The codenow-new-agent skill (installed by cn-setup).
    ~/.codenow/config
        CN_WORKSPACE (terminal or vscode), CODENOW_AGW_CLIENT_ID and
        CODENOW_WORKFORCE_URL (the developer identity for /start).

EXIT STATUS
    The exit status of the assistant, which replaces this command.
    0    CN_WORKSPACE=vscode: VS Code opened
    1    no assistant found, the one named is not installed, or
         CN_WORKSPACE=vscode and the `code' command is missing
    2    wrong arguments

EXAMPLES
    cn-new-agent
    cn-new-agent --with codex
    cn-new-agent --here

SEE ALSO
    cn-setup(1), cn-sandbox(1), cn-wait(1)
EOF
    ;;
    cn-sandbox) cat <<'EOF'
NAME
    cn-sandbox - run the local sandbox of the agent repository you are in

SYNOPSIS
    cn-sandbox up [--as-me] | down | logs | events | status
    cn-sandbox as-me off | status
    cn-sandbox run <pipeline> [subject] [json]
    cn-sandbox token [--watch | --stop]
    cn-sandbox hub [--stop | --status]
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
    up       Start the sandbox. In developer mode (CN_IDENTITY_PROVIDER=
             developer, e.g. the block of `up --as-me' in .env) it first
             writes your token and starts `token --watch' in the
             background, unless it already runs for another sandbox: one
             refresh serves every sandbox of yours. Then it prints the
             console URL on localhost: the login returns to localhost, so a
             login started on 127.0.0.1 fails. It also starts the sandbox
             hub when it is not running and prints its URL
             (sandboxes: http://localhost:8079/).
    up --as-me
             Run the agent as yourself: check that requirements.txt pins
             codenow-agent-sdk 2.24.0 or newer (an older pin: ask to raise
             that line), write the developer identity block into the
             agent's .env (client and Workforce URL from cn-setup
             --only-gateway, WORKFORCE_MODE=shadow), then `up'. Other
             lines of .env stay. An empty KEY= line of a key of the block
             outside it is removed (each removed line is named); a
             non-empty other value stops it.
    status   Print the identity the running agent uses (from its log):
             developer (tenant, client), deployment token, or unknown
             (agent not running); its last Workforce onboarding line; and
             the console URL; in developer mode also `token refresh:
             running for N sandbox(es)' or `not running'. Then the status
             of the agent's sandbox.sh. Never prints a token.
    as-me off
             Remove the block from .env and stop the token refresh when
             no other sandbox uses it.
    as-me status
             Show the block and the values stored by cn-setup.
    down     Stop the sandbox, and the background token refresh when no
             other sandbox uses it.
    token    Write your own access token (oidc-agent) to the token file,
             once. Any other `token ...' (e.g. `token person <name>') goes
             to the agent's sandbox.sh.
    token --watch
             The same every CN_SANDBOX_TOKEN_INTERVAL seconds until
             stopped.
    token --stop
             Stop the background refresh that `up' started, for every
             sandbox, and empty its list of sandboxes.
    hub      Start the sandbox hub in the background (once) and print its
             URL: one page on http://localhost:8079/ (127.0.0.1 only) with
             every agent sandbox on this computer, its state, identity,
             Workforce onboarding, egress allowlist and a diagram of how it
             is connected, with the link to each agent's console. It
             reads Docker, changes nothing and never shows a token. Works
             in any folder.
    hub --stop
             Stop the hub.
    hub --status
             Print whether the hub runs (exit 0) or not (exit 1).
    -h, --help
             Print this help and exit (only as the first argument).

ENVIRONMENT
    CN_IDENTITY_PROVIDER       developer: run the agent under your own
                               identity (also read from the agent's .env)
    CN_OIDC_ACCOUNT            the oidc-agent account (default cn-agw)
    CN_IDENTITY_TOKEN_FILE     the token file, also read from the agent's
                               .env (default ~/.codenow/sandbox-token/token)
    CN_SANDBOX_TOKEN_INTERVAL  seconds between refreshes (default 45)
    CN_SANDBOX_TOKEN_GRACE     seconds after `up' before a sandbox without a
                               running container leaves the list (300)
    CN_SANDBOX_HUB_PORT        the hub's port on 127.0.0.1 (default 8079)
    CN_SANDBOX_HUB             off: `up' does not start the hub
    CODENOW_HOME               the settings folder (default ~/.codenow)

FILES
    sandbox/sandbox.sh, .env, requirements.txt
                               in the agent repository
    ~/.codenow/config          CODENOW_AGW_CLIENT_ID and
                               CODENOW_WORKFORCE_URL (cn-setup)
    ~/.codenow/sandbox-token/token
        The token (mode 600, folder 700); never inside a repository.
    ~/.codenow/sandbox-token/watch.pid, watch.log
        The pid and log of the background refresh.
    ~/.codenow/sandbox-token/users/
        One file per agent repository that uses the refresh; an entry
        whose sandbox has no running container is removed.
    ~/.codenow/sandbox-hub/hub.pid, hub.log
        The pid and log of the sandbox hub.

SEVERAL AGENTS AT ONCE
    Each agent repository runs its own sandbox (its own compose project;
    the port is picked automatically). All of them share one token
    refresh: `up' starts it once, `down' stops it only in the last
    running sandbox.

EXIT STATUS
    The exit status of sandbox.sh for the commands it runs.
    0    token written, or refresh stopped
    1    not in a git repository, no sandbox/sandbox.sh, or no token;
         up --as-me: no client, an old SDK pin, or a line in .env that
         conflicts with the block; hub: it did not start (port taken);
         hub --status: not running
    2    wrong arguments (as-me without off or status, hub with another
         option)
    token --watch runs until it is stopped.

EXAMPLES
    cn-sandbox up
    cn-sandbox up --as-me
    cn-sandbox status
    cn-sandbox as-me off
    cn-sandbox run <pipeline>
    cn-sandbox token --watch
    cn-sandbox hub
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
    cn-setup --workspace terminal | vscode
    cn-setup -h | --help

DESCRIPTION
    Checks the tools, adds the CodeNOW MCP server of your tenant to Claude
    Code, Codex, Copilot CLI and VS Code Copilot Chat, installs the devkit
    skills into them and checks the kubeconfig and the CodeNOW Agent SDK
    index of pip. Asks once for the MCP URL and the kubeconfig path, then
    offers the optional developer identity (agent gateway, oidc-agent)
    and the Workforce (observer) URL for local agents.
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
    --workspace terminal | vscode
        Save CN_WORKSPACE in ~/.codenow/config, then exit: where
        cn-new-agent runs (terminal: in the same session; vscode: it
        opens VS Code at once and the flow goes on in its chat). The
        codenow-new-agent skill asks once and runs this.
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
    CODENOW_WORKFORCE_URL  the Workforce (observer) URL for local agents
                           (cn-sandbox up --as-me); optional. Found
                           through the CodeNOW MCP server, else asked
                           once (Enter skips)
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
    cn-setup --workspace vscode

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
