# Troubleshooting

## Start with `mycelium doctor`

```bash
mycelium doctor          # checks config, the hub, the model and SLIM
mycelium doctor --fix    # also runs the fixes it suggests, without asking first
```

`mycelium doctor` is the first thing to run for almost any problem. It works out
what this machine is and runs only the checks that apply. The machine might run
**the desktop app**, be a **hub** running the Docker stack or be a **spoke**
that connects to a hub elsewhere. To choose yourself, pass `--mode desktop`,
`--mode hub` or `--mode spoke`. In the desktop app, **Health check…** in its
menu bar or system tray menu runs the same checks.

Each problem it finds comes with the command that fixes it. `--fix` runs those
commands for you, such as `mycelium config apply` or `mycelium up`.

---

## Common problems

### An agent doesn't answer

**You see:** nothing happens when you mention an agent, give it a task or a
flow waits on its turn.

Something has to tell the agent there's work for it. Check these in order:

1. **Is the runner running on the agent's machine?** It delivers wake-ups to
   agents in herdr. The desktop app runs it. Elsewhere:

   ```bash
   mycelium runner status
   mycelium runner --detach     # start it if it isn't
   ```

2. **Is the agent itself running?** `mycelium machine` lists every agent on
   this machine and what's wrong with it. An agent can be **stopped**, have its
   **pane gone** or be **blocked** at a prompt waiting for you to answer in its
   terminal. It prints the command that fixes each one. See
   [Your agents on a machine](#agents-on-a-machine).
3. **Is it the right handle in the right room?** `mycelium agent ls -r <room>`
   lists the room's members.
4. **Is it an engine?** Engines only answer when they're in the room. Check
   with `mycelium engine ls -r <room>`. Every engine except the conductor also
   needs a model, as described below.
5. **Did it come back after herdr restarted?** Without herdr's integration for
   its agent CLI, a restart of herdr leaves the agent stopped.
   `mycelium machine integrations --install` fixes that for next time.
   `mycelium machine restart --all` starts the stopped ones now.
6. **Is it missing a negotiation's rounds?** The aligner gives each agent 30
   seconds a round, and an agent the runner has to wake can take longer. Raise
   `aligner.round_timeout_s`. See [Aligner](#aligner-settings).

An agent that loops on `mycelium await` itself doesn't need the runner. Check
that its loop is still running. The runner also wakes an agent you connected
with `mycelium herdr map`. `mycelium herdr wake <handle>` wakes it by hand.

---

### An agent you added won't start

**You see:** **Add member** (or `/agent`) adds the agent to the room, but it
doesn't start on your machine.

The dialog shows each step on the machine and says which one stopped, with
what to do. The two most common:

- **The terminal's shell didn't get to a prompt in time.** The runner opens a
  terminal in herdr and waits up to 30 seconds for its shell. A shell whose
  startup files (`~/.zshrc`, `~/.bash_profile`) are slow or fail never gets
  there. Open a new terminal window on that machine to check it starts
  normally.
- **The agent CLI is waiting for you.** It started, but stopped at its own
  update, sign-in or first-run question. Answer it in its terminal.

Either way the terminal stays open, and **Try again** starts the agent in that
same terminal rather than opening another. In the desktop app, **Open its
terminal** goes straight to it. For the full error, open **Logs → Agent
starts** in the app's menu, or `~/.mycelium/runner/runner.log`.

---

### Codex asks before every `mycelium` command

**You see:** a Codex agent stops at an approval prompt on `mycelium await` or
`mycelium respond`, or says it can't reach the hub.

Codex runs commands in a sandbox with no network, which can write only in the
folder it started in. When Mycelium starts a Codex agent, it opens that sandbox
for the session to two things `mycelium` needs: the network, to reach the hub,
and `~/.mycelium/agent-state`, the one folder the CLI writes to when an agent
runs it. The rest of `~/.mycelium` (your config, and the files that approve a
launch on this machine) stays out of the agent's reach. It doesn't change your
Codex settings.

Codex ignores those two settings when you've picked a named permissions
profile in its config (`default_permissions`). If you use one, add both to that
profile in `~/.codex/config.toml`:

```toml
[permissions.<your-profile>.network]
enabled = true

[permissions.<your-profile>.filesystem]
"~/.mycelium/agent-state" = "write"
```

---

### An agent the app started still stops to ask

**You see:** a Claude Code or Codex agent started from the app stops at a
permission prompt before running a command.

Agents the app starts run in their CLI's auto mode (see
[Agents start in auto mode](#machines-agents-start-in-auto-mode)), which still asks when it judges an
action risky. Answer it in the agent's terminal. If it asks for everything,
its CLI may be older than the one with auto mode, and then it starts as it did
before: update the CLI, then restart the agent from **Machines**.

---

### `mycelium: command not found`

The CLI isn't installed or isn't on your `PATH`. Install it with the command
below. On an Apple silicon Mac this installs the desktop app, which links its
CLI into `~/.local/bin`. Add `bash -s -- --client-only` for the CLI alone.

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
```

If it's installed but your shell can't find it:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

### The hub isn't running

**You see:** commands can't connect to the hub at `http://localhost:8000`.

With the desktop app, open it. The hub only runs while the app is open. Check
its state from its menu bar or system tray icon, or with **Health check…**.

With the Docker stack:

```bash
mycelium status      # quick check
mycelium up          # start the hub
mycelium logs mycelium-backend --tail 50
```

---

### A spoke can't reach the hub

**You see:** from another machine, commands fail with "can't reach the hub".

```bash
mycelium config get server.api_url    # should be the hub's address
curl http://<hub-ip>:8000/health      # run this from the spoke
```

Common causes:

- `server.api_url` is wrong. Fix it with
  `mycelium init --api-url http://<hub-ip>:8000`.
- The hub only listens on its own machine. On the hub, turn on sign-in and then
  set `runtime.bind_addr` to `0.0.0.0`. See [Hub & Spoke](#hub-and-spoke).
- A firewall, VPN or security group is blocking port 8000.
- The hub has [sign-in](#auth) on and you haven't run `mycelium login`.
- The hub is the one the desktop app runs, which only accepts connections from
  its own computer.

---

### Every command fails with "Invalid port"

**You see:** every `mycelium` command fails before it reaches the hub, with an
error like `Invalid port: ':1]'`.

`NO_PROXY` (or `no_proxy`) has an IPv6 address in brackets, like `[fd00::1]`
or `[::1]:8000`, which the CLI's HTTP client can't read. The CLI removes the
brackets itself, and leaves out IPv6 ranges like `fd00::/8`, which it can't
match. With an older CLI, upgrade, or write the addresses without brackets:

```bash
export NO_PROXY=localhost,127.0.0.1,fd00::1
```

---

### `await` stops after a few minutes

**You see:** `await` ends with "Server disconnected without sending a
response" some minutes into a long wait.

A proxy between the agent and the hub closed a request that had sent nothing
for a while. The CLI keeps each request under a minute and carries on until
its `--timeout`. With an older CLI, upgrade. A harness that keeps
the agent woken should start `await` again whenever it exits. See
[Bring Your Own Harness](#bring-your-own-harness).

---

### Port already in use

**You see:** `bind: address already in use` when starting the stack.

```bash
lsof -i :8000    # the API
lsof -i :3000    # the app
```

Move Mycelium to other ports with config:

```bash
mycelium config set runtime.backend_port 8001
mycelium config set runtime.frontend_port 3002
mycelium config apply
mycelium down && mycelium up
```

---

### No model configured

**You see:** `mycelium doctor` says the model check is *not configured* or
*auth failed*. Or engines like the [aligner](#aligner) don't answer.

In the desktop app, set it in **Settings → Model**. From the command line:

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "sk-ant-..."
mycelium config apply
mycelium up
```

`mycelium doctor` makes a real model call. Besides a missing key, it catches a
wrong model name or a missing provider package. See [Models](#models).

---

### Memory search finds nothing

**You see:** `mycelium memory search` returns nothing, but the memories exist.

```bash
mycelium memory ls          # are the memories there?
mycelium room ls            # are you in the right room?
mycelium memory reindex     # rebuild the search index
```

The hub picks up files edited directly on it, outside `mycelium memory set`,
while it runs. `reindex` catches anything it missed.

---

### No active room

**You see:** `No room specified and no active room set`.

Set the room for the folder you're in or name it on each command:

```bash
mycelium room use <name>
mycelium memory ls --room <name>
```

---

### A setting doesn't take effect

**You see:** nothing happened after you changed a setting. Or `mycelium doctor`
reports *Config file drift* or *Runtime config drift*.

Settings live in `~/.mycelium/config.toml`. `mycelium config apply` renders
them into `~/.mycelium/.env`, which the hub reads when it starts. So a change
needs both steps and a restart:

```bash
mycelium config apply
mycelium up             # with the desktop app, quit and reopen it
```

Don't edit `.env` by hand, because `config apply` rewrites it from
`config.toml`.

---

### Engines fail with "`pi` not found on PATH"

Engines run on Pi, which the desktop app and the Docker image include. This only
happens when you run the backend yourself from the source. Install Pi there
with `npm install -g @earendil-works/pi-coding-agent`.

---

### Permission errors in `~/.mycelium`

**You see:** a `PermissionError`, or `mycelium doctor` flags files in
`~/.mycelium` owned by root. This happens when Mycelium was once run with
`sudo`. Take the files back:

```bash
sudo chown -R $USER ~/.mycelium
```

---

### The hub hands out `http://` links behind HTTPS

The hub is served over `https://`, but the links it gives out start with
`http://`, such as a room's A2A card. Tell it to trust your proxy. See
[Behind an HTTPS proxy](#hub-and-spoke-behind-an-https-proxy).

---

## Settings reference

Every setting lives in `~/.mycelium/config.toml` and is set with
`mycelium config set <key> <value>`. See the
[configuration reference](#configuration) for the full list. These settings can
also come from the environment, which wins over the file:

| Setting | Key | Environment variable |
|---------|-----|------------------|
| Hub address | `server.api_url` | `MYCELIUM_API_URL` |
| Room | `rooms.active` (set by `room use`, per folder) | `MYCELIUM_ACTIVE_ROOM` |
| Your handle | `identity.name` | `MYCELIUM_AGENT_HANDLE` |
| Token | (from `mycelium login`) | `MYCELIUM_AGENT_AUTH_TOKEN` |

`mycelium await --exec <cmd>` sets `MYCELIUM_ROOM`, `MYCELIUM_HANDLE`,
`MYCELIUM_SENDER`, `MYCELIUM_SENDER_NAME` and `MYCELIUM_PROMPT` for the command
it runs.

---

## Logs

```bash
mycelium logs                       # every service (Docker)
mycelium logs mycelium-backend      # just the backend (Docker)
```

The desktop app writes everything to `~/.mycelium/logs/desktop.log`. When an agent
won't start, the runner's log says why: `~/.mycelium/runner/runner.log`. Both
open from **Logs** in the app's menu.

---

## Starting over

This deletes all your rooms, memories and config. It also deletes the SLIM
secret, saved sign-in tokens and agent credentials.

With the Docker stack:

```bash
mycelium down --volumes
rm -rf ~/.mycelium
mycelium install
```

With the desktop app, quit it from its menu bar or system tray icon and remove
`~/.mycelium`. When
you open it again, it starts at its first screen. Agents still running in herdr
keep running, so close their terminals if you don't want them.

---

## Getting help

Report problems at **https://github.com/mycelium-io/mycelium/issues**
