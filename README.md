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
| `cn-setup` | Checks the tools, adds the CodeNOW MCP server of your tenant to Claude Code, Codex, Copilot CLI and VS Code Copilot Chat, installs the devkit skills into them and checks the kubeconfig. Asks once for the MCP URL and the kubeconfig path. |
| `cn-doctor` | Reports what is there and what is missing. Changes nothing. |
| `cn-new-agent` | Starts your assistant with the `codenow-new-agent` skill: it asks what the agent does, creates its swarm and the agent from the newest template you pick (CodeNOW Agent SDK on LangChain, or Google ADK over A2A) and clones the repository. |
| `cn-sandbox` | Runs the local sandbox of the agent repository you are in: `up`, `run <pipeline>`, `logs`, `events`, `status`, `down`. `cn-sandbox token [--watch]` writes your own access token for a local agent under your identity (below). |
| `cn-update` | Updates the devkit to its newest release and refreshes the skills. |
| `cn-wait` | Waits for a CodeNOW build (`cn-wait build <swarm> <agent>`) or deployment (`cn-wait deploy <swarm> <environment>`) and prints each change. One run waits at most 50 s (`--max <s>` changes it), under the time limit that assistants put on a command. Needs the API key (below). Exit codes below. |
| `cn-call` | Calls one CodeNOW MCP tool and prints its JSON: `cn-call agent_swarms_list`. The arguments are one JSON object. Needs the API key (below). |

Exit codes of `cn-wait` and `cn-call`:

| Code | Means |
|---|---|
| 0 | Done: the build finished, the deployment is `HEALTHY`, the call worked. |
| 1 | The build or deployment failed. Also any status that `cn-wait` does not know as running: it prints the status. Known running statuses (`INITIALISING`, `BUILDING`, `SUCCESSFUL`, `FAILED`, `HEALTHY`, `UPDATING` and `FAILED_TO_UPDATE` are seen on a live tenant): builds `INITIALISING`, `INITIALIZING`, `QUEUED`, `PENDING`, `CREATED`, `SCHEDULED`, `WAITING`, `STARTED`, `STARTING`, `RUNNING`, `IN_PROGRESS`, `BUILDING` and `BUILD_` plus `STARTED`, `RUNNING`, `QUEUED` or `PENDING`; deployments `UPDATING`, `PENDING`, `QUEUED`, `CREATED`, `PROGRESSING`, `DEPLOYING`, `IN_PROGRESS`, `RUNNING`, `SYNCING`, `OUT_OF_SYNC`, `MISSING`, `STARTING`. No status yet counts as running. |
| 2 | Error: wrong arguments, no setup, the server cannot be reached, refuses the key, sends a redirect or an answer that is not JSON, or the tool answers with an error. One line on stderr, never the key. |
| 3 | Still running after `--max` seconds: run the same command again. |

## The flow

1. `cn-setup` once per computer.
2. `cn-new-agent` creates the agent and clones it.
3. `cn-new-agent` goes on with the agent repository's `start` skill (`/start` in a session opened there). It sets up
   your personal-dev environment, the CI triggers, the first release and the deployment with the agent's service
   account; for the CodeNOW Agent SDK also the local sandbox, for Google ADK a local run with the fake model and a
   check of the deployed agent's A2A card.
4. Develop on short-lived branches `feature/<name>/...`: the sandbox for seconds-long loops, a push for a preview in
   your personal-dev environment, a merge to `main` for a release to shared dev.

## Run a local agent under your own identity

A local agent can run as you, with your own Keycloak access token, instead of a deployed agent's token. The agent then
calls the AI gateway and Workforce as you; Workforce shows it as `--under-development-- <agent>`, owned by you, under
your person in the org chart. Your person must be in the organisation, else Workforce refuses the agent.

1. Install oidc-agent 5.2.0 or newer (`cn-doctor` checks it) and create the account `cn-agw` once with the device
   flow, as the agent gateway's client setup describes (`oidc-gen cn-agw --flow=device ...`). After a reboot, load it
   with `oidc-add cn-agw`.
2. In the agent's `.env`:

   ```bash
   CN_IDENTITY_PROVIDER=developer
   CN_IDENTITY_TOKEN_FILE=~/.codenow/sandbox-token/token
   CN_IDENTITY_DEVELOPER_CLIENTS=<client id of the cn-agw account>
   WORKFORCE_URL=https://<observer host>
   ```

   Leave `AI_GATEWAY_REFRESH_TOKEN` empty: the agent refuses to start as you next to a deployed agent's token.
3. `cn-sandbox up`. It writes the token (`oidc-token --time=120 cn-agw`) to the token file and starts
   `cn-sandbox token --watch` in the background, which writes a fresh one every 45 s (pid and log in the token's
   folder). `cn-sandbox down` stops it. Without the sandbox: `cn-sandbox token` once, or `cn-sandbox token --watch` in a
   terminal of its own; `cn-sandbox token --stop` stops a background refresh.

| Setting | Default | Meaning |
|---|---|---|
| `CN_OIDC_ACCOUNT` | `cn-agw` | the oidc-agent account the token comes from |
| `CN_IDENTITY_TOKEN_FILE` | `~/.codenow/sandbox-token/token` | the token file (mode 600, its folder 700); never in a repository or directly in your home folder |
| `CN_SANDBOX_TOKEN_INTERVAL` | `45` | seconds between two refreshes of `--watch` |

The token is a secret: it is never printed, and the sandbox mounts only its own copy of it.

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
