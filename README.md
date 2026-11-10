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
| `cn-setup` | Checks the tools, adds the CodeNOW MCP server of your tenant to Claude Code, Codex and Copilot CLI, installs the devkit skills into them and checks the kubeconfig. Asks once for the MCP URL and the kubeconfig path. |
| `cn-doctor` | Reports what is there and what is missing. Changes nothing. |
| `cn-new-agent` | Starts your assistant with the `codenow-new-agent` skill: it asks what the agent does, creates its swarm and the agent from the newest CodeNOW Agent SDK template and clones the repository. |
| `cn-sandbox` | Runs the local sandbox of the agent repository you are in: `up`, `run <pipeline>`, `logs`, `events`, `status`, `down`. |
| `cn-update` | Updates the devkit to its newest release and refreshes the skills. |

## The flow

1. `cn-setup` once per computer.
2. `cn-new-agent` creates the agent and clones it.
3. Open the agent repository in your assistant. Its `start` skill sets up your personal-dev environment, the first
   release, the deployment with the agent's service account, the CI triggers and the local sandbox.
4. Develop on short-lived branches `feature/<name>/...`: the sandbox for seconds-long loops, a push for a preview in
   your personal-dev environment, a merge to `main` for a release to shared dev.

## Settings and secrets

`~/.codenow/config` keeps the MCP URL and the kubeconfig path (mode 600). The devkit stores no token.

- Claude Code logs in to CodeNOW with OAuth on first use.
- Codex and Copilot CLI cannot use the CodeNOW login, so they send a CodeNOW API key (CodeNOW UI: your profile → API
  keys) in the `X-Codenow-Api-Key` header.
  - Codex reads it from the `CODENOW_API_KEY` environment variable when it starts; `~/.codex/config.toml` keeps no
    key. Export the variable in your shell, for example from the macOS keychain:
    `export CODENOW_API_KEY="$(security find-generic-password -s codenow-api-key -w)"`.
  - Copilot CLI keeps the key in `~/.copilot/mcp-config.json`: run `CODENOW_API_KEY=<key> cn-setup` once.

## Uninstall

```bash
rm -f ~/.local/bin/cn-*; rm -rf ~/.codenow
rm -rf ~/.claude/skills/codenow-new-agent ~/.codex/skills/codenow-new-agent ~/.copilot/skills/codenow-new-agent
```

Remove the `codenow` MCP server with `claude mcp remove codenow`, `codex mcp remove codenow` and
`copilot mcp remove codenow`.
