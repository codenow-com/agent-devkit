---
name: codenow-new-agent
description: Create a new AI agent in CodeNOW from the user's coding assistant — ask what the agent does, pick or create its agent swarm, create the agent from the newest CodeNOW Agent SDK template through the CodeNOW MCP server, wait until it is ready and clone its repository, then hand over to the agent repository's own start skill. Installed by the CodeNOW agent devkit (cn-setup); started by cn-new-agent.
---

# Create a new CodeNOW agent

Ask one question at a time and wait for the answer. Say what you will create before each create call. The CodeNOW
MCP server's tools have a prefix that depends on its name in your client (for example `mcp__codenow__agents_list`);
the steps name the operation only.

## 0. Check

`agent_swarms_list` answers. If the CodeNOW MCP server is missing or not logged in, tell the user to run `cn-setup`
(and for Codex `codex mcp login codenow`), then start again.

## 1. What the agent does

Ask for one sentence: what the agent does, for whom. Suggest a name from it: lower case letters, digits and dashes,
for example `invoice-reader`. The name becomes the agent id and the repository name.

## 2. Swarm

List the swarms with `agent_swarms_list`. A swarm groups agents that call each other and are deployed together.
The user picks one, or names a new one: use letters, digits and spaces only, with no diacritics (CodeNOW answers
`400 invalid name` otherwise). Create it with `agent_swarm_create` (`name`, `description`).

## 3. Template and repository

- `templates_agent_list`: take the highest version of `codenow-langchain-agent-sdk` (`custom: true`).
- `scm_providers_list` and `scm_spaces_list`: the CodeNOW provider (`codenow`) and its space; ask when there is a
  choice.
- `agents_create` with `agentSwarmId`, `name`, `template: {id, version, custom: true}` and
  `scm: {action: CREATE, providerType, providerId, spaceId, existingRepository: false, monoRepository: false}`.
- Wait with `agents_list` until the agent is `READY` (`agents_get` answers `400 … is not ready` until then). Take
  `scm.httpAddress`; the repository name carries the account prefix.

## 4. Clone

Ask for the parent folder (default: the current folder) and run `git clone <httpAddress> <agent name>` there.

## 5. Hand over

Tell the user:

1. The agent will run under a service account owned by a team. If there is none yet, create it now in the CodeNOW
   UI: Account Settings → Users & Teams → the team → Service Accounts → Create Service Account (permissions "Follow
   team"), and copy its UUID (the magnifier of the account). The team needs the model grants at the AI gateway.
2. Open the new repository in the coding assistant (`cd <agent name>`, then `claude`, `codex` or `copilot`). The
   repository's `start` skill does the rest: personal-dev environment, first release, deployment with the service
   account, CI triggers, `.env` and the first run in the local sandbox. Claude Code offers it by itself.
