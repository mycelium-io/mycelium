# The Mac App

Mycelium for Mac is the quickest way to get going. It runs everything
Mycelium needs on your Mac, with no Docker and no terminal, and starts
your coding agents for you when you ask.

**[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**
(Apple silicon, macOS 13 or later)

## Install

1. Open the download and drag **Mycelium** into **Applications**.
2. Open Mycelium from Applications. The first time, macOS asks whether to
   open an app downloaded from the internet; choose **Open**.
3. A few short steps set it up:
   - **Where should your rooms live?** **On this Mac** keeps your rooms,
     notes and agents here; pick it to try Mycelium on your own or to give a
     demo. **On my team's hub** joins rooms someone else runs: paste the
     hub's address, or open an invite link a teammate sent you.
   - **A model**, for rooms on this Mac: pick a provider and paste its key.
     Mycelium's own agents think with it; see [Models](#models). You can skip
     this and add it later.
   - **Agents on this Mac**: the agent programs it found, and the folder they
     may work in.
   - **Ready to start**: what you chose, then **Start Mycelium**.

![The first step: where your rooms live](desktop-onboarding.png)

Before you start, **What this sets up on your Mac** lists every change it
makes. In short: `mycelium` and `herdr` are linked into `~/.local/bin` so
agents can run them, your settings and rooms live in `~/.mycelium`, and the
hub runs only while the app is open, reachable only from this Mac. It needs
no admin password and writes nothing outside your home folder.

## What's inside

The app carries everything, pinned to versions tested together:

- the Mycelium hub and its UI;
- a [SLIM](#slim) node, for the rooms' messages;
- [herdr](#herdr), where your agents run as interactive sessions you can
  watch and type to;
- the `mycelium` CLI, which agents use to work in rooms;
- Pi, which engines like the [aligner](#aligner) think with, and the model
  that powers memory search, so search works offline.

It doesn't include an agent CLI. Install the one you use (Claude Code,
Codex, OpenCode and others), and the app finds it.

## Adding agents

In a room, open **Members** and press **Add**. Pick **Your machine**, start
from a role or write your own instructions, and add it. The agent opens in a
herdr terminal, already a member of the room.

![Adding an agent that runs on your Mac](desktop-add-member.png)

The same dialog adds the other kinds of member: an engine the hub runs, an
A2A service, or a coding agent you already have open. See
[Start Agents From the App](#machines) for how the app starts agents on your
machine.

To watch or talk to an agent, open the **Machines** page and choose **Open
terminal**, or use **Agents terminal** in the menu bar.

## The menu bar

Mycelium lives in the menu bar while it runs. Closing the window leaves it
running; **Quit Mycelium** stops the hub. Agents you started keep running in
herdr either way.

- the state of the hub, the SLIM node and the runner;
- **Open Mycelium** and **Agents terminal**;
- **Start at login**;
- **Health check…**, below;
- **Settings…** (also **Mycelium → Settings…**, ⌘,): where rooms live and
  starting at login, the [model](#models), the agents' folder, and usage
  stats, one section at a time. **Cancel** goes back to your rooms;
  **Save** restarts Mycelium with the change;
- **Check for Updates…**.

## Updates

The app checks for a new release shortly after it opens, and when you choose
**Check for Updates…**. If one is out, it asks before installing it, then
restarts. Agents keep running in herdr through the restart. An update installs
only if it carries the release's signature, so the app never installs anything
the project didn't publish.

## Health check

**Health check…** shows each part the app runs and whether it's working,
with what to do when something isn't. It runs the same checks as
`mycelium doctor --mode desktop`.

![The health check](desktop-health.png)

## Inviting people

In **Members**, **Invite** copies a link to the room. Opening it offers the
app (which joins that hub and room), the download, or the browser.

## The command line

Everything the app does is also a command, for a Linux machine, a server, or
if you'd rather use a terminal: `mycelium desktop serve` runs the same hub
without the window. See [Run it on a server instead](#walk-server) for the
full CLI setup.
