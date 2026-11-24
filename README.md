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
| `cn-new-agent` | Starts your assistant with the `codenow-new-agent` skill: it asks what the agent does, creates its swarm and the agent from the newest template you pick (CodeNOW Agent SDK on LangChain, or Google ADK over A2A) and clones the repository. With `CN_WORKSPACE=vscode` it opens VS Code at once instead (`--here`: this terminal). |
| `cn-sandbox` | Runs the local sandbox of the agent repository you are in: `up`, `run <pipeline>`, `logs`, `events`, `status` (with the agent's identity and the console URL), `down`, `hub` (all your sandboxes on one page). `cn-sandbox up --as-me` runs the agent as yourself (below); `cn-sandbox token [--watch]` writes your own access token. |
| `cn-venv` | Creates (or updates) the `.venv` of the agent repository you are in and installs its `requirements.txt`: with uv in seconds, else `python3 -m venv` and pip. Never a conda environment. |
| `cn-warm` | Downloads the dependencies of the newest published agent templates into the uv cache, so `cn-venv` of a new agent needs no download and works offline (below). |
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
2. `cn-new-agent` first settles where you work on the agent, in this terminal or in VS Code (asked once, stored as
   `CN_WORKSPACE` in `~/.codenow/config`; change it with `cn-setup --workspace terminal|vscode`).
   - Terminal: all steps go on in the same session; `code` is never run, only printed as a hint at the end.
   - VS Code: the switch happens at once, before any question about the agent. `cn-new-agent` writes a one-shot
     task "CodeNOW: new agent" (runs when the folder opens) into `.vscode/tasks.json`, runs `code .` in the current
     folder and stops. In the window that opens, the task starts your assistant (Claude Code CLI, Codex or Copilot
     CLI) in the integrated terminal, takes itself out of `tasks.json` (and deletes the file and `.vscode` when it
     created them) and the flow goes on there. The first time, VS Code asks once to allow automatic tasks: choose
     "Allow and Run". The devkit never changes your VS Code settings. If nothing starts, run the task from
     Terminal → Run Task, or type `/codenow-new-agent` in the chat. An existing `tasks.json` is merged; one with
     comments is not touched, and then, as with `CN_VSCODE_AUTOSTART=off`, the skill in a terminal assistant, or
     `--with copilot` without Copilot CLI, you open the chat (Claude Code extension, or Copilot Chat in Interactive
     mode) and type `/codenow-new-agent` (Copilot Chat: ask it to use the codenow-new-agent skill). Without the
     `code` command it tells you to install it (Command Palette: "Shell Command: Install 'code' command in PATH").
     `cn-new-agent --here` works in the terminal this once.
   - Inside VS Code (`TERM_PROGRAM=vscode`, `VSCODE_PID` or `VSCODE_IPC_HOOK_CLI` set, or Copilot Chat) the skill asks
     nothing about the workspace and runs every step there.

   It creates the agent and clones it.
3. The agent repository's `start` skill (`/start`) goes on. Terminal, and Claude Code inside VS Code: in the same
   session, with the clone as the working folder. Copilot Chat in VS Code: the clone opens in a new VS Code window,
   and you type `/start` in its chat, because only that window has the repository's skills. When the developer identity is
   set up (`cn-setup --only-gateway`), `/start` runs the local sandbox with `cn-sandbox up --as-me`. It sets up
   your personal-dev environment, the CI triggers, the first release and the deployment with the agent's service
   account, and the local sandbox; for Google ADK (template 1.1.0 or newer) also a check of the deployed agent's
   A2A card.
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
   index; commit the change); an agent of the Google ADK template (1.1.0 or newer: `google-adk` pinned, no
   `codenow-agent-sdk`) needs no SDK pin and says "ADK agent: SDK pin check not needed". Then it writes this block
   into the agent's `.env` and starts the sandbox as in step 3:

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

`cn-sandbox up` runs the agent as you by default, until you say otherwise: whenever your identity is ready
(`CODENOW_AGW_CLIENT_ID` stored, `oidc-token` gives a token, the SDK pin is 2.24.0 or newer) it writes or refreshes
the block exactly like `up --as-me`. When it is not ready, `up` prints one line with the reason and the fix (e.g.
`identity: deployment token: your own identity is not ready: no agent gateway client is set (CODENOW_AGW_CLIENT_ID);
fix: cn-setup --only-gateway`) and runs on the deployment token. The deployment token only on your command:
`cn-sandbox up --deployment-token` for one run (the next `up` runs as you again), or `cn-sandbox as-me off` from now
on in this repository (a comment line in `.env` remembers it) until `cn-sandbox as-me on` or `cn-sandbox up --as-me`.
The first deployment changes nothing of this: only the console login moves from the local dev identity provider to
the agent's own client. `cn-sandbox status` prints the mode and its source (`mode: as you (default)`,
`mode: deployment token (as-me off)`, `mode: deployment token (identity not ready: ...)`); the hub's identity chip shows
the same.

`cn-sandbox as-me status` shows the block and the stored values; `cn-sandbox as-me off` removes the block and stops
the token refresh when no other sandbox uses it. You can also write the four lines into `.env` by hand; `cn-sandbox up`
then works the same. While the block is in `.env`, a plain `cn-sandbox up` also runs the agent as you.

Before the agent's first deployment `cn-sandbox up --as-me` works too (an agent template newer than 1.7.0): the sandbox
takes the agent gateway from `CODENOW_AGW_URL` (cn-setup passes it and `CODENOW_IAM_ISSUER` on) and starts the local
dev identity provider for the console login only, signed in as you. It prints
`sandbox: agent not deployed yet: console login is local (dev IdP, as <you>); models and Workforce use your own token`;
`cn-sandbox status` says `console login: local dev IdP (not deployed yet)` and the hub shows a `pre-deploy` chip. The
next `up` after the first deployment uses the agent's own console client.

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
cn-sandbox: console login: agent's own client
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

### Runs, Valkey and search of one sandbox

Each card links to three read-only views of that sandbox's own data (`<project>` is the compose project, for
example `sandbox-customs-tariff-advisor`):

| Page | JSON | Shows |
|---|---|---|
| `/s/<project>/runs` | `/api/s/<project>/runs` | the run store's runs, newest first, 50 per page: time, pipeline, subject, status, duration, cost, `developer` and `env_class`; filters `status=`, `pipeline=`, `since=1h\|24h\|7d\|30d`, `page=` |
| `/s/<project>/runs/<run_id>` | `/api/s/<project>/runs/<run_id>` | one run: stages on a timeline, tool calls (arguments, result, duration), summary, error, output, halt handoff, facts, cost and tokens, its events from `swarm:events` (each links to its place in the stream), and the whole row as JSON |
| `/s/<project>/valkey` | `/api/s/<project>/valkey/keys?pattern=` | the keys of a pattern (`SCAN`, at most 1000) with type, TTL and size |
| `/s/<project>/valkey/<key>` | `/api/s/<project>/valkey/key?key=` | one key: a stream newest first (50 per page, `before=<id>`, filter `kind=`, hide kinds with `exclude=a,b` or the ✕ next to a kind, remembered per key in the browser), hash fields, list items, set and sorted-set members, the first 4 KB of a string |
| `/s/<project>/search?q=` | `/api/s/<project>/search?q=` | runs (id prefix, subject, pipeline, status, summary, error, output), events (the newest 5000 entries of `swarm:events` and `swarm:debug`) and key names |
| `/s/<project>/try` | `/api/s/<project>/a2a/card` | the agent card and the Try it form (below); it sends, it does not only read |

The run store and Valkey are not published to your computer: the hub reads them with `docker exec` into the
sandbox's `runstore` and `valkey` containers, each with a timeout of 8 s. Postgres gets only SELECTs that the hub
builds, in a `READ ONLY` transaction, with every value from the page as a psql variable; it reads only `agent_runs`
and adapts to the columns of older SDK versions. Valkey gets only read commands (`SCAN`, `TYPE`, `TTL`, `XRANGE`,
`XREVRANGE`, `HGETALL`, `LRANGE`, ...). Every answer is capped and masked: JWTs, bearer values, the values of keys
named like a token, secret, password or API key, and long opaque strings.

### Try it: send one A2A message

`/s/<project>/try` (the card's **Try it** link) shows the agent's card (`/.well-known/agent.json`: name,
description, url, skills with ids, descriptions, input modes and examples) and a form: a skill, a message (a text
part), an optional subject and an optional JSON object (a data part, the pipeline's facts). **Send** posts one
JSON-RPC `message/send` to the agent, built as `cn-sandbox run` builds it (`metadata.skillId`, a data part with the
facts and `subject`), and polls `tasks/get` until the task ends, for at most 120 s. The page then shows the state,
the task id, the final text, the data parts, the duration, the raw JSON-RPC (masked) and, for an SDK agent, the link
to the run's page (`/s/<project>/runs/<run_id>`).

This is the hub's only action that changes something: **the agent runs and model calls are billed.** The request
goes only to `127.0.0.1:<the sandbox's port>` (the card's url is rewritten to it). The hub accepts the POST
(`/api/s/<project>/a2a/send`) only from its own page: the same origin, a per-process CSRF token in the
`X-CN-Hub-Token` header, a JSON body of at most 32 KB; one request per sandbox at a time; the answer is read up to
4 MB.

The caller token is made for each send, the same way as `cn-sandbox run`, and is never sent to the browser,
printed or logged: `SANDBOX_CALLER_TOKEN` in the hub's environment; with `SANDBOX_IDP=dev` (or the pre-deploy marker
`sandbox/.run/predeploy`) a dev person token from `bash sandbox/sandbox.sh token person <you>`; in developer mode
your own token (`oidc-token --time=60 <CN_OIDC_ACCOUNT>`); otherwise the agent's refresh token at the tenant IAM
(read from `.env` only for that exchange). When no token can be made, the page says why; run the same call from the
terminal with `cn-sandbox run <pipeline> "<subject>" '<json>'`. A 401 means the agent did not accept the token
(signature, trusted issuer, or the audience when `A2A_AUDIENCE_MODE=enforce`; the page shows the mode the agent
logged: `shadow` accepts every token of the trusted issuer); a 403 means the token is valid but the caller may not
start the skill.

Apart from Try it, the hub only reads: Docker (`docker ps`, `docker inspect`, the agent's log), `sandbox/.run/allow` and
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

## Fast Python environments with uv

An agent's `.venv` (for `bash scripts/check.sh`) takes about 45 s with pip, a minute or more on a new computer. With
[uv](https://docs.astral.sh/uv/) and a filled cache it takes 2 s:

```bash
brew install uv          # cn-setup offers it on macOS; Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
cn-warm                  # once, and after a new template version: fills ~/.cache/uv
cn-venv                  # in the agent repository: .venv with requirements.txt
```

Measured on a Mac for the LangChain template's `requirements.txt` (SDK 2.24.0): pip 44 s with its own cache, 168 s
without; uv 15 s with an empty cache, 2 s after `cn-warm`, under 1 s with `UV_OFFLINE=1`.

- **The SDK index.** uv does not read `pip.conf`. The devkit reads it (index-url, extra-index-url, the files and
  `PIP_*` variables in pip's order) and gives uv every index except public PyPI as `UV_EXTRA_INDEX_URL`, for its own
  commands only: the tenant's `extra-index-url` first, then public PyPI, then pip's `index-url` (a JFrog proxy of PyPI
  is slow, so it is asked last). Public PyPI stays uv's default index. A JFrog URL without `/simple` gets it (uv needs
  it). `UV_INDEX_STRATEGY=unsafe-first-match`: the tenant index answers 403 for a package it does not hold, and uv's
  default strategy stops there; a package still comes from the first index that has it. The credentials in the URLs
  are never printed (`https://***@...`) and never written to a file. Your own `UV_INDEX`, `UV_INDEX_URL`,
  `UV_DEFAULT_INDEX`, `UV_EXTRA_INDEX_URL` or `UV_INDEX_STRATEGY` stay as they are.
- **Python.** `cn-venv` and `cn-warm` use uv's own Python 3.12 (`UV_PYTHON_PREFERENCE=only-managed`), never the conda
  one, also in a shell in conda base.
- **Cache.** `~/.cache/uv` (`uv cache dir`; `UV_CACHE_DIR` moves it). On Linux the devkit sets `UV_LINK_MODE=hardlink`;
  on macOS uv clones files from the cache (copy-on-write). `cn-doctor` prints the indexes (masked) and the cache size.
- **Templates.** `cn-warm` takes the highest tag `<name>-v<x.y.z>` of each template repository on
  `gitlab.cloud.codenow.com/codenow-dev/demo-tenant` (`codenow-langchain-agent-sdk`, `demo-tenant-adk-based-agent`);
  `CN_WARM_REPOS="<git url>[#<ref>] ..."` names others. It clones with your git credentials.

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
  - `cn-new-agent` cannot start the chat in VS Code: with `CN_WORKSPACE=vscode` it starts Copilot CLI in the
    integrated terminal when it is installed (`--with copilot`); otherwise it opens the folder in VS Code, and you
    write in the chat: "Use the codenow-new-agent skill to create a new CodeNOW agent and clone it into this
    folder."

## Uninstall

```bash
rm -f ~/.local/bin/cn-*; rm -rf ~/.codenow
rm -rf ~/.claude/skills/codenow-new-agent ~/.codex/skills/codenow-new-agent ~/.copilot/skills/codenow-new-agent
```

Remove the `codenow` MCP server with `claude mcp remove codenow`, `codex mcp remove codenow` and
`copilot mcp remove codenow`.

## License

Apache License 2.0, see [LICENSE](LICENSE).
