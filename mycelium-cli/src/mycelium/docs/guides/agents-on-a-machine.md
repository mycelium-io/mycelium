# Your Agents on a Machine

Every herdr agent on a machine is listed in one place, whoever started it: the
runner, `mycelium swarm`, or you. In the app, that's the **Machines** page (in
the Mac app, **Your agents…** in the menu bar). From a terminal on that
machine:

```bash
mycelium machine
```

![The Machines page: a machine's agent CLIs, its agents, and what to fix](app-machines.png)

It lists the agents by herdr workspace, says what each is doing, and then
what's wrong, with the command that fixes each problem. Add `--json` for the
list as data.

An agent is:

- **working**, **idle**, or **blocked** (stopped at a prompt, waiting for you
  to answer it in its terminal) while it runs;
- **stopped** when its terminal is open with nothing running in it;
- **pane gone** when its terminal was closed.

## When herdr restarts

Restarting herdr's server (to update it, say) stops every agent running in it.
herdr brings each one back in its own conversation if herdr's integration for
that agent CLI is installed. Without it, the terminals come back empty and the
agents show as stopped.

```bash
mycelium machine integrations             # which are installed
mycelium machine integrations --install   # install them for the agent CLIs here
```

Installing one adds a hook to that agent CLI's own settings (for Claude Code,
`~/.claude/settings.json`), so Mycelium only does it when you say so. The Mac
app asks once.

## Restarting agents

An agent that stopped and didn't come back can be restarted. It starts again in
its own folder, as the same member, with no memory of what it was doing: it
reads its notes, then catches up from the room.

```bash
mycelium machine restart --all         # every stopped agent
mycelium machine restart reviewer      # one
```

On the Machines page, **Restart** says where each agent will start before
anything does, and the runner asks you on the machine first, as it does before
any start.

## Other fixes

```bash
mycelium machine rename reviewer "review"  # its name in herdr
mycelium machine unbind reviewer           # forget its terminal; it stays in the room
mycelium machine unbind --gone             # forget every terminal that's gone
```
