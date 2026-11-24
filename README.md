# CodeNOW agent devkit

Commands for developing AI agents on CodeNOW from your coding assistant (Claude Code, Codex, GitHub Copilot CLI).
The commands do what a script can do; the conversation (what the agent does, its name, its swarm) runs in the
assistant through the CodeNOW MCP server.

## Install

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/codenow-com/agent-devkit/HEAD/install.sh)"
```

To read the script first:

```bash
git clone https://github.com/codenow-com/agent-devkit.git
less agent-devkit/install.sh
./agent-devkit/install.sh
```

The installer clones the devkit into `~/.codenow/devkit` (the newest release tag), links the commands into
`~/.local/bin` and needs no `sudo`. macOS and Linux; on Windows use WSL.

## Commands

| Command | Does |
|---|---|
| `cn-setup` | Checks the tools, adds the CodeNOW MCP server of your tenant to Claude Code, Codex, Copilot CLI and VS Code Copilot Chat, installs the devkit skills into them and checks the kubeconfig. Asks once for the MCP URL and the kubeconfig path. Then offers the optional developer identity (below); `--skip-gateway` leaves it out, `--only-gateway` runs only it. |
| `cn-doctor` | Reports what is there and what is missing, the developer identity included (`cn-doctor --only-gateway`: only that). Changes nothing. |
| `cn-new-agent` | Starts your assistant with the `codenow-new-agent` skill: it asks what the agent does, creates its swarm and the agent from the newest template you pick (CodeNOW Agent SDK on LangChain, or Google ADK over A2A) and clones the repository. |
| `cn-sandbox` | Runs the local sandbox of the agent repository you are in: `up`, `run <pipeline>`, `logs`, `events`, `status` (with the agent's identity and the console URL), `down`, `hub` (all your sandboxes on one page). `cn-sandbox up --as-me` runs the agent as yourself (below); `cn-sandbox token [--watch]` writes your own access token. |
| `cn-update` | Updates the devkit to its newest release and refreshes the skills. |
| `cn-wait` | Waits for a CodeNOW build (`cn-wait build <swarm> <agent>`) or deployment (`cn-wait deploy <swarm> <environment>`) and prints each change. One run waits at most 50 s (`--max <s>` changes it), under the time limit that assistants put on a command. Needs the API key (below). Exit codes below. |
| `cn-call` | Calls one CodeNOW MCP tool and prints its JSON: `cn-call agent_swarms_list`. The arguments are one JSON object. Needs the API key (below). |
| `cn-<command> --help` | Every command has `--help` (or `-h`): its options, environment variables, files, exit codes and examples. It only prints. An unknown option exits with 2 (`cn-sandbox` passes it on to the agent's `sandbox.sh`). |

Exit codes of `cn-wait` and `cn-call`:

| Code | Means |
|---|---|
| 0 | Done: the build finished, the deployment is `HEALTHY`, the call worked. |
| 1 | The build or deployment failed. Also any status that `cn-wait` does not know as running: it prints the status. Known running statuses (`INITIALISING`, `BUILDING`, `SUCCESSFUL`, `FAILED`, `HEALTHY`, `UPDATING` and `FAILED_TO_UPDATE` are seen on a live tenant): builds `INITIALISING`, `INITIALIZING`, `QUEUED`, `PENDING`, `CREATED`, `SCHEDULED`, `WAITING`, `STARTED`, `STARTING`, `RUNNING`, `IN_PROGRESS`, `BUILDING` and `BUILD_` plus `STARTED`, `RUNNING`, `QUEUED` or `PENDING`; deployments `UPDATING`, `PENDING`, `QUEUED`, `CREATED`, `PROGRESSING`, `DEPLOYING`, `IN_PROGRESS`, `RUNNING`, `SYNCING`, `OUT_OF_SYNC`, `MISSING`, `STARTING`. No status yet counts as running. |
| 2 | Error: wrong arguments, no setup, the server cannot be reached, refuses the key, sends a redirect or an answer that is not JSON, or the tool answers with an error. One line on stderr, never the key. |
| 3 | Still running after `--max` seconds: run the same command again. |

## The flow

1. `cn-setup` once per computer.
2. `cn-new-agent` asks once where you work on the agent, in this terminal or in VS Code (stored as `CN_WORKSPACE` in
   `~/.codenow/config`; change it with `cn-setup --workspace terminal|vscode`), creates the agent and clones it.
3. The agent repository's `start` skill (`/start`) goes on. Terminal: in the same session; `code` is never run, only
   printed as a hint at the end. VS Code: the clone opens in a new VS Code window as the last action, and you type
   `/start` in its chat (Claude Code extension, or Copilot Chat in Interactive mode). When the developer identity is
   set up (`cn-setup --only-gateway`), `/start` runs the local sandbox with `cn-sandbox up --as-me`. It sets up
   your personal-dev environment, the CI triggers, the first release and the deployment with the agent's service
   account; for the CodeNOW Agent SDK also the local sandbox, for Google ADK a local run with the fake model and a
   check of the deployed agent's A2A card.
4. Develop on short-lived branches `feature/<name>/...`: the sandbox for seconds-long loops, a push for a preview in
   your personal-dev environment, a merge to `main` for a release to shared dev.

## Developer identity through the agent gateway

Your own Keycloak access token, kept fresh by [oidc-agent](https://github.com/indigo-dc/oidc-agent), works for the
agent gateway of your environment (models), the CodeNOW MCP server of your tenant and a local agent under your
identity (next section). No provider key, no service account. `cn-setup` sets it up as an optional step (it asks
first), `cn-setup --only-gateway` runs only this step, and running it again changes nothing that is already in place.

| Step | What it does |
|---|---|
| Values | The IAM issuer from your MCP server's metadata (`/.well-known/oauth-protected-resource`), the Keycloak client by the rule `<tenant>-<environment>-agent-gateway` (the tenant from the MCP URL, you name the environment), and the gateway URL you give (`https://agent-gateway.<environment>.<tenant>.<domain>`). Saved in `~/.codenow/config`: `CODENOW_IAM_ISSUER`, `CODENOW_AGW_CLIENT_ID`, `CODENOW_AGW_URL`, `CN_OIDC_ACCOUNT` (`cn-agw`). |
| oidc-agent | Needs 5.2.0 or newer. macOS: offers to run `brew tap indigo-dc/oidc-agent && brew install oidc-agent`. Linux: prints the packages of http://repo.data.kit.edu (Debian and Ubuntu ship an older one). Windows: run it in WSL. Never sudo. |
| Shell profile | Asks to add `eval "$(oidc-agent-service use)" > /dev/null` to `~/.<shell>rc`, so every shell finds the agent. |
| PKCE | Keycloak wants PKCE S256 for the device flow, and oidc-agent sends it there only from `custom_parameters.config` in its folder. Asks to write a pair for the account (entries of other accounts stay), then restarts the agent. |
| Account | When `oidc-add -l` does not list `cn-agw`: asks, then runs `oidc-gen` with the device flow. Open the URL it prints in any browser, confirm the code, and type a new local password for the account file (not your Keycloak password). Needs a terminal. |
| Check | `oidc-token --time=60 cn-agw`, its claims (audience = the gateway URL, client, your username), the gateway's `/v1/models` and an MCP `initialize` with the token. The token is never printed. |

After a reboot, load the account once: `oidc-add cn-agw`.

| Symptom | Fix |
|---|---|
| 401 from the gateway | The token lacks the gateway's audience or has old claims: `oidc-token --force-new cn-agw`. |
| 403 on a model | None of your teams (`cn_teams`) may use it. |
| 403 from the MCP server | You are not a member of the tenant (`cn_accounts`). |
| `oidc-token` cannot reach the agent, or the account is not loaded | Open a new terminal (it starts the agent), then `oidc-add cn-agw`. |
| `oidc-token` fails with `invalid_grant` | The Keycloak session expired: `oidc-gen cn-agw --reauthenticate`. |
| `oidc-gen`: `Missing parameter: code_challenge_method` | No PKCE pair for the account: `cn-setup --only-gateway`, then `oidc-gen` again. |
| `oidc-gen`: `unauthorized_client` | The Keycloak client does not have the Device Authorization Grant on. |
| TLS or certificate error | Put the local CA into the system trust store (oidc-agent). |

## Run your local agent as yourself

A local agent can run as you, with your own Keycloak access token, instead of a deployed agent's token. The agent then
calls the AI gateway and Workforce as you; Workforce shows it as `--under-development-- <agent>`, owned by you, under
your person in the org chart. Your person must be in the organisation, else Workforce refuses the agent.

1. Once per computer: `cn-setup --only-gateway` (above). It creates the oidc-agent account `cn-agw` against the
   public Keycloak client `<tenant>-<environment>-agent-gateway` (on the demo tenant
   `demo-tenant-demo-environment-agent-gateway`) and stores the Workforce (observer) URL for local agents,
   `CODENOW_WORKFORCE_URL`. It finds the observer through the CodeNOW MCP server (agents made from the
   `ai-swarm-observer` template whose URL answers): one is offered as the default, several are listed to pick from,
   none is asked once (Enter skips). On the demo tenant the expected value is
   `https://observer-nov18-observer-test.demo-environment.demo-tenant.codenow-test.com`. After a reboot, load the
   account with `oidc-add cn-agw`.
2. In the agent repository: `cn-sandbox up --as-me`. It checks that `requirements.txt` pins
   `codenow-agent-sdk` 2.24.0 or newer (an older pin: it asks to raise that one line to the newest version of your pip
   index; commit the change), writes this block into the agent's `.env` and starts the sandbox as in step 3:

   ```bash
   # >>> cn-devkit: developer identity (cn-sandbox as-me off removes it)
   CN_IDENTITY_PROVIDER=developer
   CN_IDENTITY_DEVELOPER_CLIENTS=demo-tenant-demo-environment-agent-gateway
   WORKFORCE_URL=https://observer-nov18-observer-test.demo-environment.demo-tenant.codenow-test.com
   WORKFORCE_MODE=shadow
   # <<< cn-devkit
   ```

   Other lines of `.env` stay. A second run refreshes the block. An empty line of one of these keys outside the block
   (`WORKFORCE_URL=`, as in a template's `.env`) is removed, and the output names it. When one of these keys is set
   outside the block with another value, it stops and names the line to remove. Without a Workforce URL the two `WORKFORCE_*` lines are left
   out and the agent does not appear in Workforce. Leave `AI_GATEWAY_REFRESH_TOKEN` empty: the agent refuses to start
   as you next to a deployed agent's token.
3. `cn-sandbox up` (also the second half of `up --as-me`) writes the token (`oidc-token --time=120 cn-agw`) to the
   token file and starts `cn-sandbox token --watch` in the background, which writes a fresh one every 45 s (pid and log
   in the token's folder). `cn-sandbox down` stops it when no other sandbox uses it. Without the sandbox:
   `cn-sandbox token` once, or `cn-sandbox token --watch` in a terminal of its own; `cn-sandbox token --stop` stops a
   background refresh.

`cn-sandbox as-me status` shows the block and the stored values; `cn-sandbox as-me off` removes the block and stops
the token refresh when no other sandbox uses it. You can also write the four lines into `.env` by hand; `cn-sandbox up`
then works the same. While the block is in `.env`, a plain `cn-sandbox up` also runs the agent as you.

### Several agents at once

You can run the sandboxes of several agent repositories at the same time: each one is its own compose project, and
its port is picked automatically. They share one token refresh. `cn-sandbox up` starts it once and lists the agent
repository next to the token (`~/.codenow/sandbox-token/users/`); `cn-sandbox down` (or `as-me off`) stops it only
in the last running sandbox. An entry whose sandbox has no running container (and that is older than
`CN_SANDBOX_TOKEN_GRACE` seconds) is dropped. `cn-sandbox status` prints
`token refresh: running for N sandbox(es)`; `cn-sandbox token --stop` stops the refresh for all of them.

`cn-sandbox status` first says under which identity the running agent runs (from the agent's log), then shows the
status of the agent's `sandbox.sh`:

```text
cn-sandbox: identity: developer (demo-tenant, client demo-tenant-demo-environment-agent-gateway)
cn-sandbox: Workforce: onboarding approved (instance dev-..., mode shadow)
cn-sandbox: console: http://localhost:8080/ (log in on localhost, not on 127.0.0.1)
```

The other cases are `identity: deployment token (legacy-refresh-token); run cn-sandbox up --as-me to run as yourself`
and `identity: unknown (agent not running)`.

Open the console on `http://localhost:<port>/`, as `cn-sandbox up` and `status` print it. The login returns to
`localhost`, and its state cookie belongs to one host name.

| Symptom | Fix |
|---|---|
| Console: `Login expired or invalid` | You started the login on `127.0.0.1`. Use `localhost` and start again at `http://localhost:<port>/auth/login`. |
| `up --as-me` stops on a line of `.env` | That line sets a key of the block to another value: remove it, then run again. |

| Setting | Default | Meaning |
|---|---|---|
| `CN_OIDC_ACCOUNT` | `cn-agw` | the oidc-agent account the token comes from |
| `CN_IDENTITY_TOKEN_FILE` | `~/.codenow/sandbox-token/token` | the token file (mode 600, its folder 700); never in a repository or directly in your home folder |
| `CN_SANDBOX_TOKEN_INTERVAL` | `45` | seconds between two refreshes of `--watch` |
| `CN_SANDBOX_TOKEN_GRACE` | `300` | seconds a sandbox counts as using the refresh after its `up`, even without a running container |

The token is a secret: it is never printed, and the sandbox mounts only its own copy of it.

## All your sandboxes on one page

`cn-sandbox hub` starts a small local page on `http://localhost:8079/` (bound to 127.0.0.1 only) and prints its URL;
`cn-sandbox up` starts it too when it is not running and prints `sandboxes: http://localhost:8079/` under the console
line. The page lists every agent sandbox on this computer (the Docker compose projects named `sandbox-*`) and refreshes
every 5 s. Per sandbox it shows:

- the agent's name, its repository folder and whether the sandbox runs (a stopped one is grey, with the
  `cn-sandbox up` hint);
- the identity: `as you (developer)` or `deployment token`, and the agent's last Workforce onboarding line;
- the link to the agent's console (`http://localhost:<port>/`, in a new tab);
- a diagram of how this sandbox is connected: browser, edge, agent, runstore and valkey on the inner network (no
  internet), and egress to each allowlisted host on the outer network, plus the token the agent uses.

The hub only reads: Docker (`docker ps`, `docker inspect`, the agent's log), `sandbox/.run/allow` and
`sandbox/.run/port` of the repository, and four non-secret keys of `.env` (`CN_IDENTITY_PROVIDER`,
`CN_IDENTITY_DEVELOPER_CLIENTS`, `WORKFORCE_URL`, `WORKFORCE_MODE`). It masks anything that looks like a token.

| Command | Does |
|---|---|
| `cn-sandbox hub` | Starts the hub in the background (once) and prints its URL. |
| `cn-sandbox hub --status` | Says whether it runs. |
| `cn-sandbox hub --stop` | Stops it. |

| Setting | Default | Meaning |
|---|---|---|
| `CN_SANDBOX_HUB_PORT` | `8079` | the hub's port; when another program has it, the hub says so: choose another |
| `CN_SANDBOX_HUB` | `on` | `off`: `cn-sandbox up` does not start the hub |

The pid and log are in `~/.codenow/sandbox-hub/`.

## Settings and secrets

`~/.codenow/config` keeps the MCP URL and the kubeconfig path (mode 600), never a token. `CODENOW_API_KEY=<key> cn-setup`
also saves the key in `~/.codenow/credentials` (mode 600) for `cn-wait` and `cn-call`; they read `CODENOW_API_KEY`
first when it is set. `cn-setup` first checks a new key against the server; a key that does not work does not replace
the stored one. `cn-setup --forget-key` removes the stored key. The MCP URL must use `https://` (`http://` only for
`localhost`), and `cn-call` and `cn-wait` do not follow redirects, so the key goes to that server only.

- Claude Code logs in to CodeNOW with OAuth on first use.
- Codex and Copilot CLI cannot use the CodeNOW login, so they send a CodeNOW API key (CodeNOW UI: your profile → API
  keys) in the `X-Codenow-Api-Key` header.
  - Codex reads it from the `CODENOW_API_KEY` environment variable when it starts; `~/.codex/config.toml` keeps no
    key. Export the variable in your shell, for example from the macOS keychain:
    `export CODENOW_API_KEY="$(security find-generic-password -s codenow-api-key -w)"`.
  - Copilot CLI keeps the key in `~/.copilot/mcp-config.json`: run `CODENOW_API_KEY=<key> cn-setup` once. Copilot CLI
    takes the header only on its command line (`copilot mcp add --header`), so while `cn-setup` adds the server, other
    users of the computer can see the key in the process list for a moment.
- VS Code Copilot Chat: `cn-setup` adds the server to the user-level `mcp.json` of VS Code (and VS Code Insiders). The
  file keeps no key: on the first start of the server (Command Palette: MCP: List Servers, the server, Start Server)
  VS Code asks for the API key and keeps it in its own secret storage. Other servers in the file stay; a file with
  comments is not changed, and `cn-setup` prints the lines to add by hand.
  - Use the chat in the Interactive mode, not Autopilot: in Autopilot the assistant cannot ask you to confirm a change
    in CodeNOW, so it stops at the first one.
  - `cn-new-agent` cannot start the chat in VS Code. Open the folder in VS Code and write in the chat: "Use the
    codenow-new-agent skill to create a new CodeNOW agent and clone it into this folder."

## Uninstall

```bash
rm -f ~/.local/bin/cn-*; rm -rf ~/.codenow
rm -rf ~/.claude/skills/codenow-new-agent ~/.codex/skills/codenow-new-agent ~/.copilot/skills/codenow-new-agent
```

Remove the `codenow` MCP server with `claude mcp remove codenow`, `codex mcp remove codenow` and
`copilot mcp remove codenow`.

## License

Apache License 2.0, see [LICENSE](LICENSE).
