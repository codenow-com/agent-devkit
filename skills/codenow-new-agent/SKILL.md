---
name: codenow-new-agent
description: Create a new AI agent in CodeNOW from the user's coding assistant — first settle where the user works (in this terminal, or in VS Code: a terminal assistant then opens VS Code at once and stops; inside VS Code no question is asked; stored as CN_WORKSPACE), then ask what the agent does, pick or create its agent swarm, pick the template (CodeNOW Agent SDK on LangChain, or Google ADK over A2A), create the agent from its newest version through the CodeNOW MCP server, wait until it is ready, clone its repository and continue with the agent repository's own start skill. Installed by the CodeNOW agent devkit (cn-setup); started by cn-new-agent.
---

# Create a new CodeNOW agent

Ask one question at a time and wait for the answer. When a question has fixed options, use the client's choice tool
(in Claude Code `AskUserQuestion`, recommended option first); otherwise ask in plain text. Say what you will create
before each create call.

If the client cannot ask the user (an autonomous mode, for example VS Code Copilot Chat in Autopilot), stop before the
first create call: tell the user to switch the chat to an interactive mode (in VS Code: Interactive) and to start
again. Never report the task as done when you created nothing.

## Where the user works (before anything else)

Settle this first, before step 0 and before any question about the agent.

1. Inside VS Code? The flow runs inside VS Code when the client is VS Code Copilot Chat, or when any of these is set in
   the environment (check with one command, for example
   `printf '%s|%s|%s\n' "$TERM_PROGRAM" "$VSCODE_PID" "$VSCODE_IPC_HOOK_CLI"`):
   - `TERM_PROGRAM=vscode`
   - `VSCODE_PID` (any value)
   - `VSCODE_IPC_HOOK_CLI` (any value)

   When `cn-new-agent` started you through its folder-open task "CodeNOW: new agent", the user is already in VS
   Code (its integrated terminal).
   Inside VS Code, do not ask where the user works. When `CN_WORKSPACE` in `~/.codenow/config` is not set, save
   `vscode` with `cn-setup --workspace vscode`. Do all steps here, in this chat. Step 5 says how to go on after the
   clone.
2. Started with `cn-new-agent --here` (the environment variable `CN_NEW_AGENT_HERE=1`, or `--here` in the request):
   the workspace is `terminal` for this run. Do not ask and do not change `CN_WORKSPACE`.
3. Otherwise read `CN_WORKSPACE` in `~/.codenow/config` (`terminal` or `vscode`). When it is set, use it and tell the
   user in one line (change it with `cn-setup --workspace terminal|vscode`). When it is not set, ask with the choice
   tool: "Where do you want to work on the agent: in this terminal, or in VS Code?" Options: "In this terminal"
   (recommended) and "In VS Code". Save the answer with `cn-setup --workspace terminal` or
   `cn-setup --workspace vscode` (it writes only that line). If you cannot run a command, give the user that one
   command.

- `terminal`: never run `code` during the flow. Steps 0 to 5 go on in this session.
- `vscode` in a terminal assistant (Claude Code CLI, Codex, Copilot CLI) outside VS Code: switch now. Do not do step 0
  and do not ask any question about the agent here. Check that the `code` command exists (`command -v code`).
  - When it does not exist, tell the user only this and stop: "The `code` command is not on your PATH. In VS Code,
    open the Command Palette and run \"Shell Command: Install 'code' command in PATH\", then run cn-new-agent again."
  - When it exists, run `code .` (this folder is the parent folder of the clone) as the last action of this session.
    Then stop and tell the user only this: "Continue in VS Code: in the window that opened, open the chat (Claude
    Code extension, or Copilot Chat in Interactive mode) and type /codenow-new-agent (Copilot Chat: ask it to use the
    codenow-new-agent skill). Nothing else runs in this terminal."

## 0. Check and pick the MCP server

- Read `CODENOW_MCP_URL` from `~/.codenow/config`. Use the MCP server whose URL is that one; its tool prefix depends
  on the name in your client (for example `mcp__codenow__…` or `mcp__codenow-demo__…`). Do not ask the user which
  server to use and do not call other CodeNOW servers. If the client has no server with that URL, tell the user to
  run `cn-setup`.
- `agent_swarms_list` answers. If it does not: in Claude Code the user logs in through `/mcp`; Codex and Copilot CLI
  need a CodeNOW API key (`CODENOW_API_KEY`, see `cn-setup`); in VS Code Copilot Chat the user starts the server
  (Command Palette: MCP: List Servers, the server, Start Server) and enters the API key. Then start again. Do no other
  step while the server does not answer.

## 1. What the agent does

Ask for one sentence: what the agent does, for whom. Suggest a name from it. CodeNOW makes the agent id and the
repository name from the name, and it refuses some names with `400 Constraint Violation … invalid name`:

- lower case letters, digits and dashes, starting with a letter, for example `invoice-reader`;
- every part between dashes starts with a letter: `invoice-reader2` and `omi-agent2` pass, `invoice-reader-2` fails
  (observed on the demo tenant; the API does not state the rule);
- the name is not used in the swarm yet (`agents_list`).

## 2. Swarm

List the swarms with `agent_swarms_list`. A swarm groups agents that call each other and are deployed together.
The user picks one, or names a new one: letters, digits, spaces and dashes (for example `office-hot-desks` or
`Fakturacni agenti`), with no diacritics: CodeNOW answers `400 invalid name` to a letter such as `á` or `č`. CodeNOW
makes the swarm id from the name. Create it with `agent_swarm_create` (`name`, `description`).

## 3. Template and repository

- Ask which template, with the choice tool: "CodeNOW Agent SDK (LangChain) — recommended" (pipelines in YAML and
  Markdown, the local sandbox, Workforce support) or "Google ADK (A2A)" (a Google ADK agent that other agents call
  over A2A, one example tool).
- `templates_agent_list`: take the highest version of the chosen template, `custom: true`:
  `codenow-langchain-agent-sdk` or `adk-based-agent`. Compare versions as numbers (`1.10.0` is above `1.9.0`).
- Google ADK only: the template has two required properties (its `properties` in `templates_agent_list`). Ask for
  each:
  - `agentDescription`: the sentence on the agent's A2A card; other agents read it to decide whether to call this
    one. Suggest the sentence from step 1 and ask the user to confirm or change it.
  - `skillId`: the id of the agent's one A2A skill; other agents call `call_agent(agent=<agent name>,
    pipeline=<skill id>)`. Suggest a short verb from the agent's job (for example `ask`, `score`, `triage`). Lower
    case letters, digits and dashes, starting with a letter (`^[a-z][a-z0-9-]*$`); ask again when it does not match.
- `scm_providers_list` and `scm_spaces_list`: the CodeNOW provider (`codenow`) and its space; ask when there is a
  choice.
- `agents_create` with `agentSwarmId`, `name`, `description` (the sentence from step 1),
  `template: {id, version, custom: true}` and
  `scm: {action: CREATE, providerType, providerId, spaceId, existingRepository: false, monoRepository: false}`.
  For Google ADK, `template` also carries the properties as a map of strings:
  `template: {id: adk-based-agent, version, custom: true, properties: {agentDescription: "<sentence>", skillId:
  "<skill id>"}}`.
- Wait until the agent is `READY`, usually 1 to 2 minutes: call `agents_list` (with the swarm id) every 30 to 60
  seconds and tell the user its state in one line. Do not call `agents_get` while you wait: it answers
  `400 … is not ready` until the agent is ready. Never wait in one long command: a client stops a long tool call.
- Take `scm.httpAddress` of the agent and give it to the user. The repository name carries the account prefix
  (`demo-tenant-invoice-reader`), so always take the address from the answer.

## 4. Clone

Ask for the parent folder (default: the current folder) and run `git clone <httpAddress> <agent name>` there. Do not
open an editor here: step 5 does it, and only for Copilot Chat in VS Code.

## 5. Continue with the start skill

### Inside VS Code, Copilot Chat

Run `code <agent name>` as the last action of this flow: it opens the clone in a new window, because only a chat in
that window has the repository's `AGENTS.md` and skills. When the `code` command does not exist, tell the user to open
the folder `<agent name>` in VS Code (File, Open Folder). Then stop and tell the user only this: "Continue in the new
VS Code window: open Copilot Chat in Interactive mode and type /start." Do not run the start skill here.

### Inside VS Code, Claude Code

Go on as in the workspace `terminal` below, in this same session: run the start skill with the cloned repository as
the working folder for every command. Do not run `code` and do not open a new window. Only when the user asks, open the
clone in this window (`code -r <agent name>`) as the last action: VS Code then reloads the window and this chat ends.
At the end, instead of the `code <agent name>` hint, tell the user to open the folder `<agent name>` in VS Code for
daily work; there the repository's skills are commands.

### Workspace `terminal`

Never run `code`. Do not ask the user to open a new session.

Before the start skill, read `CODENOW_AGW_CLIENT_ID` and `CODENOW_WORKFORCE_URL` from `~/.codenow/config`. When both
are set, the developer identity is ready: tell the start skill so, and where it starts the local sandbox, use
`cn-sandbox up --as-me` (the local agent runs as the user and appears in Workforce as
`--under-development-- <agent name>`). When one is missing, the sandbox starts with `cn-sandbox up`; mention that
`cn-setup --only-gateway` sets up the developer identity.

Read
`<agent name>/.claude/skills/start/SKILL.md` (Codex and Copilot:
`<agent name>/.agents/skills/start/SKILL.md`) and do its steps now, with the cloned repository as the working folder
for every command. Both templates have this skill. Its step 1 is already done: you know the swarm and the agent. If
the clone has no start skill (a Google ADK agent from template 1.0.0), tell the user, run the tests and the local run
of its `README.md` ("Run locally"), and stop.

Tell the user at the end that daily work happens in a session opened in the repository (`cd <agent name>`, then
`claude`, `codex` or `copilot`): there the repository's skills are commands (CodeNOW Agent SDK: `/build-agent`,
`/sandbox` and others; Google ADK: `/a2a-protocol`, `/ai-gateway-access` and others). Last, print only the hint
`code <agent name>` to browse the code in VS Code; do not run it.
