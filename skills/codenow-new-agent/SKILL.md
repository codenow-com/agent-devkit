---
name: codenow-new-agent
description: Create a new AI agent in CodeNOW from the user's coding assistant — ask what the agent does, pick or create its agent swarm, create the agent from the newest CodeNOW Agent SDK template through the CodeNOW MCP server, wait until it is ready and clone its repository, then continue in the same session with the agent repository's own start skill. Installed by the CodeNOW agent devkit (cn-setup); started by cn-new-agent.
---

# Create a new CodeNOW agent

Ask one question at a time and wait for the answer. When a question has fixed options, use the client's choice tool
(in Claude Code `AskUserQuestion`, recommended option first); otherwise ask in plain text. Say what you will create
before each create call.

If the client cannot ask the user (an autonomous mode, for example VS Code Copilot Chat in Autopilot), stop before the
first create call: tell the user to switch the chat to an interactive mode (in VS Code: Interactive) and to start
again. Never report the task as done when you created nothing.

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

- `templates_agent_list`: take the highest version of `codenow-langchain-agent-sdk` (`custom: true`).
- `scm_providers_list` and `scm_spaces_list`: the CodeNOW provider (`codenow`) and its space; ask when there is a
  choice.
- `agents_create` with `agentSwarmId`, `name`, `description` (the sentence from step 1),
  `template: {id, version, custom: true}` and
  `scm: {action: CREATE, providerType, providerId, spaceId, existingRepository: false, monoRepository: false}`.
- Wait until the agent is `READY`, usually 1 to 2 minutes: call `agents_list` (with the swarm id) every 30 to 60
  seconds and tell the user its state in one line. Do not call `agents_get` while you wait: it answers
  `400 … is not ready` until the agent is ready. Never wait in one long command: a client stops a long tool call.
- Take `scm.httpAddress` of the agent and give it to the user. The repository name carries the account prefix
  (`demo-tenant-invoice-reader`), so always take the address from the answer.

## 4. Clone

Ask for the parent folder (default: the current folder) and run `git clone <httpAddress> <agent name>` there. Then
open the clone in the user's editor when the `code` command exists (`code <agent name>`); in VS Code Copilot Chat the
user goes on in a chat of that new window.

## 5. Continue with the start skill

Do not ask the user to open a new session. Read `<agent name>/.claude/skills/start/SKILL.md` (Codex and Copilot:
`<agent name>/.agents/skills/start/SKILL.md`) and do its steps now, with the cloned repository as the working folder
for every command. Its step 1 is already done: you know the swarm and the agent.

Tell the user at the end that daily work happens in a session opened in the repository (`cd <agent name>`, then
`claude`, `codex` or `copilot`): there the repository's skills (`/build-agent`, `/sandbox` and others) are commands.
